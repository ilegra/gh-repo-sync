import base64
import re
import urllib.parse
from typing import Any

import requests
import structlog
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from src.git.client import Git
from src.providers.base import Branch, OriginProvider, validate_branch_name

logger = structlog.get_logger(__name__)


class BitbucketCloudProvider(OriginProvider):
    """Origin repository provider implementation for Bitbucket Cloud."""

    def __init__(
        self,
        repo_url: str,
        token: str,
        username: str | None = None,
        git: Git | None = None,
        remote_name: str = "origin_remote",
    ):
        """
        Initializes the Bitbucket Cloud Provider.

        Args:
            repo_url: Bitbucket Cloud repository URL.
            token: Bitbucket App Password or Repository/Workspace Access Token.
            username: Optional Bitbucket username for App Password authentication.
            git: Optional initialized Git client.
            remote_name: Name of git remote tracking this repository.
        """
        self.repo_url = repo_url
        self.token = token
        self.username = username.strip() if username and username.strip() else None
        self.git = git
        self.remote_name = remote_name
        self._session: requests.Session | None = None
        self._repo_metadata: dict[str, Any] | None = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            session = requests.Session()
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET"],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._session = session
        return self._session

    def _get_auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.username:
            credentials = f"{self.username}:{self.token}".encode()
            b64_creds = base64.b64encode(credentials).decode("utf-8")
            headers["Authorization"] = f"Basic {b64_creds}"
        else:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _parse_bitbucket_url(self) -> tuple[str, str] | None:
        """
        Parses Bitbucket Cloud URL into (workspace, repo_slug).

        Supports:
        - https://bitbucket.org/{workspace}/{repo_slug}
        - https://bitbucket.org/{workspace}/{repo_slug}.git
        - https://{user}@bitbucket.org/{workspace}/{repo_slug}.git
        - git@bitbucket.org:{workspace}/{repo_slug}.git
        """
        clean_url = self.repo_url.strip().rstrip("/")
        https_regex = (
            r"^https?://(?:[^/@]+@)?bitbucket\.org/([^/]+)/([^/]+?)(?:\.git)?$"
        )
        ssh_regex = r"^git@bitbucket\.org:([^/]+)/([^/]+?)(?:\.git)?$"

        for pattern in (https_regex, ssh_regex):
            match = re.match(pattern, clean_url)
            if match:
                return match.group(1), match.group(2)

        return None

    def get_authenticated_url(self) -> str:
        """Returns the origin remote git URL with authentication credentials."""
        parsed = self._parse_bitbucket_url()
        auth_prefix = (
            f"{urllib.parse.quote(self.username, safe='')}:{self.token}"
            if self.username
            else f"x-token-auth:{self.token}"
        )

        if parsed:
            workspace, repo_slug = parsed
            return f"https://{auth_prefix}@bitbucket.org/{workspace}/{repo_slug}.git"

        clean_url = self.repo_url.strip()
        if clean_url.startswith("https://"):
            clean_url = clean_url[len("https://") :]
        elif clean_url.startswith("http://"):
            clean_url = clean_url[len("http://") :]
        if "@" in clean_url.split("/", 1)[0]:
            clean_url = clean_url.split("@", 1)[1]
        return f"https://{auth_prefix}@{clean_url}"

    def get_repo_name(self) -> str:
        """Returns the base repository name."""
        parsed = self._parse_bitbucket_url()
        if parsed:
            return parsed[1]
        clean = self.repo_url.strip().rstrip("/").removesuffix(".git")
        return clean.split("/")[-1]

    def _fetch_repo_metadata(self) -> dict[str, Any] | None:
        if self._repo_metadata is not None:
            return self._repo_metadata

        parsed = self._parse_bitbucket_url()
        if not parsed:
            logger.debug(
                "Could not parse Bitbucket workspace/repo_slug from URL for API check",
                url=self.repo_url,
            )
            return None

        workspace, repo_slug = parsed
        workspace_q = urllib.parse.quote(workspace, safe="")
        repo_q = urllib.parse.quote(repo_slug, safe="")
        api_url = f"https://api.bitbucket.org/2.0/repositories/{workspace_q}/{repo_q}"

        try:
            session = self._get_session()
            response = session.get(
                api_url, headers=self._get_auth_headers(), timeout=10
            )
            if response.status_code == 200:
                data: dict[str, Any] = response.json()
                self._repo_metadata = data
                return data
            logger.warning(
                "Bitbucket Cloud API returned non-200 status code",
                status_code=response.status_code,
                body=response.text[:200],
            )
        except Exception as e:
            logger.warning(
                "Failed to query Bitbucket Cloud repository metadata via API",
                error=str(e),
            )

        return None

    def is_repo_disabled(self) -> bool:
        """Checks if the origin Bitbucket Cloud repository is archived or read-only."""
        data = self._fetch_repo_metadata()
        if not data:
            return False

        is_disabled = bool(
            data.get("is_archived", False) or data.get("is_read_only", False)
        )
        logger.info(
            "Checked Bitbucket Cloud repository status via API",
            repo=self.get_repo_name(),
            is_disabled=is_disabled,
        )
        return is_disabled

    def _ensure_remote(self) -> None:
        if not self.git:
            raise RuntimeError(
                "Git client is not initialized for BitbucketCloudProvider"
            )
        remotes_out = self.git.run("remote", check=False)
        existing_remotes = (
            remotes_out.stdout.splitlines() if remotes_out.success else []
        )
        if self.remote_name not in existing_remotes:
            self.git.remote_add(self.remote_name, self.get_authenticated_url())

    def get_remote_ref(self, branch_name: str) -> str:
        """
        Returns the remote reference string for a given branch name.

        Args:
            branch_name: Unqualified branch name.

        Returns:
            str: Full remote reference path for git operations.
        """
        return f"refs/remotes/{self.remote_name}/{branch_name}"

    def _get_default_branch_name(self) -> str:
        metadata = self._fetch_repo_metadata()
        if metadata:
            mainbranch = metadata.get("mainbranch")
            if isinstance(mainbranch, dict):
                name = mainbranch.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()

        if not self.git:
            return "main"

        sym_res = self.git.symbolic_ref(
            f"refs/remotes/{self.remote_name}/HEAD", short=True
        )
        if (
            sym_res.success
            and isinstance(sym_res.stdout, str)
            and sym_res.stdout.strip()
        ):
            return sym_res.stdout.strip().removeprefix(f"{self.remote_name}/")
        return "main"

    def get_branches(self) -> list[Branch]:
        """
        Fetches remote references from origin and returns all valid branches.

        Returns:
            list[Branch]: List of valid branch objects available at origin,
                with the default branch indicated via `is_default=True`.
        """
        if not self.git:
            raise RuntimeError(
                "Git client is not initialized for BitbucketCloudProvider"
            )

        self._ensure_remote()

        fetch_origin = self.git.fetch(self.remote_name, prune=True)
        if not fetch_origin.success:
            stderr_lower = fetch_origin.stderr.lower()
            if (
                "is disabled" in stderr_lower
                or "archived" in stderr_lower
                or self.is_repo_disabled()
            ):
                logger.warning("Origin repository is disabled or archived.")
                return []
            fetch_origin.raise_for_status()

        default_branch_name = self._get_default_branch_name()
        prefix = f"refs/remotes/{self.remote_name}/"
        raw_refs = self.git.for_each_ref(prefix)
        branches: list[Branch] = []
        for ref in raw_refs:
            branch_name = ref.removeprefix(prefix)
            if branch_name == "HEAD":
                continue
            if not validate_branch_name(branch_name, self.git):
                logger.warning(
                    "Ignoring invalid Origin branch name", branch=branch_name
                )
                continue
            branches.append(
                Branch(
                    name=branch_name,
                    remote_ref=f"{prefix}{branch_name}",
                    is_default=(branch_name == default_branch_name),
                )
            )

        if branches and not any(b.is_default for b in branches):
            fallback_index = 0
            for idx, b in enumerate(branches):
                if b.name in ("main", "master"):
                    fallback_index = idx
                    break
            branches[fallback_index] = branches[fallback_index].model_copy(
                update={"is_default": True}
            )

        return branches

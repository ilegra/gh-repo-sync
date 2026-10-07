import base64
import re
import urllib.parse

import requests
import structlog
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from src.git.client import Git
from src.providers.base import Branch, OriginProvider, validate_branch_name

logger = structlog.get_logger(__name__)


class AzureDevOpsProvider(OriginProvider):
    """Origin repository provider implementation for Azure DevOps."""

    def __init__(
        self,
        repo_url: str,
        pat: str,
        git: Git | None = None,
        remote_name: str = "origin_remote",
    ):
        """
        Initializes the Azure DevOps Provider.

        Args:
            repo_url: Azure DevOps repository URL.
            pat: Personal Access Token for authentication.
            git: Optional initialized Git client.
            remote_name: Name of git remote tracking this repository.
        """
        self.repo_url = repo_url
        self.pat = pat
        self.git = git
        self.remote_name = remote_name
        self._session: requests.Session | None = None

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

    def get_authenticated_url(self) -> str:
        """Returns the origin remote git URL with authentication credentials."""
        clean_url = self.repo_url
        if clean_url.startswith("https://"):
            clean_url = clean_url[len("https://") :]
        elif clean_url.startswith("http://"):
            clean_url = clean_url[len("http://") :]
        return f"https://anything:{self.pat}@{clean_url}"

    def get_repo_name(self) -> str:
        """Returns the base repository name."""
        clean = self.repo_url.rstrip("/").removesuffix(".git")
        return clean.split("/")[-1]

    def _parse_ado_url(self) -> tuple[str, str, str] | None:
        """
        Parses Azure DevOps URL into (org, project, repo).
        Supports:
        - https://dev.azure.com/{org}/{project}/_git/{repo}
        - https://{org}.visualstudio.com/{project}/_git/{repo}
        """
        dev_azure_regex = r"^https://dev\.azure\.com/([^/]+)/([^/]+)/_git/(.+)$"
        vs_regex = r"^https://([^/]+)\.visualstudio\.com/([^/]+)/_git/(.+)$"

        m = re.match(dev_azure_regex, self.repo_url)
        if m:
            return m.group(1), m.group(2), m.group(3)

        m = re.match(vs_regex, self.repo_url)
        if m:
            return m.group(1), m.group(2), m.group(3)

        return None

    def is_repo_disabled(self) -> bool:
        """Checks if the origin Azure DevOps repository is disabled or archived."""
        parsed = self._parse_ado_url()
        if not parsed:
            logger.debug(
                "Could not parse ADO org/project/repo from URL for API check",
                url=self.repo_url,
            )
            return False

        org, project, repo = parsed
        project_url = urllib.parse.quote(project)
        repo_url = urllib.parse.quote(repo)
        api_url = f"https://dev.azure.com/{org}/{project_url}/_apis/git/repositories/{repo_url}?api-version=7.1"

        b64_pat = base64.b64encode(f":{self.pat}".encode()).decode("utf-8")
        headers = {
            "Authorization": f"Basic {b64_pat}",
            "Content-Type": "application/json",
        }

        try:
            session = self._get_session()
            response = session.get(api_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                is_disabled = bool(data.get("isDisabled", False))
                logger.info(
                    "Checked ADO repository status via API",
                    repo=repo,
                    is_disabled=is_disabled,
                )
                return is_disabled
            else:
                logger.warning(
                    "Azure DevOps API returned non-200 status code",
                    status_code=response.status_code,
                    body=response.text[:200],
                )
        except Exception as e:
            logger.warning(
                "Failed to check if Azure DevOps repo is disabled via API", error=str(e)
            )

        return False

    def _ensure_remote(self) -> None:
        if not self.git:
            raise RuntimeError("Git client is not initialized for AzureDevOpsProvider")
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
            raise RuntimeError("Git client is not initialized for AzureDevOpsProvider")

        self._ensure_remote()

        fetch_origin = self.git.fetch(self.remote_name, prune=True)
        if not fetch_origin.success:
            if "is disabled" in fetch_origin.stderr.lower() or self.is_repo_disabled():
                logger.warning("Origin repository is disabled.")
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

import re

import structlog

from src.git.client import Git
from src.providers.base import Branch, DestinationProvider, validate_branch_name

logger = structlog.get_logger(__name__)


class GitHubProvider(DestinationProvider):
    """Destination repository provider implementation for GitHub."""

    def __init__(
        self,
        repo_url: str,
        token: str,
        git: Git,
        remote_name: str = "destination_remote",
    ):
        """
        Initializes the GitHub Provider.

        Args:
            repo_url: The destination GitHub repository URL.
            token: Authentication token.
            git: Initialized Git client for executing commits.
            remote_name: Name of git remote tracking this repository.
        """
        self.repo_url = repo_url
        self.token = token
        self.git = git
        self.remote_name = remote_name

    def get_authenticated_url(self) -> str:
        """Returns the destination remote git URL with authentication credentials."""
        clean_url = self.repo_url
        if clean_url.startswith("https://"):
            clean_url = clean_url[len("https://") :]
        elif clean_url.startswith("http://"):
            clean_url = clean_url[len("http://") :]
        return f"https://x-access-token:{self.token}@{clean_url}"

    def get_repo_name(self) -> str:
        """Returns the base repository name."""
        clean = self.repo_url.rstrip("/").removesuffix(".git")
        return clean.split("/")[-1]

    def _ensure_remote(self) -> None:
        if not self.git:
            raise RuntimeError("Git client is not initialized for GitHubProvider")
        remotes_out = self.git.run("remote", check=False)
        existing_remotes = (
            remotes_out.stdout.splitlines() if remotes_out.success else []
        )
        if self.remote_name not in existing_remotes:
            if "origin" in existing_remotes:
                self.git.run("remote", "rename", "origin", self.remote_name, check=True)
            else:
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
        Fetches remote references from destination and returns all valid branches.

        Returns:
            list[Branch]: List of valid branch objects available at destination,
                with the default branch indicated via `is_default=True`.
        """
        if not self.git:
            raise RuntimeError("Git client is not initialized for GitHubProvider")

        self._ensure_remote()
        fetch_res = self.git.fetch(self.remote_name, prune=True)
        if not fetch_res.success:
            fetch_res.raise_for_status()

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
                    "Ignoring invalid Destination branch name", branch=branch_name
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

    def commit(
        self,
        subject: str,
        author: str,
        body: str | None = None,
        allow_empty: bool = False,
    ) -> None:
        """
        Commits changes to the GitHub repository, injecting '[skip actions]' into the
        commit subject if it is not already present, preventing recursive workflow runs.

        Args:
            subject: The commit message subject line.
            author: The author of the commit (e.g. 'Name <email>').
            body: Optional commit message body.
            allow_empty: Allow creating an empty commit if there are no changes.
        """
        marker = "[skip actions]"

        # Prevent duplication if upstream already skips CI/actions
        skip_patterns = [
            r"\[skip actions\]",
            r"\[skip ci\]",
            r"\[ci skip\]",
            r"\[no ci\]",
            r"\[actions skip\]",
        ]
        pattern = "|".join(skip_patterns)

        if not re.search(pattern, subject, re.IGNORECASE):
            subject = f"{subject} {marker}"

        msg = f"{subject}\n\n{body}" if body else subject

        if self.git.status_porcelain():
            self.git.commit(msg, author=author)
        elif allow_empty:
            self.git.commit(msg, author=author, allow_empty=True)

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

    def get_default_branch(self) -> Branch:
        """
        Returns the default branch of the destination repository.

        Returns:
            Branch: Default branch instance.
        """
        if not self.git:
            return Branch(name="main", remote_ref=self.get_remote_ref("main"))

        sym_res = self.git.symbolic_ref(
            f"refs/remotes/{self.remote_name}/HEAD", short=True
        )
        if sym_res.success and sym_res.stdout:
            name = sym_res.stdout.removeprefix(f"{self.remote_name}/")
        else:
            name = "main"
        return Branch(name=name, remote_ref=self.get_remote_ref(name))

    def get_branches(self) -> list[Branch]:
        """
        Fetches remote references from destination and returns all valid branches.

        Returns:
            list[Branch]: List of valid branch objects available at destination.
        """
        if not self.git:
            raise RuntimeError("Git client is not initialized for GitHubProvider")

        self._ensure_remote()
        fetch_res = self.git.fetch(self.remote_name, prune=True)
        if not fetch_res.success:
            fetch_res.raise_for_status()

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
                Branch(name=branch_name, remote_ref=f"{prefix}{branch_name}")
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

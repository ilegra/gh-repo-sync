import re

from src.git.client import Git
from src.providers.base import DestinationProvider


class GitHubProvider(DestinationProvider):
    def __init__(self, repo_url: str, token: str, git: Git):
        """
        Initializes the GitHub Provider.

        Args:
            repo_url: The destination GitHub repository URL.
            token: Authentication token.
            git: Initialized Git client for executing commits.
        """
        self.repo_url = repo_url
        self.token = token
        self.git = git

    def get_authenticated_url(self) -> str:
        clean_url = self.repo_url
        if clean_url.startswith("https://"):
            clean_url = clean_url[len("https://") :]
        elif clean_url.startswith("http://"):
            clean_url = clean_url[len("http://") :]
        return f"https://x-access-token:{self.token}@{clean_url}"

    def get_repo_name(self) -> str:
        clean = self.repo_url.rstrip("/").removesuffix(".git")
        return clean.split("/")[-1]

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

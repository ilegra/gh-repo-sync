import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.git.client import Git


class Branch(BaseModel):
    """Represents a repository branch and its associated remote reference."""

    name: str = Field(..., description="Branch name without remote prefix")
    remote_ref: str = Field(
        ...,
        description="Remote-prefixed reference used in git operations",
    )


def validate_branch_name(branch: str, git: "Git | None" = None) -> bool:
    """Validates whether a branch name is safe and valid."""
    if not branch or branch.startswith("-"):
        return False
    # Reject unsafe characters not conforming to safe branch regex
    if re.search(r"[^a-zA-Z0-9._/-]", branch):
        return False
    if ".." in branch or branch.endswith("/") or branch.startswith("/"):
        return False
    if git:
        return git.check_ref_format(branch)
    return True


class OriginProvider(ABC):
    """Abstract interface representing an origin repository provider."""

    @abstractmethod
    def get_authenticated_url(self) -> str:
        """Returns the origin remote git URL with authentication credentials."""
        pass

    @abstractmethod
    def is_repo_disabled(self) -> bool:
        """Checks if the origin repository is disabled or archived via API."""
        pass

    @abstractmethod
    def get_repo_name(self) -> str:
        """Returns the base repository name."""
        pass

    @abstractmethod
    def get_branches(self) -> list[Branch]:
        """
        Fetches remote references from origin and returns all valid branches.

        Returns:
            list[Branch]: List of valid branch objects available at origin.
        """
        pass

    @abstractmethod
    def get_default_branch(self) -> Branch:
        """
        Returns the default branch of the origin repository.

        Returns:
            Branch: Default branch instance.
        """
        pass

    @abstractmethod
    def get_remote_ref(self, branch_name: str) -> str:
        """
        Returns the remote reference string for a given branch name.

        Args:
            branch_name: Unqualified branch name.

        Returns:
            str: Full remote reference path for git operations.
        """
        pass


class DestinationProvider(ABC):
    """Abstract interface representing a destination repository provider."""

    @abstractmethod
    def get_authenticated_url(self) -> str:
        """Returns the destination remote git URL with authentication credentials."""
        pass

    @abstractmethod
    def get_repo_name(self) -> str:
        """Returns the base repository name."""
        pass

    @abstractmethod
    def commit(
        self,
        subject: str,
        author: str,
        body: str | None = None,
        allow_empty: bool = False,
    ) -> None:
        """
        Commits changes to the destination repository, handling any provider-specific
        message formatting (like CI skip markers).

        Args:
            subject: The commit message subject line.
            author: The author of the commit (e.g. 'Name <email>').
            body: Optional commit message body.
            allow_empty: Allow creating an empty commit if there are no changes.
        """
        pass

    @abstractmethod
    def get_branches(self) -> list[Branch]:
        """
        Fetches remote references from destination and returns all valid branches.

        Returns:
            list[Branch]: List of valid branch objects available at destination.
        """
        pass

    @abstractmethod
    def get_default_branch(self) -> Branch:
        """
        Returns the default branch of the destination repository.

        Returns:
            Branch: Default branch instance.
        """
        pass

    @abstractmethod
    def get_remote_ref(self, branch_name: str) -> str:
        """
        Returns the remote reference string for a given branch name.

        Args:
            branch_name: Unqualified branch name.

        Returns:
            str: Full remote reference path for git operations.
        """
        pass

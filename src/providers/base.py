import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.git.client import Git


@dataclass
class PullRequest:
    """Pure data container representing a pull request."""

    id: str
    title: str
    description: str
    source_branch: str
    target_branch: str
    author: str
    state: str = "open"
    is_draft: bool = False
    is_from_fork: bool = False
    url: str = ""
    number: int | None = None
    reviewers: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    head_sha: str = ""


@dataclass
class PullRequestComment:
    """Pure data container representing a pull request comment."""

    id: str
    body: str
    author: str
    created_at: str = ""
    updated_at: str = ""
    file_path: str | None = None
    line: int | None = None
    side: str | None = None
    start_line: int | None = None
    start_side: str | None = None
    parent_id: str | None = None
    is_resolved: bool = False
    resolved_by: str | None = None
    node_id: str | None = None


@dataclass
class PrSyncResult:
    """Pure data container representing pull request synchronization results."""

    created_prs: list[int] = field(default_factory=list)
    updated_prs: list[int] = field(default_factory=list)
    closed_prs: list[int] = field(default_factory=list)
    synced_pr_comments: int = 0
    errors: list[str] = field(default_factory=list)


class PrExporter(ABC):
    """Abstract interface for exporting pull requests and comments from an origin."""

    @abstractmethod
    def get_open_pull_requests(self) -> list[PullRequest]:
        """Returns all currently open pull requests from the origin repository."""
        pass

    @abstractmethod
    def get_pull_request(self, pr_id: str) -> PullRequest | None:
        """Returns a single pull request by origin ID, or None if not found."""
        pass

    @abstractmethod
    def get_pull_request_comments(self, pr_id: str) -> list[PullRequestComment]:
        """Returns all non-deleted comments for the given origin pull request ID."""
        pass


class PrImporter(ABC):
    """Abstract interface for reconciling pull requests on a destination provider."""

    @abstractmethod
    def reconcile(
        self,
        origin_prs: list[PullRequest],
        pr_exporter: PrExporter,
        branch_mapping: dict[str, str] | None = None,
        available_branches: set[str] | None = None,
        user_mapping: dict[str, str] | None = None,
    ) -> PrSyncResult:
        """
        Reconciles open and completed pull requests and their comments on destination.

        Args:
            origin_prs: Open pull requests fetched from the origin provider.
            pr_exporter: Exporter used to fetch comments and final PR states.
            branch_mapping: Optional mapping from origin to destination branch names.
            available_branches: Optional set of destination branch names that exist.
            user_mapping: Optional explicit mapping from origin display names to
                destination user logins.

        Returns:
            PrSyncResult: Summary of created, updated, closed PRs, comments, and errors.
        """
        pass


class Branch(BaseModel):
    """Represents a repository branch and its associated remote reference."""

    name: str = Field(..., description="Branch name without remote prefix")
    remote_ref: str = Field(
        ...,
        description="Remote-prefixed reference used in git operations",
    )
    is_default: bool = Field(
        default=False,
        description=(
            "Indicates whether this branch is the default branch of the repository"
        ),
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
            list[Branch]: List of valid branch objects available at origin,
                with the default branch indicated via `is_default=True`.
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

    def get_pr_exporter(self) -> PrExporter | None:
        """Returns an optional PR exporter if supported by this origin provider."""
        return None


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
            list[Branch]: List of valid branch objects available at destination,
                with the default branch indicated via `is_default=True`.
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

    def get_pr_importer(self) -> PrImporter | None:
        """Returns an optional PR importer if supported by this destination provider."""
        return None

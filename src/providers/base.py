from abc import ABC, abstractmethod


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

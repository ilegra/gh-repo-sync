from abc import ABC, abstractmethod


class OriginProvider(ABC):
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
    @abstractmethod
    def get_authenticated_url(self) -> str:
        """Returns the destination remote git URL with authentication credentials."""
        pass

    @abstractmethod
    def get_repo_name(self) -> str:
        """Returns the base repository name."""
        pass

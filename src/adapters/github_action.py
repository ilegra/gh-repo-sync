"""GitHub Actions output adapter for publishing sync results."""

from src.config import SyncResult


class GithubActionOutputAdapter:
    """Adapter for publishing synchronization results as GitHub Action outputs."""

    def publish(self, result: SyncResult) -> None:
        """
        Publishes the synchronization result as a GitHub Actions output variable.

        Args:
            result: The synchronization result data structure to serialize and publish.
        """
        payload = result.model_dump_json()
        self._print_output("sync-result", payload)

    def _print_output(self, name: str, value: str) -> None:
        print(f"::set-output name={name}::{value}")

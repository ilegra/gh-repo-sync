import os
import shutil
import sys
import tempfile

import structlog
from structlog.types import Processor

from src.config import SyncConfig
from src.core.sync import SyncManager
from src.git.client import Git
from src.providers.azure_devops import AzureDevOpsProvider
from src.providers.github import GitHubProvider


def _setup_logging() -> None:
    is_github_actions = bool(os.getenv("GITHUB_ACTIONS"))
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if is_github_actions:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def main() -> None:
    """CLI entrypoint for repository synchronization execution."""
    _setup_logging()
    logger = structlog.get_logger(__name__)

    try:
        config = SyncConfig()
    except Exception as e:
        logger.error("Configuration validation error", error=str(e))
        sys.exit(1)

    # Setup isolated git workspace
    temp_dir = tempfile.mkdtemp(prefix="repo_sync_")
    repo_dir = os.path.join(temp_dir, "repo")
    os.makedirs(repo_dir, exist_ok=True)

    try:
        mask_patterns = [config.origin_token, config.destination_token]
        git_client = Git(repo_dir, mask_patterns=mask_patterns)

        # Origin provider factory (Azure DevOps is the currently supported origin)
        origin_provider = AzureDevOpsProvider(
            repo_url=config.origin_url,
            pat=config.origin_token,
            git=git_client,
            remote_name="origin_remote",
        )

        # Destination provider factory (GitHub)
        destination_provider = GitHubProvider(
            repo_url=config.destination_url,
            token=config.destination_token,
            git=git_client,
            remote_name="destination_remote",
        )

        manager = SyncManager(
            config=config,
            origin_provider=origin_provider,
            destination_provider=destination_provider,
            git_client=git_client,
        )

        result = manager.execute()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    if result.already_disabled:
        logger.info("Origin repository is disabled. Sync skipped.")
        sys.exit(0)

    if result.errors:
        logger.error("Sync completed with errors", errors=result.errors)
        sys.exit(1)

    logger.info(
        "Repository sync completed successfully",
        synced=result.synced_branches,
        removed=result.removed_branches,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()

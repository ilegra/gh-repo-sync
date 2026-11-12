import logging
import os
import shutil
import sys
import tempfile

import structlog
from structlog.types import Processor

from src.adapters.github_action import GithubActionOutputAdapter
from src.config import SyncConfig
from src.core.sync import SyncManager
from src.git.client import Git
from src.providers.azure_devops import AzureDevOpsProvider
from src.providers.github import GitHubProvider
from src.version import get_version


def _setup_logging() -> None:
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(colors=True),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def main(argv: list[str] | None = None) -> int:
    """
    CLI entrypoint for repository synchronization execution.

    Args:
        argv: Optional command-line arguments. Defaults to sys.argv[1:].

    Returns:
        int: 0 on success, 1 on failure.
    """
    if argv is None:
        argv = sys.argv[1:]

    if "--version" in argv or "-V" in argv:
        print(f"gh-repo-sync {get_version()}")
        return 0

    if "--help" in argv or "-h" in argv:
        print("Usage: gh-repo-sync")
        print("\nRepository synchronization engine (Origin to GitHub).\n")
        print("Options:")
        print("  -h, --help     Show this help message and exit")
        print("  -V, --version  Show application version and exit\n")
        print("Environment Variables:")
        print("  ORIGIN_URL                   Origin repository URL (required)")
        print("  ORIGIN_TOKEN                 Origin PAT / access token (required)")
        print("  DESTINATION_URL              Destination GitHub repo URL (required)")
        print("  DESTINATION_TOKEN            Destination GitHub token (required)")
        print("  ORIGIN_EXCLUSIVE_PATHS       Paths on Origin to purge from sync")
        print("  DESTINATION_EXCLUSIVE_PATHS  Paths on Destination to keep protected")
        print("  BRANCH_MAPPING               Branch mapping origin:dest")
        print("  COMMITTER_NAME               Committer name fallback")
        print("  COMMITTER_EMAIL              Committer email fallback")
        return 0

    _setup_logging()
    logger = structlog.get_logger(__name__)

    try:
        config = SyncConfig()
    except Exception as e:
        logger.error("Configuration validation error", error=str(e))
        return 1

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

        adapter = GithubActionOutputAdapter()
        adapter.publish(result)
    except Exception as e:
        logger.error("Synchronization failed", error=str(e))
        return 1
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    if result.already_disabled:
        logger.info("Origin repository is disabled. Sync skipped.")
        return 0

    if result.errors:
        logger.error("Sync completed with errors", errors=result.errors)
        return 1

    logger.info(
        "Repository sync completed successfully",
        evaluated=result.evaluated_branches,
        updated=result.updated_branches,
        removed=result.removed_branches,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

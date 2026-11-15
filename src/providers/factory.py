from src.config import SyncConfig
from src.git.client import Git
from src.providers.azure_devops import AzureDevOpsProvider
from src.providers.base import OriginProvider
from src.providers.bitbucket_cloud import BitbucketCloudProvider


def get_origin_provider(
    config: SyncConfig,
    git_client: Git | None = None,
    remote_name: str = "origin_remote",
) -> OriginProvider:
    """
    Resolves and instantiates the appropriate OriginProvider for the given config.

    Uses `config.origin_provider` when explicitly specified, otherwise auto-detects
    the provider from `config.origin_url`.

    Args:
        config: Synchronizer configuration settings.
        git_client: Optional initialized Git client.
        remote_name: Name of the git remote tracking the origin repository.

    Returns:
        OriginProvider: Instantiated provider for the origin repository.

    Raises:
        ValueError: If the configured provider or origin URL is unsupported.
    """
    explicit = (config.origin_provider or "").strip().lower()
    if explicit:
        if explicit in ("bitbucket", "bitbucket_cloud", "bitbucket-cloud"):
            return BitbucketCloudProvider(
                repo_url=config.origin_url,
                token=config.origin_token,
                username=config.origin_username,
                git=git_client,
                remote_name=remote_name,
            )
        if explicit in ("ado", "azure_devops", "azure-devops"):
            return AzureDevOpsProvider(
                repo_url=config.origin_url,
                pat=config.origin_token,
                git=git_client,
                remote_name=remote_name,
            )
        raise ValueError(f"Unsupported origin provider: '{config.origin_provider}'")

    url_lower = config.origin_url.lower()
    if "bitbucket.org" in url_lower:
        return BitbucketCloudProvider(
            repo_url=config.origin_url,
            token=config.origin_token,
            username=config.origin_username,
            git=git_client,
            remote_name=remote_name,
        )
    if "dev.azure.com" in url_lower or "visualstudio.com" in url_lower:
        return AzureDevOpsProvider(
            repo_url=config.origin_url,
            pat=config.origin_token,
            git=git_client,
            remote_name=remote_name,
        )

    raise ValueError(
        f"Unable to auto-detect origin provider from URL '{config.origin_url}'. "
        "Supported hosts: dev.azure.com, visualstudio.com, bitbucket.org, "
        "or set ORIGIN_PROVIDER explicitly."
    )

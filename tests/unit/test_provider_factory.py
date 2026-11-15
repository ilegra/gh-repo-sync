import pytest

from src.config import SyncConfig
from src.providers.azure_devops import AzureDevOpsProvider
from src.providers.bitbucket_cloud import BitbucketCloudProvider
from src.providers.factory import get_origin_provider


def _make_config(
    origin_url: str,
    origin_provider: str | None = None,
    origin_username: str | None = None,
) -> SyncConfig:
    return SyncConfig(
        ORIGIN_URL=origin_url,
        ORIGIN_TOKEN="secret-origin-token",
        ORIGIN_PROVIDER=origin_provider,
        ORIGIN_USERNAME=origin_username,
        DESTINATION_URL="https://github.com/org/repo.git",
        DESTINATION_TOKEN="secret-gh-token",
    )


@pytest.mark.parametrize(
    "origin_url,expected_cls",
    [
        ("https://dev.azure.com/org/proj/_git/repo", AzureDevOpsProvider),
        ("https://org.visualstudio.com/proj/_git/repo", AzureDevOpsProvider),
        ("https://bitbucket.org/workspace/repo", BitbucketCloudProvider),
        ("https://user@bitbucket.org/workspace/repo.git", BitbucketCloudProvider),
        ("git@bitbucket.org:workspace/repo.git", BitbucketCloudProvider),
    ],
)
def test_factory_auto_detects_provider(
    origin_url: str,
    expected_cls: type,
) -> None:
    config = _make_config(origin_url)
    provider = get_origin_provider(config)
    assert isinstance(provider, expected_cls)


@pytest.mark.parametrize(
    "override,expected_cls",
    [
        ("bitbucket", BitbucketCloudProvider),
        ("bitbucket_cloud", BitbucketCloudProvider),
        ("bitbucket-cloud", BitbucketCloudProvider),
        ("BITBUCKET", BitbucketCloudProvider),
        ("ado", AzureDevOpsProvider),
        ("azure_devops", AzureDevOpsProvider),
        ("azure-devops", AzureDevOpsProvider),
    ],
)
def test_factory_explicit_provider_override(
    override: str,
    expected_cls: type,
) -> None:
    config = _make_config(
        origin_url="https://git.internal.example.com/team/repo.git",
        origin_provider=override,
        origin_username="bb-user",
    )
    provider = get_origin_provider(config)
    assert isinstance(provider, expected_cls)
    if isinstance(provider, BitbucketCloudProvider):
        assert provider.username == "bb-user"


def test_factory_raises_on_unknown_explicit_provider() -> None:
    config = _make_config(
        origin_url="https://bitbucket.org/workspace/repo",
        origin_provider="gitlab",
    )
    with pytest.raises(ValueError, match="Unsupported origin provider"):
        get_origin_provider(config)


def test_factory_raises_on_unknown_origin_url() -> None:
    config = _make_config(
        origin_url="https://gitlab.com/group/repo.git",
    )
    with pytest.raises(ValueError, match="Unable to auto-detect origin provider"):
        get_origin_provider(config)

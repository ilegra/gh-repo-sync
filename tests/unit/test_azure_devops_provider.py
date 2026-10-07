import responses

from src.providers.azure_devops import AzureDevOpsProvider


def test_ado_authenticated_url_and_repo_name() -> None:
    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
    )
    auth_url = provider.get_authenticated_url()
    assert (
        auth_url
        == "https://anything:my-pat-secret@dev.azure.com/my-org/my-project/_git/my-repo"
    )
    assert provider.get_repo_name() == "my-repo"


@responses.activate
def test_ado_is_repo_disabled_true() -> None:
    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
    )
    api_url = "https://dev.azure.com/my-org/my-project/_apis/git/repositories/my-repo?api-version=7.1"
    responses.add(
        responses.GET,
        api_url,
        json={"id": "123", "name": "my-repo", "isDisabled": True},
        status=200,
    )

    assert provider.is_repo_disabled() is True


@responses.activate
def test_ado_is_repo_disabled_false() -> None:
    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
    )
    api_url = "https://dev.azure.com/my-org/my-project/_apis/git/repositories/my-repo?api-version=7.1"
    responses.add(
        responses.GET,
        api_url,
        json={"id": "123", "name": "my-repo", "isDisabled": False},
        status=200,
    )

    assert provider.is_repo_disabled() is False


@responses.activate
def test_ado_api_retries_and_failure() -> None:
    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
    )
    api_url = "https://dev.azure.com/my-org/my-project/_apis/git/repositories/my-repo?api-version=7.1"
    # Return 500 error
    responses.add(
        responses.GET,
        api_url,
        status=500,
    )

    # Should gracefully catch failure and return False
    assert provider.is_repo_disabled() is False

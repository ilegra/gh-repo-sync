import responses
from pytest_mock import MockerFixture

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


def test_ado_get_remote_ref() -> None:
    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
        remote_name="custom_origin",
    )
    assert provider.get_remote_ref("main") == "refs/remotes/custom_origin/main"
    assert (
        provider.get_remote_ref("feature/foo")
        == "refs/remotes/custom_origin/feature/foo"
    )


def test_ado_get_default_branch_name_with_symbolic_ref(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_sym_res = mocker.MagicMock(success=True, stdout="origin_remote/main")
    mock_git.symbolic_ref.return_value = mock_sym_res

    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
        git=mock_git,
        remote_name="origin_remote",
    )
    name = provider._get_default_branch_name()
    assert name == "main"


def test_ado_get_default_branch_name_fallback(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    mock_git.symbolic_ref.return_value = mocker.MagicMock(success=False, stdout="")

    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
        git=mock_git,
    )
    name = provider._get_default_branch_name()
    assert name == "main"


def test_ado_get_branches_success(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    # Mock remote check
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="origin_remote\n")
    # Mock fetch
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    # Mock symbolic ref for default branch
    mock_git.symbolic_ref.return_value = mocker.MagicMock(
        success=True, stdout="origin_remote/main"
    )
    # Mock for_each_ref
    mock_git.for_each_ref.return_value = [
        "refs/remotes/origin_remote/HEAD",
        "refs/remotes/origin_remote/main",
        "refs/remotes/origin_remote/feature/login",
        "refs/remotes/origin_remote/-bad-branch",
    ]
    mock_git.check_ref_format.return_value = True

    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
        git=mock_git,
        remote_name="origin_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 2
    assert branches[0].name == "main"
    assert branches[0].remote_ref == "refs/remotes/origin_remote/main"
    assert branches[0].is_default is True
    assert branches[1].name == "feature/login"
    assert branches[1].remote_ref == "refs/remotes/origin_remote/feature/login"
    assert branches[1].is_default is False
    mock_git.fetch.assert_called_once_with("origin_remote", prune=True)


def test_ado_get_branches_adds_remote_if_missing(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="other_remote\n")
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.for_each_ref.return_value = ["refs/remotes/origin_remote/main"]
    mock_git.check_ref_format.return_value = True

    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
        git=mock_git,
        remote_name="origin_remote",
    )
    branches = provider.get_branches()

    mock_git.remote_add.assert_called_once_with(
        "origin_remote", provider.get_authenticated_url()
    )
    assert len(branches) == 1
    assert branches[0].name == "main"


def test_ado_get_branches_handles_disabled_repo(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="origin_remote\n")
    mock_git.fetch.return_value = mocker.MagicMock(
        success=False,
        exit_code=1,
        stderr="TF401019: The Git repository with name or ID is disabled.",
    )

    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
        git=mock_git,
        remote_name="origin_remote",
    )
    branches = provider.get_branches()
    assert branches == []


def test_ado_get_branches_requires_git() -> None:
    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
        git=None,
    )
    import pytest

    with pytest.raises(RuntimeError, match="Git client is not initialized"):
        provider.get_branches()


def test_ado_get_branches_defines_custom_default_branch(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="origin_remote\n")
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.symbolic_ref.return_value = mocker.MagicMock(
        success=True, stdout="origin_remote/develop"
    )
    mock_git.for_each_ref.return_value = [
        "refs/remotes/origin_remote/HEAD",
        "refs/remotes/origin_remote/main",
        "refs/remotes/origin_remote/develop",
        "refs/remotes/origin_remote/feature/foo",
    ]
    mock_git.check_ref_format.return_value = True

    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
        git=mock_git,
        remote_name="origin_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 3
    branch_map = {b.name: b for b in branches}
    assert branch_map["develop"].is_default is True
    assert branch_map["main"].is_default is False
    assert branch_map["feature/foo"].is_default is False


def test_ado_get_branches_defines_default_branch_fallback_to_master(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="origin_remote\n")
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.symbolic_ref.return_value = mocker.MagicMock(success=False, stdout="")
    mock_git.for_each_ref.return_value = [
        "refs/remotes/origin_remote/HEAD",
        "refs/remotes/origin_remote/master",
        "refs/remotes/origin_remote/feature/foo",
    ]
    mock_git.check_ref_format.return_value = True

    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
        git=mock_git,
        remote_name="origin_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 2
    branch_map = {b.name: b for b in branches}
    assert branch_map["master"].is_default is True
    assert branch_map["feature/foo"].is_default is False


def test_ado_get_branches_defines_default_branch_fallback_to_first_branch(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="origin_remote\n")
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.symbolic_ref.return_value = mocker.MagicMock(success=False, stdout="")
    mock_git.for_each_ref.return_value = [
        "refs/remotes/origin_remote/HEAD",
        "refs/remotes/origin_remote/release/v1",
        "refs/remotes/origin_remote/feature/foo",
    ]
    mock_git.check_ref_format.return_value = True

    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
        git=mock_git,
        remote_name="origin_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 2
    assert branches[0].name == "release/v1"
    assert branches[0].is_default is True
    assert branches[1].name == "feature/foo"
    assert branches[1].is_default is False


def test_ado_get_default_branch_name_without_git() -> None:
    provider = AzureDevOpsProvider(
        repo_url="https://dev.azure.com/my-org/my-project/_git/my-repo",
        pat="my-pat-secret",
        git=None,
    )
    assert provider._get_default_branch_name() == "main"

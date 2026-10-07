import pytest
from pytest_mock import MockerFixture

from src.providers.github import GitHubProvider


def test_github_authenticated_url_and_repo_name() -> None:
    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo.git",
        token="secret-token",
        git=None,  # type: ignore[arg-type]
    )
    assert (
        provider.get_authenticated_url()
        == "https://x-access-token:secret-token@github.com/my-org/my-repo.git"
    )
    assert provider.get_repo_name() == "my-repo"


def test_github_get_remote_ref() -> None:
    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo",
        token="token",
        git=None,  # type: ignore[arg-type]
        remote_name="custom_dest",
    )
    assert provider.get_remote_ref("main") == "refs/remotes/custom_dest/main"
    assert (
        provider.get_remote_ref("feature/test")
        == "refs/remotes/custom_dest/feature/test"
    )


def test_github_get_default_branch_name_with_symbolic_ref(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_git.symbolic_ref.return_value = mocker.MagicMock(
        success=True, stdout="destination_remote/main"
    )

    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo",
        token="token",
        git=mock_git,
        remote_name="destination_remote",
    )
    name = provider._get_default_branch_name()
    assert name == "main"


def test_github_get_default_branch_name_fallback(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    mock_git.symbolic_ref.return_value = mocker.MagicMock(success=False, stdout="")

    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo",
        token="token",
        git=mock_git,
        remote_name="destination_remote",
    )
    name = provider._get_default_branch_name()
    assert name == "main"


def test_github_get_branches_success(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(
        success=True, stdout="destination_remote\n"
    )
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.symbolic_ref.return_value = mocker.MagicMock(
        success=True, stdout="destination_remote/main"
    )
    mock_git.for_each_ref.return_value = [
        "refs/remotes/destination_remote/HEAD",
        "refs/remotes/destination_remote/main",
        "refs/remotes/destination_remote/develop",
        "refs/remotes/destination_remote/..bad-branch",
    ]
    mock_git.check_ref_format.return_value = True

    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo",
        token="token",
        git=mock_git,
        remote_name="destination_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 2
    assert branches[0].name == "main"
    assert branches[0].remote_ref == "refs/remotes/destination_remote/main"
    assert branches[0].is_default is True
    assert branches[1].name == "develop"
    assert branches[1].remote_ref == "refs/remotes/destination_remote/develop"
    assert branches[1].is_default is False
    mock_git.fetch.assert_called_once_with("destination_remote", prune=True)


def test_github_get_branches_renames_origin_remote(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    # 'origin' exists from git clone
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="origin\n")
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.for_each_ref.return_value = ["refs/remotes/destination_remote/main"]
    mock_git.check_ref_format.return_value = True

    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo",
        token="token",
        git=mock_git,
        remote_name="destination_remote",
    )
    branches = provider.get_branches()

    mock_git.run.assert_any_call(
        "remote", "rename", "origin", "destination_remote", check=True
    )
    assert len(branches) == 1
    assert branches[0].name == "main"


def test_github_get_branches_adds_remote_if_missing(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(
        success=True, stdout="something_else\n"
    )
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.for_each_ref.return_value = ["refs/remotes/destination_remote/main"]
    mock_git.check_ref_format.return_value = True

    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo",
        token="token",
        git=mock_git,
        remote_name="destination_remote",
    )
    branches = provider.get_branches()

    mock_git.remote_add.assert_called_once_with(
        "destination_remote", provider.get_authenticated_url()
    )
    assert len(branches) == 1
    assert branches[0].name == "main"


def test_github_get_branches_requires_git() -> None:
    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo",
        token="token",
        git=None,  # type: ignore[arg-type]
    )
    with pytest.raises(RuntimeError, match="Git client is not initialized"):
        provider.get_branches()


def test_github_get_branches_defines_custom_default_branch(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(
        success=True, stdout="destination_remote\n"
    )
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.symbolic_ref.return_value = mocker.MagicMock(
        success=True, stdout="destination_remote/production"
    )
    mock_git.for_each_ref.return_value = [
        "refs/remotes/destination_remote/HEAD",
        "refs/remotes/destination_remote/main",
        "refs/remotes/destination_remote/production",
        "refs/remotes/destination_remote/staging",
    ]
    mock_git.check_ref_format.return_value = True

    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo",
        token="token",
        git=mock_git,
        remote_name="destination_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 3
    branch_map = {b.name: b for b in branches}
    assert branch_map["production"].is_default is True
    assert branch_map["main"].is_default is False
    assert branch_map["staging"].is_default is False


def test_github_get_branches_defines_default_branch_fallback_to_master(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(
        success=True, stdout="destination_remote\n"
    )
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.symbolic_ref.return_value = mocker.MagicMock(success=False, stdout="")
    mock_git.for_each_ref.return_value = [
        "refs/remotes/destination_remote/HEAD",
        "refs/remotes/destination_remote/master",
        "refs/remotes/destination_remote/feature/bar",
    ]
    mock_git.check_ref_format.return_value = True

    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo",
        token="token",
        git=mock_git,
        remote_name="destination_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 2
    branch_map = {b.name: b for b in branches}
    assert branch_map["master"].is_default is True
    assert branch_map["feature/bar"].is_default is False


def test_github_get_branches_defines_default_branch_fallback_to_first_branch(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(
        success=True, stdout="destination_remote\n"
    )
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.symbolic_ref.return_value = mocker.MagicMock(success=False, stdout="")
    mock_git.for_each_ref.return_value = [
        "refs/remotes/destination_remote/HEAD",
        "refs/remotes/destination_remote/release/v2",
        "refs/remotes/destination_remote/hotfix/1",
    ]
    mock_git.check_ref_format.return_value = True

    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo",
        token="token",
        git=mock_git,
        remote_name="destination_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 2
    assert branches[0].name == "release/v2"
    assert branches[0].is_default is True
    assert branches[1].name == "hotfix/1"
    assert branches[1].is_default is False


def test_github_get_default_branch_name_without_git() -> None:
    provider = GitHubProvider(
        repo_url="https://github.com/my-org/my-repo",
        token="token",
        git=None,  # type: ignore[arg-type]
    )
    assert provider._get_default_branch_name() == "main"

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.config import SyncConfig, SyncResult
from src.main import main


@pytest.fixture
def mock_valid_config() -> SyncConfig:
    return SyncConfig(
        origin_url="https://dev.azure.com/org/project/_git/repo",
        origin_token="dummy-ado-token",
        destination_url="https://github.com/org/repo.git",
        destination_token="dummy-gh-token",
    )


def test_main_returns_1_on_config_exception() -> None:
    with patch("src.main.SyncConfig", side_effect=ValueError("Invalid config")):
        ret = main()
        assert ret == 1


def test_main_returns_1_on_sync_manager_exception(
    mock_valid_config: SyncConfig,
) -> None:
    created_temp_dirs: list[str] = []
    original_mkdtemp = tempfile.mkdtemp

    def tracked_mkdtemp(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
    ) -> str:
        d = original_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
        created_temp_dirs.append(d)
        return d

    with (
        patch("src.main.SyncConfig", return_value=mock_valid_config),
        patch("src.main.Git"),
        patch("src.main.AzureDevOpsProvider"),
        patch("src.main.GitHubProvider"),
        patch("src.main.tempfile.mkdtemp", side_effect=tracked_mkdtemp),
        patch("src.main.SyncManager.execute", side_effect=RuntimeError("Sync error")),
        patch("src.main.GithubActionOutputAdapter") as mock_adapter_cls,
    ):
        ret = main()
        assert ret == 1
        mock_adapter_cls.assert_not_called()
        assert len(created_temp_dirs) == 1
        assert not os.path.exists(created_temp_dirs[0])


def test_main_returns_1_on_adapter_exception(mock_valid_config: SyncConfig) -> None:
    dummy_result = SyncResult(
        repo_name="repo",
        origin_repo="https://dev.azure.com/org/project/_git/repo",
        destination_repo="https://github.com/org/repo.git",
    )
    mock_adapter = MagicMock()
    mock_adapter.publish.side_effect = RuntimeError("Adapter failed")

    with (
        patch("src.main.SyncConfig", return_value=mock_valid_config),
        patch("src.main.Git"),
        patch("src.main.AzureDevOpsProvider"),
        patch("src.main.GitHubProvider"),
        patch("src.main.SyncManager.execute", return_value=dummy_result),
        patch("src.main.GithubActionOutputAdapter", return_value=mock_adapter),
    ):
        ret = main()
        assert ret == 1
        mock_adapter.publish.assert_called_once_with(dummy_result)


def test_main_returns_1_when_result_has_errors(mock_valid_config: SyncConfig) -> None:
    dummy_result = SyncResult(
        repo_name="repo",
        origin_repo="https://dev.azure.com/org/project/_git/repo",
        destination_repo="https://github.com/org/repo.git",
        errors=["Push failed for branch `feature/x`"],
    )
    mock_adapter = MagicMock()

    with (
        patch("src.main.SyncConfig", return_value=mock_valid_config),
        patch("src.main.Git"),
        patch("src.main.AzureDevOpsProvider"),
        patch("src.main.GitHubProvider"),
        patch("src.main.SyncManager.execute", return_value=dummy_result),
        patch("src.main.GithubActionOutputAdapter", return_value=mock_adapter),
    ):
        ret = main()
        assert ret == 1
        mock_adapter.publish.assert_called_once_with(dummy_result)


def test_main_returns_0_on_success(mock_valid_config: SyncConfig) -> None:
    dummy_result = SyncResult(
        repo_name="repo",
        origin_repo="https://dev.azure.com/org/project/_git/repo",
        destination_repo="https://github.com/org/repo.git",
        synced_branches=["main"],
        removed_branches=["old"],
        synced_tags=["v1.0"],
        errors=[],
    )
    mock_adapter = MagicMock()

    with (
        patch("src.main.SyncConfig", return_value=mock_valid_config),
        patch("src.main.Git"),
        patch("src.main.AzureDevOpsProvider"),
        patch("src.main.GitHubProvider"),
        patch("src.main.SyncManager.execute", return_value=dummy_result),
        patch("src.main.GithubActionOutputAdapter", return_value=mock_adapter),
    ):
        ret = main()
        assert ret == 0
        mock_adapter.publish.assert_called_once_with(dummy_result)


def test_main_returns_0_when_already_disabled(mock_valid_config: SyncConfig) -> None:
    dummy_result = SyncResult(
        repo_name="repo",
        origin_repo="https://dev.azure.com/org/project/_git/repo",
        destination_repo="https://github.com/org/repo.git",
        already_disabled=True,
        errors=[],
    )
    mock_adapter = MagicMock()

    with (
        patch("src.main.SyncConfig", return_value=mock_valid_config),
        patch("src.main.Git"),
        patch("src.main.AzureDevOpsProvider"),
        patch("src.main.GitHubProvider"),
        patch("src.main.SyncManager.execute", return_value=dummy_result),
        patch("src.main.GithubActionOutputAdapter", return_value=mock_adapter),
    ):
        ret = main()
        assert ret == 0
        mock_adapter.publish.assert_called_once_with(dummy_result)

from pathlib import Path

import pytest

from src.config import SyncConfig, SyncResult


def test_config_parsing_and_defaults() -> None:
    config = SyncConfig(
        ORIGIN_URL="https://dev.azure.com/org/proj/_git/repo",
        ORIGIN_TOKEN="secret-origin-pat",
        DESTINATION_URL="https://github.com/org/repo.git",
        DESTINATION_TOKEN="secret-gh-token",
        ORIGIN_EXCLUSIVE_PATHS="charts, deploy/.env",
        DESTINATION_EXCLUSIVE_PATHS="docs, .github/actions",
        BRANCH_MAPPING="master:main, develop:dev",
    )

    # Defaults + custom
    assert ".pipeline" in config.origin_exclusive_paths
    assert "azure-pipelines*.yml" in config.origin_exclusive_paths
    assert "charts" in config.origin_exclusive_paths
    assert "deploy/.env" in config.origin_exclusive_paths

    assert ".github" in config.destination_exclusive_paths
    assert "docs" in config.destination_exclusive_paths
    assert ".github/actions" in config.destination_exclusive_paths

    # Branch mapping
    assert config.branch_mapping == {"master": "main", "develop": "dev"}
    assert config.reverse_branch_mapping == {"main": "master", "dev": "develop"}


def test_config_legacy_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADO_URL", "https://dev.azure.com/org/proj/_git/repo")
    monkeypatch.setenv("ADO_PAT", "ado-token-xyz")
    monkeypatch.setenv("GH_URL", "https://github.com/org/repo")
    monkeypatch.setenv("GH_TOKEN", "gh-token-123")
    monkeypatch.setenv("ADO_EXCLUSIVE_PATHS", "custom_ado")
    monkeypatch.setenv("GH_EXCLUSIVE_PATHS", "custom_gh")

    config = SyncConfig()
    assert config.origin_url == "https://dev.azure.com/org/proj/_git/repo"
    assert config.origin_token == "ado-token-xyz"
    assert config.destination_url == "https://github.com/org/repo"
    assert config.destination_token == "gh-token-123"
    assert "custom_ado" in config.origin_exclusive_paths
    assert "custom_gh" in config.destination_exclusive_paths


def test_sync_result_serialization(tmp_path: Path) -> None:
    res_file = tmp_path / "sync.json"
    result = SyncResult(
        repo_name="my-repo",
        origin_repo="https://dev.azure.com/org/proj/_git/my-repo",
        destination_repo="https://github.com/org/my-repo",
        synced_branches=["main", "feature/1"],
        removed_branches=["old-branch"],
        errors=[],
    )
    result.write_to_file(str(res_file))
    assert res_file.exists()
    content = res_file.read_text()
    assert '"repo_name": "my-repo"' in content
    assert '"synced_branches": [\n    "main",\n    "feature/1"\n  ]' in content


def test_config_committer_defaults_and_properties() -> None:
    config = SyncConfig(
        ORIGIN_URL="https://dev.azure.com/org/proj/_git/repo",
        ORIGIN_TOKEN="secret-origin-pat",
        DESTINATION_URL="https://github.com/org/repo.git",
        DESTINATION_TOKEN="secret-gh-token",
    )
    assert config.bot_name == "github-actions[bot]"
    assert config.bot_email == "github-actions[bot]@users.noreply.github.com"
    assert config.committer_name == "github-actions[bot]"
    assert config.committer_email == "github-actions[bot]@users.noreply.github.com"


def test_config_committer_custom_parameterization() -> None:
    config = SyncConfig(
        ORIGIN_URL="https://dev.azure.com/org/proj/_git/repo",
        ORIGIN_TOKEN="secret-origin-pat",
        DESTINATION_URL="https://github.com/org/repo.git",
        DESTINATION_TOKEN="secret-gh-token",
        COMMITTER_NAME="Custom CI Bot",
        COMMITTER_EMAIL="custom-ci@example.com",
    )
    assert config.bot_name == "Custom CI Bot"
    assert config.bot_email == "custom-ci@example.com"
    assert config.committer_name == "Custom CI Bot"
    assert config.committer_email == "custom-ci@example.com"


def test_config_committer_empty_or_whitespace_falls_back() -> None:
    config = SyncConfig(
        ORIGIN_URL="https://dev.azure.com/org/proj/_git/repo",
        ORIGIN_TOKEN="secret-origin-pat",
        DESTINATION_URL="https://github.com/org/repo.git",
        DESTINATION_TOKEN="secret-gh-token",
        COMMITTER_NAME="   ",
        COMMITTER_EMAIL="",
    )
    assert config.bot_name == "github-actions[bot]"
    assert config.bot_email == "github-actions[bot]@users.noreply.github.com"
    assert config.committer_name == "github-actions[bot]"
    assert config.committer_email == "github-actions[bot]@users.noreply.github.com"


def test_config_committer_env_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORIGIN_URL", "https://dev.azure.com/org/proj/_git/repo")
    monkeypatch.setenv("ORIGIN_TOKEN", "pat")
    monkeypatch.setenv("DESTINATION_URL", "https://github.com/org/repo.git")
    monkeypatch.setenv("DESTINATION_TOKEN", "token")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Git Env Committer")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "committer@git.env")

    config = SyncConfig()
    assert config.bot_name == "Git Env Committer"
    assert config.bot_email == "committer@git.env"
    assert config.committer_name == "Git Env Committer"
    assert config.committer_email == "committer@git.env"

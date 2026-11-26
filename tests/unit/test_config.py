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
        evaluated_branches=["main", "feature/1"],
        updated_branches=["feature/1"],
        removed_branches=["old-branch"],
        errors=[],
    )
    result.write_to_file(str(res_file))
    assert res_file.exists()
    content = res_file.read_text()
    assert '"repo_name": "my-repo"' in content
    assert '"evaluated_branches": [\n    "main",\n    "feature/1"\n  ]' in content
    assert '"updated_branches": [\n    "feature/1"\n  ]' in content


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


def test_config_bitbucket_aliases_and_default_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORIGIN_URL", "https://bitbucket.org/workspace/repo")
    monkeypatch.setenv("BITBUCKET_TOKEN", "bb-secret")
    monkeypatch.setenv("BITBUCKET_USERNAME", "bb-user")
    monkeypatch.setenv("ORIGIN_TYPE", "bitbucket")
    monkeypatch.setenv("DESTINATION_URL", "https://github.com/org/repo.git")
    monkeypatch.setenv("DESTINATION_TOKEN", "gh-secret")

    config = SyncConfig()
    assert config.origin_token == "bb-secret"
    assert config.origin_username == "bb-user"
    assert config.origin_provider == "bitbucket"
    assert "bitbucket-pipelines.yml" in config.origin_exclusive_paths


class TestPrUserMappingConfig:
    @staticmethod
    def _make_config(pr_user_mapping: str | None = None) -> SyncConfig:
        if pr_user_mapping is None:
            return SyncConfig(
                ORIGIN_URL="https://bitbucket.org/workspace/repo",
                ORIGIN_TOKEN="bb-secret",
                DESTINATION_URL="https://github.com/org/repo.git",
                DESTINATION_TOKEN="gh-secret",
            )
        return SyncConfig(
            ORIGIN_URL="https://bitbucket.org/workspace/repo",
            ORIGIN_TOKEN="bb-secret",
            DESTINATION_URL="https://github.com/org/repo.git",
            DESTINATION_TOKEN="gh-secret",
            PR_USER_MAPPING=pr_user_mapping,
        )

    def test_given_empty_pr_user_mapping_when_reading_property_then_returns_empty_dict(
        self,
    ) -> None:
        config = self._make_config()
        assert config.pr_user_mapping == {}

    def test_given_json_pr_user_mapping_when_reading_property_then_parses_names_with_commas_and_strips_at_prefix(
        self,
    ) -> None:
        config = self._make_config('{"Doe, Jane": "@jdoe", "Bob Smith": "bsmith"}')
        assert config.pr_user_mapping == {"Doe, Jane": "jdoe", "Bob Smith": "bsmith"}

    def test_given_comma_separated_pr_user_mapping_when_reading_property_then_parses_pairs_and_strips_whitespace(
        self,
    ) -> None:
        config = self._make_config(
            " Jane Doe : @jdoe , Bob Smith : bsmith , invalid_entry "
        )
        assert config.pr_user_mapping == {"Jane Doe": "jdoe", "Bob Smith": "bsmith"}

    def test_given_malformed_json_pr_user_mapping_when_initializing_config_then_raises_validation_error(
        self,
    ) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Invalid JSON in PR_USER_MAPPING"):
            self._make_config('{"Jane Doe": }')

    def test_given_non_object_json_pr_user_mapping_when_initializing_config_then_raises_validation_error(
        self,
    ) -> None:
        from pydantic import ValidationError

        with pytest.raises(
            ValidationError,
            match="PR_USER_MAPPING JSON must be an object mapping strings to strings",
        ):
            self._make_config('{"Jane Doe": 123}')

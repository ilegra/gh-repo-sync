from typing import Any
from unittest.mock import MagicMock, patch

from src.config import SyncConfig
from src.core.sync import (
    SyncManager,
    is_exclusive_path,
    parse_author,
    validate_branch_name,
)
from src.git.client import GitResult
from src.providers.base import Branch


def test_validate_branch_name() -> None:
    # Valid branches
    assert validate_branch_name("main") is True
    assert validate_branch_name("feature/ABC-123") is True
    assert validate_branch_name("bugfix.name") is True
    assert validate_branch_name("releases/v1.0.0") is True

    # Invalid branches
    assert validate_branch_name("") is False
    assert validate_branch_name("-starts-with-dash") is False
    assert validate_branch_name("has spaces") is False
    assert validate_branch_name("has~tilde") is False
    assert validate_branch_name("has^caret") is False
    assert validate_branch_name("has:colon") is False
    assert validate_branch_name("has?question") is False
    assert validate_branch_name("has*star") is False
    assert validate_branch_name("has[bracket") is False
    assert validate_branch_name("has..dotdot") is False
    assert validate_branch_name("/starts-with-slash") is False
    assert validate_branch_name("ends-with-slash/") is False


def test_is_exclusive_path() -> None:
    exclusive = [".github", ".pipeline", "azure-pipelines*.yml", "charts"]

    # Exact matches and subpath matches
    assert is_exclusive_path(".github", exclusive) is True
    assert is_exclusive_path(".github/workflows/ci.yml", exclusive) is True
    assert is_exclusive_path(".pipeline/build.sh", exclusive) is True
    assert is_exclusive_path("charts/values.yaml", exclusive) is True
    assert is_exclusive_path("sub/folder/charts/Chart.yaml", exclusive) is True

    # Glob matches
    assert is_exclusive_path("azure-pipelines.yml", exclusive) is True
    assert is_exclusive_path("azure-pipelines-ci.yml", exclusive) is True
    assert is_exclusive_path("ci/azure-pipelines-prod.yml", exclusive) is True

    # Non-matches (should NOT match partial or unrelated)
    assert is_exclusive_path(".github2/file", exclusive) is False
    assert is_exclusive_path("my_charts_folder", exclusive) is False
    assert is_exclusive_path("azure-pipelines.txt", exclusive) is False
    assert is_exclusive_path("src/index.js", exclusive) is False


def test_parse_author() -> None:
    bot_name = "test-bot"
    bot_email = "bot@example.com"

    # Valid author
    name, email = parse_author("Alice Doe\talice@example.com", bot_name, bot_email)
    assert name == "Alice Doe"
    assert email == "alice@example.com"

    # Missing email separator
    name, email = parse_author("Alice Doe", bot_name, bot_email)
    assert name == bot_name
    assert email == bot_email

    # Email missing @
    name, email = parse_author("Alice Doe\tnot-an-email", bot_name, bot_email)
    assert name == bot_name
    assert email == bot_email

    # Empty string
    name, email = parse_author("", bot_name, bot_email)
    assert name == bot_name
    assert email == bot_email


def test_branch_model_is_default() -> None:
    branch = Branch(name="feature/test", remote_ref="refs/remotes/origin/feature/test")
    assert branch.is_default is False

    default_branch = Branch(
        name="main",
        remote_ref="refs/remotes/origin/main",
        is_default=True,
    )
    assert default_branch.is_default is True


def test_sync_manager_execute() -> None:
    config = SyncConfig(
        ORIGIN_URL="origin",
        ORIGIN_TOKEN="token1",
        DESTINATION_URL="dest",
        DESTINATION_TOKEN="token2",
        BOT_NAME="bot",
        BOT_EMAIL="bot@example.com",
    )

    mock_origin = MagicMock()
    mock_origin.is_repo_disabled.return_value = False
    mock_origin.get_branches.return_value = [
        Branch(name="main", remote_ref="origin/main", is_default=True),
        Branch(name="feature/new", remote_ref="origin/feature/new", is_default=False),
    ]
    mock_origin.remote_name = "origin"
    mock_origin.get_remote_ref = lambda b: f"origin/{b}"

    mock_dest = MagicMock()
    mock_dest.get_repo_name.return_value = "test-repo"
    mock_dest.get_authenticated_url.return_value = "auth-dest"
    mock_dest.get_branches.return_value = [
        Branch(name="main", remote_ref="dest/main", is_default=True),
        Branch(name="feature/old", remote_ref="dest/feature/old", is_default=False),
    ]
    mock_dest.remote_name = "dest"
    mock_dest.get_remote_ref = lambda b: f"dest/{b}"

    mock_git = MagicMock()

    def ref_exists_side_effect(ref: str) -> bool:
        return ref in [
            "origin/main",
            "origin/feature/new",
            "dest/main",
            "dest/feature/old",
        ]

    mock_git.ref_exists.side_effect = ref_exists_side_effect

    def merge_base_side_effect(ref1: str, ref2: str) -> bool:
        # 'main' is fully synced
        if ref1 == "origin/main" and ref2 == "dest/main":
            return True
        return False

    mock_git.merge_base_is_ancestor.side_effect = merge_base_side_effect

    def push_side_effect(remote: str, **kwargs: Any) -> GitResult:
        if kwargs.get("tags"):
            return GitResult(0, "", " * [new tag]         v1.0 -> v1.0\n", [])
        return GitResult(0, "", "", [])

    mock_git.push.side_effect = push_side_effect
    mock_git.status_porcelain.return_value = []
    mock_git.cwd = "/tmp/fake-repo"

    with (
        patch("src.core.sync.Git") as MockGit,
        patch.object(SyncManager, "_has_exclusive_path_changes", return_value=False),
        patch.object(SyncManager, "_purge_origin_exclusive_assets"),
        patch.object(SyncManager, "_resolve_seed_reference", return_value="dest/main"),
    ):
        MockGit.return_value = MagicMock()
        manager = SyncManager(config, mock_origin, mock_dest, mock_git)
        result = manager.execute()

    assert result.repo_name == "test-repo"
    assert "main" in result.evaluated_branches
    assert "feature/new" in result.evaluated_branches
    assert "main" not in result.updated_branches  # fully synced
    assert "feature/new" in result.updated_branches  # newly pushed
    assert "feature/old" in result.removed_branches  # pruned
    assert "v1.0" in result.synced_tags  # mock parsed from stderr

    # Verify branch state was method-scoped and not retained on the instance
    assert not hasattr(manager, "origin_branches")
    assert not hasattr(manager, "destination_branches")
    assert not hasattr(manager, "default_branch")


def test_determine_default_branch() -> None:
    dest_branches = [
        Branch(name="main", remote_ref="dest/main", is_default=True),
        Branch(name="dev", remote_ref="dest/dev", is_default=False),
    ]
    origin_branches = [
        Branch(name="master", remote_ref="origin/master", is_default=True),
    ]
    assert (
        SyncManager._determine_default_branch(dest_branches, origin_branches) == "main"
    )

    dest_branches_no_default = [
        Branch(name="dev", remote_ref="dest/dev", is_default=False),
    ]
    assert (
        SyncManager._determine_default_branch(dest_branches_no_default, origin_branches)
        == "master"
    )

    origin_branches_no_default = [
        Branch(name="feat", remote_ref="origin/feat", is_default=False),
    ]
    assert (
        SyncManager._determine_default_branch(
            dest_branches_no_default, origin_branches_no_default
        )
        == "main"
    )


def test_sync_manager_configures_custom_committer() -> None:
    config = SyncConfig(
        ORIGIN_URL="https://dev.azure.com/org/proj/_git/repo",
        ORIGIN_TOKEN="pat",
        DESTINATION_URL="https://github.com/org/repo.git",
        DESTINATION_TOKEN="token",
        COMMITTER_NAME="Custom Committer Bot",
        COMMITTER_EMAIL="custom-committer@example.com",
    )
    mock_origin = MagicMock()
    mock_origin.get_branches.return_value = [
        Branch(name="main", remote_ref="origin/main")
    ]
    mock_origin.is_repo_disabled.return_value = False

    mock_dest = MagicMock()
    mock_dest.get_authenticated_url.return_value = "https://auth-url"
    mock_dest.get_branches.return_value = [Branch(name="main", remote_ref="dest/main")]

    mock_git = MagicMock()
    mock_git.cwd = "/tmp/repo"

    with patch("src.core.sync.Git") as mock_git_cls:
        parent_git = MagicMock()
        mock_git_cls.return_value = parent_git

        manager = SyncManager(config, mock_origin, mock_dest, mock_git)
        manager._setup_environment()

        mock_git.config.assert_any_call("user.name", "Custom Committer Bot")
        mock_git.config.assert_any_call("user.email", "custom-committer@example.com")


def test_sync_manager_configures_fallback_committer() -> None:
    config = SyncConfig(
        ORIGIN_URL="https://dev.azure.com/org/proj/_git/repo",
        ORIGIN_TOKEN="pat",
        DESTINATION_URL="https://github.com/org/repo.git",
        DESTINATION_TOKEN="token",
    )
    mock_origin = MagicMock()
    mock_origin.get_branches.return_value = [
        Branch(name="main", remote_ref="origin/main")
    ]
    mock_origin.is_repo_disabled.return_value = False

    mock_dest = MagicMock()
    mock_dest.get_authenticated_url.return_value = "https://auth-url"
    mock_dest.get_branches.return_value = [Branch(name="main", remote_ref="dest/main")]

    mock_git = MagicMock()
    mock_git.cwd = "/tmp/repo"

    with patch("src.core.sync.Git") as mock_git_cls:
        parent_git = MagicMock()
        mock_git_cls.return_value = parent_git

        manager = SyncManager(config, mock_origin, mock_dest, mock_git)
        manager._setup_environment()

        mock_git.config.assert_any_call("user.name", "github-actions[bot]")
        mock_git.config.assert_any_call(
            "user.email", "github-actions[bot]@users.noreply.github.com"
        )


def test_sync_manager_author_resolution_fallback() -> None:
    config = SyncConfig(
        ORIGIN_URL="https://dev.azure.com/org/proj/_git/repo",
        ORIGIN_TOKEN="pat",
        DESTINATION_URL="https://github.com/org/repo.git",
        DESTINATION_TOKEN="token",
        COMMITTER_NAME="Fallback Committer",
        COMMITTER_EMAIL="fallback@example.com",
    )
    mock_origin = MagicMock()
    mock_dest = MagicMock()
    mock_git = MagicMock()

    # Case 1: reference does not exist
    mock_git.ref_exists.return_value = False
    manager = SyncManager(config, mock_origin, mock_dest, mock_git)
    name, email = manager._resolve_origin_author("nonexistent/ref")
    assert name == "Fallback Committer"
    assert email == "fallback@example.com"

    # Case 2: reference exists but git log produces invalid/missing email
    mock_git.ref_exists.return_value = True
    mock_git.log_one.return_value = "Author Without Email\t"
    name, email = manager._resolve_origin_author("origin/main")
    assert name == "Fallback Committer"
    assert email == "fallback@example.com"


def _create_mock_sync_manager(
    origin_branches: list[Branch],
    dest_branches: list[Branch],
    merge_base_true_for: list[tuple[str, str]] | None = None,
) -> tuple[SyncManager, MagicMock]:
    config = SyncConfig(
        ORIGIN_URL="origin",
        ORIGIN_TOKEN="token1",
        DESTINATION_URL="dest",
        DESTINATION_TOKEN="token2",
    )
    mock_origin = MagicMock()
    mock_origin.is_repo_disabled.return_value = False
    mock_origin.get_branches.return_value = origin_branches
    mock_origin.remote_name = "origin"
    mock_origin.get_remote_ref = lambda b: f"origin/{b}"

    mock_dest = MagicMock()
    mock_dest.get_repo_name.return_value = "test-repo"
    mock_dest.get_authenticated_url.return_value = "auth-dest"
    mock_dest.get_branches.return_value = dest_branches
    mock_dest.remote_name = "dest"
    mock_dest.get_remote_ref = lambda b: f"dest/{b}"

    mock_git = MagicMock()
    mock_git.ref_exists.return_value = True

    if merge_base_true_for is None:
        merge_base_true_for = []

    def merge_base_side_effect(ref1: str, ref2: str) -> bool:
        return (ref1, ref2) in merge_base_true_for

    mock_git.merge_base_is_ancestor.side_effect = merge_base_side_effect
    mock_git.push.return_value = GitResult(0, "", "", [])
    mock_git.status_porcelain.return_value = []
    mock_git.cwd = "/tmp/fake-repo"

    manager = SyncManager(config, mock_origin, mock_dest, mock_git)
    return manager, mock_git


def test_sync_no_branches_to_sync() -> None:
    # 1 - when there are no branches to sync whatsoever
    manager, _ = _create_mock_sync_manager(
        origin_branches=[],
        dest_branches=[],
    )
    with (
        patch("src.core.sync.Git") as MockGit,
        patch.object(SyncManager, "_has_exclusive_path_changes", return_value=False),
        patch.object(SyncManager, "_purge_origin_exclusive_assets"),
        patch.object(SyncManager, "_resolve_seed_reference", return_value="dest/main"),
    ):
        MockGit.return_value = MagicMock()
        result = manager.execute()

    assert result.evaluated_branches == []
    assert result.updated_branches == []
    assert result.removed_branches == []


def test_sync_branches_without_updates() -> None:
    # 2 - When there branches without updates
    manager, _ = _create_mock_sync_manager(
        origin_branches=[
            Branch(name="main", remote_ref="origin/main", is_default=True)
        ],
        dest_branches=[Branch(name="main", remote_ref="dest/main", is_default=True)],
        merge_base_true_for=[("origin/main", "dest/main")],
    )
    with (
        patch("src.core.sync.Git") as MockGit,
        patch.object(SyncManager, "_has_exclusive_path_changes", return_value=False),
        patch.object(SyncManager, "_purge_origin_exclusive_assets"),
        patch.object(SyncManager, "_resolve_seed_reference", return_value="dest/main"),
    ):
        MockGit.return_value = MagicMock()
        result = manager.execute()

    assert result.evaluated_branches == ["main"]
    assert result.updated_branches == []
    assert result.removed_branches == []


def test_sync_branches_with_updates() -> None:
    # 3 - When there are branches with updates
    manager, mock_git = _create_mock_sync_manager(
        origin_branches=[
            Branch(name="main", remote_ref="origin/main", is_default=True),
            Branch(name="feat", remote_ref="origin/feat", is_default=False),
        ],
        dest_branches=[
            Branch(name="main", remote_ref="dest/main", is_default=True),
        ],
        merge_base_true_for=[
            ("origin/main", "dest/main")
        ],  # main is fully synced, feat is not
    )
    # the manager will see 'feat' is not in destination since we'll mock ref_exists
    mock_git.ref_exists.side_effect = lambda ref: (
        ref
        in [
            "origin/main",
            "origin/feat",
            "dest/main",
        ]
    )

    with (
        patch("src.core.sync.Git") as MockGit,
        patch.object(SyncManager, "_has_exclusive_path_changes", return_value=False),
        patch.object(SyncManager, "_purge_origin_exclusive_assets"),
        patch.object(SyncManager, "_resolve_seed_reference", return_value="dest/main"),
    ):
        MockGit.return_value = MagicMock()
        result = manager.execute()

    assert "main" in result.evaluated_branches
    assert "feat" in result.evaluated_branches
    assert "main" not in result.updated_branches
    assert "feat" in result.updated_branches
    assert result.removed_branches == []


def test_sync_only_removed_branches() -> None:
    # 4 - no branches with updates, only removed branches
    manager, mock_git = _create_mock_sync_manager(
        origin_branches=[
            Branch(name="main", remote_ref="origin/main", is_default=True)
        ],
        dest_branches=[
            Branch(name="main", remote_ref="dest/main", is_default=True),
            Branch(name="old", remote_ref="dest/old", is_default=False),
        ],
        merge_base_true_for=[("origin/main", "dest/main")],
    )
    # mock ref_exists to say 'origin/old' doesn't exist
    mock_git.ref_exists.side_effect = lambda ref: (
        ref
        in [
            "origin/main",
            "dest/main",
            "dest/old",
        ]
    )

    with (
        patch("src.core.sync.Git") as MockGit,
        patch.object(SyncManager, "_has_exclusive_path_changes", return_value=False),
        patch.object(SyncManager, "_purge_origin_exclusive_assets"),
        patch.object(SyncManager, "_resolve_seed_reference", return_value="dest/main"),
    ):
        MockGit.return_value = MagicMock()
        result = manager.execute()

    assert result.evaluated_branches == ["main"]
    assert result.updated_branches == []
    assert result.removed_branches == ["old"]

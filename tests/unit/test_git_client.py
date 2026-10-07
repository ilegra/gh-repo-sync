from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from src.git.client import Git, GitError


def test_git_mask_text() -> None:
    client = Git("/tmp", mask_patterns=["supersecretpat", "mygithubtoken"])
    raw = "git remote add origin https://anything:supersecretpat@dev.azure.com/repo"
    masked = client.mask_text(raw)
    assert "supersecretpat" not in masked
    assert "***" in masked


def test_git_merge_command(mocker: MockerFixture) -> None:
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    client = Git("/repo")
    client.merge(
        "origin/feature",
        strategy_option="theirs",
        no_commit=True,
        allow_unrelated_histories=True,
    )

    expected = [
        "git",
        "merge",
        "-X",
        "theirs",
        "--no-commit",
        "--allow-unrelated-histories",
        "origin/feature",
    ]
    mock_run.assert_called_once_with(
        expected,
        cwd="/repo",
        capture_output=True,
        text=True,
        check=False,
    )


def test_git_commit_command(mocker: MockerFixture) -> None:
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    client = Git("/repo")
    client.commit(
        "sync changes [skip actions]",
        author="John Doe <jdoe@example.com>",
        allow_empty=True,
    )

    expected = [
        "git",
        "commit",
        "-m",
        "sync changes [skip actions]",
        "--author=John Doe <jdoe@example.com>",
        "--allow-empty",
    ]
    mock_run.assert_called_once_with(
        expected,
        cwd="/repo",
        capture_output=True,
        text=True,
        check=False,
    )


def test_git_checkout_command(mocker: MockerFixture) -> None:
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    client = Git("/repo")
    client.checkout("main", base_ref="origin/main", create=True)

    expected = ["git", "checkout", "-B", "main", "origin/main"]
    mock_run.assert_called_once_with(
        expected,
        cwd="/repo",
        capture_output=True,
        text=True,
        check=False,
    )


def test_git_checkout_theirs_path(mocker: MockerFixture) -> None:
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    client = Git("/repo")
    client.checkout("file.txt", theirs=True, paths=["file.txt"])

    expected = ["git", "checkout", "--theirs", "--", "file.txt"]
    mock_run.assert_called_once_with(
        expected,
        cwd="/repo",
        capture_output=True,
        text=True,
        check=False,
    )


def test_git_push_delete(mocker: MockerFixture) -> None:
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    client = Git("/repo")
    client.push("destination", ref="feature/old", delete=True)

    expected = ["git", "push", "destination", "--delete", "feature/old"]
    mock_run.assert_called_once_with(
        expected,
        cwd="/repo",
        capture_output=True,
        text=True,
        check=False,
    )


def test_git_raise_for_status(mocker: MockerFixture) -> None:
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="fatal error occurred"
    )

    client = Git("/repo")
    with pytest.raises(GitError) as exc_info:
        client.run("status", check=True)

    assert "fatal error occurred" in str(exc_info.value)

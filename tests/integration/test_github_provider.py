import os
import shutil
import tempfile
from collections.abc import Generator

import pytest

from src.git.client import Git
from src.providers.github import GitHubProvider


def create_local_repo(path: str) -> Git:
    os.makedirs(path, exist_ok=True)
    git = Git(path)
    git.run("init", "-b", "main", check=True)
    git.config("user.name", "Tester")
    git.config("user.email", "tester@example.com")
    return git


@pytest.fixture
def github_provider_env() -> Generator[dict[str, str | Git], None, None]:
    temp_dir = tempfile.mkdtemp(prefix="test_gh_provider_")
    repo_dir = os.path.join(temp_dir, "repo")
    git_client = create_local_repo(repo_dir)

    yield {
        "root": temp_dir,
        "repo": repo_dir,
        "git": git_client,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


def test_github_provider_commit_injects_skip_actions(
    github_provider_env: dict[str, str | Git],
) -> None:
    git_client = github_provider_env["git"]
    assert isinstance(git_client, Git)
    repo_dir = str(github_provider_env["repo"])

    provider = GitHubProvider("https://github.com/org/repo.git", "token", git_client)

    # Stage a file
    with open(os.path.join(repo_dir, "file.txt"), "w") as f:
        f.write("content")
    git_client.add(all_files=True)

    # Commit via provider
    provider.commit("feat: add file", author="Test <test@example.com>")

    # Verify commit message
    msg = git_client.log_one("HEAD", "%B")
    assert msg.strip() == "feat: add file [skip actions]"


def test_github_provider_commit_deduplicates_skip_tags(
    github_provider_env: dict[str, str | Git],
) -> None:
    git_client = github_provider_env["git"]
    assert isinstance(git_client, Git)
    repo_dir = str(github_provider_env["repo"])

    provider = GitHubProvider("https://github.com/org/repo.git", "token", git_client)

    # Stage a file
    with open(os.path.join(repo_dir, "file.txt"), "w") as f:
        f.write("content")
    git_client.add(all_files=True)

    # Commit via provider with existing [skip ci]
    provider.commit("feat: add file [skip ci]", author="Test <test@example.com>")

    # Verify commit message (should not append [skip actions])
    msg = git_client.log_one("HEAD", "%B")
    assert msg.strip() == "feat: add file [skip ci]"


def test_github_provider_commit_with_body(
    github_provider_env: dict[str, str | Git],
) -> None:
    git_client = github_provider_env["git"]
    assert isinstance(git_client, Git)
    repo_dir = str(github_provider_env["repo"])

    provider = GitHubProvider("https://github.com/org/repo.git", "token", git_client)

    # Stage a file
    with open(os.path.join(repo_dir, "file.txt"), "w") as f:
        f.write("content")
    git_client.add(all_files=True)

    # Commit via provider with body
    provider.commit(
        "sync: update", author="Test <test@example.com>", body="Origin commit 12345"
    )

    # Verify commit message
    msg = git_client.log_one("HEAD", "%B")
    assert "sync: update [skip actions]" in msg
    assert "Origin commit 12345" in msg

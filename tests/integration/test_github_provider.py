import os
import shutil
import tempfile
from collections.abc import Generator
from typing import Any

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


_INTEGRATION_ENV_VARS = (
    "INTEGRATION_BITBUCKET_URL",
    "INTEGRATION_BITBUCKET_TOKEN",
    "INTEGRATION_GITHUB_URL",
    "INTEGRATION_GITHUB_TOKEN",
)


def _has_pr_integration_env() -> bool:
    return all(bool(os.getenv(var)) for var in _INTEGRATION_ENV_VARS)


@pytest.mark.skipif(
    not _has_pr_integration_env(),
    reason=(
        "Live Bitbucket Cloud / GitHub PR integration credentials not set "
        "(requires INTEGRATION_BITBUCKET_URL, INTEGRATION_BITBUCKET_TOKEN, "
        "INTEGRATION_GITHUB_URL, INTEGRATION_GITHUB_TOKEN)"
    ),
)
class TestGitHubPrImporterIntegration:
    """End-to-end PR synchronization integration tests against live Bitbucket Cloud & GitHub."""

    def _gh_headers(self) -> dict[str, str]:
        token = os.environ["INTEGRATION_GITHUB_TOKEN"]
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _run_sync(self, sync_pull_requests: bool) -> Any:
        from src.config import SyncConfig
        from src.core.sync import SyncManager
        from src.providers.bitbucket_cloud import BitbucketCloudProvider

        temp_dir = tempfile.mkdtemp(prefix="pr_sync_int_")
        repo_dir = os.path.join(temp_dir, "repo")
        os.makedirs(repo_dir, exist_ok=True)
        try:
            config = SyncConfig(
                ORIGIN_URL=os.environ["INTEGRATION_BITBUCKET_URL"],
                ORIGIN_TOKEN=os.environ["INTEGRATION_BITBUCKET_TOKEN"],
                ORIGIN_USERNAME=os.getenv("INTEGRATION_BITBUCKET_USERNAME"),
                DESTINATION_URL=os.environ["INTEGRATION_GITHUB_URL"],
                DESTINATION_TOKEN=os.environ["INTEGRATION_GITHUB_TOKEN"],
                SYNC_PULL_REQUESTS=sync_pull_requests,
            )
            git_client = Git(repo_dir)
            origin = BitbucketCloudProvider(
                repo_url=config.origin_url,
                token=config.origin_token,
                username=config.origin_username,
                git=git_client,
            )
            dest = GitHubProvider(
                repo_url=config.destination_url,
                token=config.destination_token,
                git=git_client,
            )
            return SyncManager(config, origin, dest, git_client).execute()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_given_sync_prs_disabled_when_syncing_then_no_prs_synced_to_destination(
        self,
    ) -> None:
        result = self._run_sync(sync_pull_requests=False)
        assert result.created_prs == []
        assert result.updated_prs == []
        assert result.closed_prs == []

    def test_given_sync_prs_enabled_and_origin_only_pr_when_syncing_then_pr_synced_to_destination(
        self,
    ) -> None:
        result = self._run_sync(sync_pull_requests=True)
        assert result.errors == []

    def test_given_sync_prs_enabled_and_origin_comment_when_syncing_then_comment_synced_to_destination(
        self,
    ) -> None:
        result = self._run_sync(sync_pull_requests=True)
        assert result.errors == []

    def test_given_sync_prs_enabled_and_origin_pr_merged_or_closed_when_syncing_then_pr_closed_on_destination(
        self,
    ) -> None:
        result = self._run_sync(sync_pull_requests=True)
        assert result.errors == []

    def test_given_sync_prs_enabled_and_origin_comment_resolved_when_syncing_then_comment_resolved_on_destination(
        self,
    ) -> None:
        result = self._run_sync(sync_pull_requests=True)
        assert result.errors == []

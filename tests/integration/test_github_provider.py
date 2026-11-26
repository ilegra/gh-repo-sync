import os
import shutil
import tempfile
from collections.abc import Generator
from typing import Any

import pytest

from src.git.client import Git
from src.providers.bitbucket_cloud import BitbucketCloudProvider
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


class _ContainerizedBitbucketOrigin(BitbucketCloudProvider):
    """Uses local bare Git repo for git ops and containerized Bitbucket API for PRs."""

    def __init__(
        self,
        local_git_url: str,
        api_base_url: str,
        git: Git,
    ) -> None:
        super().__init__(
            repo_url="https://bitbucket.org/test-ws/test-repo",
            token="bb-test-token",
            git=git,
            api_base_url=api_base_url,
        )
        self._local_git_url = local_git_url

    def get_authenticated_url(self) -> str:
        return self._local_git_url

    def is_repo_disabled(self) -> bool:
        return False


class _ContainerizedGitHubDestination(GitHubProvider):
    """Uses local bare Git repo for git ops and containerized GitHub API for PRs."""

    def __init__(
        self,
        local_git_url: str,
        api_base_url: str,
        git: Git,
    ) -> None:
        super().__init__(
            repo_url="https://github.com/test-org/test-repo",
            token="gh-test-token",
            git=git,
            api_base_url=api_base_url,
        )
        self._local_git_url = local_git_url

    def get_authenticated_url(self) -> str:
        return self._local_git_url


def _setup_seeded_git_repos(root_dir: str) -> tuple[str, str]:
    """Creates bare origin & destination repos with 'main' and 'feat/pr-sync' branches."""
    origin_bare = os.path.join(root_dir, "origin.git")
    dest_bare = os.path.join(root_dir, "dest.git")
    os.makedirs(origin_bare, exist_ok=True)
    os.makedirs(dest_bare, exist_ok=True)
    Git(origin_bare).run("init", "--bare", "-b", "main", check=True)
    Git(dest_bare).run("init", "--bare", "-b", "main", check=True)

    work = os.path.join(root_dir, "seed_work")
    git = create_local_repo(work)
    with open(os.path.join(work, "README.md"), "w", encoding="utf-8") as f:
        f.write("initial\n")
    git.add(all_files=True)
    git.commit("chore: init", author="Tester <tester@example.com>")
    git.remote_add("origin", origin_bare)
    git.remote_add("dest", dest_bare)
    git.push("origin", ref="main")
    git.push("dest", ref="main")

    # Feature branch only on origin
    git.checkout("feat/pr-sync", create=True)
    with open(os.path.join(work, "feature.txt"), "w", encoding="utf-8") as f:
        f.write("feature work\n")
    git.add(all_files=True)
    git.commit("feat: add feature", author="Tester <tester@example.com>")
    git.push("origin", ref="feat/pr-sync")

    return origin_bare, dest_bare


class TestGitHubPrImporterIntegration:
    """End-to-end PR sync tests against containerized Bitbucket Cloud & GitHub emulators."""

    @pytest.fixture(autouse=True)
    def _reset_containers(
        self,
        bitbucket_cloud_container: dict[str, Any],
        github_container: dict[str, Any],
    ) -> None:
        import requests

        requests.post(
            f"{bitbucket_cloud_container['base_url']}/_seed/reset", timeout=5
        ).raise_for_status()
        requests.post(
            f"{github_container['base_url']}/_seed/reset", timeout=5
        ).raise_for_status()

    def _run_sync(
        self,
        origin_bare: str,
        dest_bare: str,
        bb_base_url: str,
        gh_base_url: str,
        sync_pull_requests: bool,
        pr_user_mapping: str = "",
    ) -> Any:
        from src.config import SyncConfig
        from src.core.sync import SyncManager

        temp_dir = tempfile.mkdtemp(prefix="pr_sync_int_")
        repo_dir = os.path.join(temp_dir, "repo")
        os.makedirs(repo_dir, exist_ok=True)
        try:
            config = SyncConfig(
                ORIGIN_URL="https://bitbucket.org/test-ws/test-repo",
                ORIGIN_TOKEN="bb-test-token",
                DESTINATION_URL="https://github.com/test-org/test-repo",
                DESTINATION_TOKEN="gh-test-token",
                SYNC_PULL_REQUESTS=sync_pull_requests,
                PR_USER_MAPPING=pr_user_mapping,
            )
            git_client = Git(repo_dir)
            origin = _ContainerizedBitbucketOrigin(
                local_git_url=origin_bare,
                api_base_url=f"{bb_base_url}/2.0",
                git=git_client,
            )
            dest = _ContainerizedGitHubDestination(
                local_git_url=dest_bare,
                api_base_url=gh_base_url,
                git=git_client,
            )
            return SyncManager(config, origin, dest, git_client).execute()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_given_sync_prs_disabled_when_syncing_then_no_prs_synced_to_destination(
        self,
        bitbucket_cloud_container: dict[str, Any],
        github_container: dict[str, Any],
    ) -> None:
        import requests

        bb_url = bitbucket_cloud_container["base_url"]
        gh_url = github_container["base_url"]

        root = tempfile.mkdtemp(prefix="pr_int_repos_")
        try:
            origin_bare, dest_bare = _setup_seeded_git_repos(root)
            requests.post(
                f"{bb_url}/_seed/pullrequests",
                json={
                    "id": 1,
                    "title": "Feature PR",
                    "source_branch": "feat/pr-sync",
                    "target_branch": "main",
                },
                timeout=5,
            ).raise_for_status()

            self._run_sync(
                origin_bare, dest_bare, bb_url, gh_url, sync_pull_requests=False
            )

            gh_prs = requests.get(
                f"{gh_url}/repos/test-org/test-repo/pulls?state=open", timeout=5
            ).json()
            assert gh_prs == []
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_given_sync_prs_enabled_and_origin_only_pr_when_syncing_then_pr_synced_to_destination(
        self,
        bitbucket_cloud_container: dict[str, Any],
        github_container: dict[str, Any],
    ) -> None:
        import requests

        bb_url = bitbucket_cloud_container["base_url"]
        gh_url = github_container["base_url"]

        root = tempfile.mkdtemp(prefix="pr_int_repos_")
        try:
            origin_bare, dest_bare = _setup_seeded_git_repos(root)
            requests.post(
                f"{bb_url}/_seed/pullrequests",
                json={
                    "id": 42,
                    "title": "Add PR sync",
                    "description": "Synced from Bitbucket",
                    "author": "Alice",
                    "source_branch": "feat/pr-sync",
                    "target_branch": "main",
                },
                timeout=5,
            ).raise_for_status()

            result = self._run_sync(
                origin_bare, dest_bare, bb_url, gh_url, sync_pull_requests=True
            )
            assert result.errors == []

            gh_prs = requests.get(
                f"{gh_url}/repos/test-org/test-repo/pulls?state=open", timeout=5
            ).json()
            assert len(gh_prs) == 1
            assert gh_prs[0]["title"] == "Add PR sync"
            assert gh_prs[0]["head"]["ref"] == "feat/pr-sync"
            assert gh_prs[0]["base"]["ref"] == "main"
            assert "<!-- gh-repo-sync:origin-pr-id=42 -->" in gh_prs[0]["body"]
            assert "Alice" in gh_prs[0]["body"]
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_given_sync_prs_enabled_and_origin_comment_when_syncing_then_comment_synced_to_destination(
        self,
        bitbucket_cloud_container: dict[str, Any],
        github_container: dict[str, Any],
    ) -> None:
        import requests

        bb_url = bitbucket_cloud_container["base_url"]
        gh_url = github_container["base_url"]

        root = tempfile.mkdtemp(prefix="pr_int_repos_")
        try:
            origin_bare, dest_bare = _setup_seeded_git_repos(root)
            requests.post(
                f"{bb_url}/_seed/pullrequests",
                json={
                    "id": 10,
                    "title": "Comment PR",
                    "source_branch": "feat/pr-sync",
                    "target_branch": "main",
                },
                timeout=5,
            ).raise_for_status()
            requests.post(
                f"{bb_url}/_seed/pullrequests/10/comments",
                json={"id": 501, "body": "Please rename this", "author": "Bob"},
                timeout=5,
            ).raise_for_status()

            result = self._run_sync(
                origin_bare, dest_bare, bb_url, gh_url, sync_pull_requests=True
            )
            assert result.errors == []

            gh_prs = requests.get(
                f"{gh_url}/repos/test-org/test-repo/pulls?state=open", timeout=5
            ).json()
            pr_num = gh_prs[0]["number"]
            comments = requests.get(
                f"{gh_url}/repos/test-org/test-repo/issues/{pr_num}/comments", timeout=5
            ).json()
            assert len(comments) == 1
            assert "Please rename this" in comments[0]["body"]
            assert "Bob" in comments[0]["body"]
            assert "<!-- gh-repo-sync:origin-comment-id=501 -->" in comments[0]["body"]
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_given_sync_prs_enabled_and_origin_pr_merged_or_closed_when_syncing_then_pr_closed_on_destination(
        self,
        bitbucket_cloud_container: dict[str, Any],
        github_container: dict[str, Any],
    ) -> None:
        import requests

        bb_url = bitbucket_cloud_container["base_url"]
        gh_url = github_container["base_url"]

        root = tempfile.mkdtemp(prefix="pr_int_repos_")
        try:
            origin_bare, dest_bare = _setup_seeded_git_repos(root)
            requests.post(
                f"{bb_url}/_seed/pullrequests",
                json={
                    "id": 77,
                    "title": "Merge me",
                    "source_branch": "feat/pr-sync",
                    "target_branch": "main",
                },
                timeout=5,
            ).raise_for_status()

            # First sync creates PR on GitHub
            self._run_sync(
                origin_bare, dest_bare, bb_url, gh_url, sync_pull_requests=True
            )
            gh_prs = requests.get(
                f"{gh_url}/repos/test-org/test-repo/pulls?state=open", timeout=5
            ).json()
            pr_num = gh_prs[0]["number"]

            # Mark PR merged on Bitbucket Cloud
            requests.patch(
                f"{bb_url}/_seed/pullrequests/77",
                json={"state": "MERGED"},
                timeout=5,
            ).raise_for_status()

            # Second sync closes PR on GitHub with status note
            result = self._run_sync(
                origin_bare, dest_bare, bb_url, gh_url, sync_pull_requests=True
            )
            assert result.errors == []

            pr_state = requests.get(
                f"{gh_url}/repos/test-org/test-repo/pulls/{pr_num}", timeout=5
            ).json()
            assert pr_state["state"] == "closed"

            comments = requests.get(
                f"{gh_url}/repos/test-org/test-repo/issues/{pr_num}/comments", timeout=5
            ).json()
            assert any("**merged**" in c["body"] for c in comments)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_given_sync_prs_enabled_and_origin_comment_resolved_when_syncing_then_comment_resolved_on_destination(
        self,
        bitbucket_cloud_container: dict[str, Any],
        github_container: dict[str, Any],
    ) -> None:
        import requests

        bb_url = bitbucket_cloud_container["base_url"]
        gh_url = github_container["base_url"]

        root = tempfile.mkdtemp(prefix="pr_int_repos_")
        try:
            origin_bare, dest_bare = _setup_seeded_git_repos(root)
            requests.post(
                f"{bb_url}/_seed/pullrequests",
                json={
                    "id": 88,
                    "title": "Resolve comment PR",
                    "source_branch": "feat/pr-sync",
                    "target_branch": "main",
                },
                timeout=5,
            ).raise_for_status()
            requests.post(
                f"{bb_url}/_seed/pullrequests/88/comments",
                json={"id": 601, "body": "Fix typo", "author": "Carol"},
                timeout=5,
            ).raise_for_status()

            # First sync creates PR + comment
            self._run_sync(
                origin_bare, dest_bare, bb_url, gh_url, sync_pull_requests=True
            )
            gh_prs = requests.get(
                f"{gh_url}/repos/test-org/test-repo/pulls?state=open", timeout=5
            ).json()
            pr_num = gh_prs[0]["number"]
            comments = requests.get(
                f"{gh_url}/repos/test-org/test-repo/issues/{pr_num}/comments", timeout=5
            ).json()
            node_id = comments[0]["node_id"]

            # Resolve comment on Bitbucket Cloud
            requests.post(
                f"{bb_url}/_seed/pullrequests/88/comments/601/resolve",
                json={"resolved_by": "Alice"},
                timeout=5,
            ).raise_for_status()

            # Second sync resolves comment on GitHub via GraphQL
            result = self._run_sync(
                origin_bare, dest_bare, bb_url, gh_url, sync_pull_requests=True
            )
            assert result.errors == []

            gql_resp = requests.post(
                f"{gh_url}/graphql",
                json={
                    "query": (
                        "query($id: ID!) { node(id: $id) "
                        "{ ... on IssueComment { isMinimized minimizedReason body } } }"
                    ),
                    "variables": {"id": node_id},
                },
                timeout=5,
            ).json()
            node = gql_resp["data"]["node"]
            assert node["isMinimized"] is True
            assert node["minimizedReason"] == "RESOLVED"
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_given_org_members_and_pr_with_reviewers_when_syncing_then_assigns_author_requests_reviewers_and_mentions_users(
        self,
        bitbucket_cloud_container: dict[str, Any],
        github_container: dict[str, Any],
    ) -> None:
        import requests

        bb_url = bitbucket_cloud_container["base_url"]
        gh_url = github_container["base_url"]

        root = tempfile.mkdtemp(prefix="pr_int_repos_")
        try:
            origin_bare, dest_bare = _setup_seeded_git_repos(root)
            requests.post(
                f"{gh_url}/_seed/org_members",
                json={
                    "org": "test-org",
                    "members": [
                        {"login": "jdoe", "name": "Jane Doe"},
                        {"login": "bsmith", "name": "Bob Smith"},
                        {"login": "cwhite", "name": "Carol White"},
                    ],
                },
                timeout=5,
            ).raise_for_status()
            requests.post(
                f"{bb_url}/_seed/pullrequests",
                json={
                    "id": 91,
                    "title": "Resolve users PR",
                    "description": "Body",
                    "author": "Jane Doe",
                    "reviewers": ["Bob Smith", "Carol White"],
                    "source_branch": "feat/pr-sync",
                    "target_branch": "main",
                },
                timeout=5,
            ).raise_for_status()
            requests.post(
                f"{bb_url}/_seed/pullrequests/91/comments",
                json={"id": 701, "body": "LGTM!", "author": "Bob Smith"},
                timeout=5,
            ).raise_for_status()

            result = self._run_sync(
                origin_bare, dest_bare, bb_url, gh_url, sync_pull_requests=True
            )
            assert result.errors == []

            gh_prs = requests.get(
                f"{gh_url}/repos/test-org/test-repo/pulls?state=open", timeout=5
            ).json()
            assert len(gh_prs) == 1
            pr = gh_prs[0]
            assert "Author: @jdoe" in pr["body"]
            assert [u["login"] for u in pr["assignees"]] == ["jdoe"]
            assert [u["login"] for u in pr["requested_reviewers"]] == [
                "bsmith",
                "cwhite",
            ]

            comments = requests.get(
                f"{gh_url}/repos/test-org/test-repo/issues/{pr['number']}/comments",
                timeout=5,
            ).json()
            assert len(comments) == 1
            assert comments[0]["body"].startswith("> @bsmith\n\nLGTM!")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_given_pr_user_mapping_override_when_syncing_then_resolves_mapped_users_and_falls_back_for_unknown(
        self,
        bitbucket_cloud_container: dict[str, Any],
        github_container: dict[str, Any],
    ) -> None:
        import requests

        bb_url = bitbucket_cloud_container["base_url"]
        gh_url = github_container["base_url"]

        root = tempfile.mkdtemp(prefix="pr_int_repos_")
        try:
            origin_bare, dest_bare = _setup_seeded_git_repos(root)
            requests.post(
                f"{bb_url}/_seed/pullrequests",
                json={
                    "id": 92,
                    "title": "Mapped users PR",
                    "author": "Doe, Jane",
                    "reviewers": ["External Reviewer"],
                    "source_branch": "feat/pr-sync",
                    "target_branch": "main",
                },
                timeout=5,
            ).raise_for_status()
            requests.post(
                f"{bb_url}/_seed/pullrequests/92/comments",
                json={
                    "id": 702,
                    "body": "Question",
                    "author": "External Reviewer",
                },
                timeout=5,
            ).raise_for_status()

            result = self._run_sync(
                origin_bare,
                dest_bare,
                bb_url,
                gh_url,
                sync_pull_requests=True,
                pr_user_mapping='{"Doe, Jane": "jdoe"}',
            )
            assert result.errors == []

            gh_prs = requests.get(
                f"{gh_url}/repos/test-org/test-repo/pulls?state=open", timeout=5
            ).json()
            assert len(gh_prs) == 1
            pr = gh_prs[0]
            assert "Author: @jdoe" in pr["body"]
            assert [u["login"] for u in pr["assignees"]] == ["jdoe"]
            assert pr["requested_reviewers"] == []

            comments = requests.get(
                f"{gh_url}/repos/test-org/test-repo/issues/{pr['number']}/comments",
                timeout=5,
            ).json()
            assert len(comments) == 1
            assert comments[0]["body"].startswith("> **External Reviewer**\n\nQuestion")
        finally:
            shutil.rmtree(root, ignore_errors=True)

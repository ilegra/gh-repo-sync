from typing import Any

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


class TestGitHubProvider:
    def test_given_valid_github_url_when_getting_pr_importer_then_returns_github_pr_importer(
        self, mocker: MockerFixture
    ) -> None:
        from src.providers.github import GitHubPrImporter

        provider = GitHubProvider(
            repo_url="https://github.com/my-org/my-repo.git",
            token="gh-token",
            git=mocker.MagicMock(),
        )
        importer = provider.get_pr_importer()
        assert isinstance(importer, GitHubPrImporter)
        assert provider.get_pr_importer() is importer

    def test_given_unparseable_github_url_when_getting_pr_importer_then_returns_none(
        self, mocker: MockerFixture
    ) -> None:
        provider = GitHubProvider(
            repo_url="not-a-valid-url",
            token="gh-token",
            git=mocker.MagicMock(),
        )
        assert provider.get_pr_importer() is None


class TestGitHubPrImporter:
    def _make_importer(self, host: str = "github.com") -> Any:
        from src.providers.github import GitHubPrImporter

        return GitHubPrImporter(
            owner="my-org",
            repo="my-repo",
            token="gh-token",
            host=host,
        )

    def _make_exporter(
        self,
        mocker: MockerFixture,
        comments: Any = None,
        pr_lookup: Any = None,
    ) -> Any:
        exporter = mocker.MagicMock()
        exporter.get_pull_request_comments.return_value = comments or []
        exporter.get_pull_request.return_value = pr_lookup
        return exporter

    @staticmethod
    def _json_body(call: Any) -> dict[str, Any]:
        import json

        body = call.request.body
        assert isinstance(body, (str, bytes))
        result: dict[str, Any] = json.loads(body)
        return result

    def test_given_ghe_url_when_reconciling_prs_then_uses_enterprise_rest_and_graphql_endpoints(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest, PullRequestComment

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://ghe.example.com/api/v3/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://ghe.example.com/api/v3/repos/my-org/my-repo/pulls",
                json={"number": 10},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://ghe.example.com/api/v3/repos/my-org/my-repo/issues/10/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://ghe.example.com/api/v3/repos/my-org/my-repo/issues/10/comments",
                json={"id": 1, "node_id": "IC_ghe1"},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://ghe.example.com/api/graphql",
                json={
                    "data": {
                        "minimizeComment": {"minimizedComment": {"isMinimized": True}}
                    }
                },
                status=200,
            )

            exporter = self._make_exporter(
                mocker,
                comments=[
                    PullRequestComment(
                        id="c1", body="Done", author="Alice", is_resolved=True
                    )
                ],
            )
            importer = self._make_importer(host="ghe.example.com")
            origin_pr = PullRequest(
                id="1",
                title="GHE PR",
                description="Desc",
                source_branch="feat/a",
                target_branch="main",
                author="Alice",
            )
            res = importer.reconcile([origin_pr], exporter)
            assert res.created_prs == [10]
            assert res.synced_pr_comments == 1

    def test_given_new_origin_pr_when_reconciling_then_creates_github_pr_with_attribution_marker(
        self, mocker: MockerFixture
    ) -> None:

        import responses

        from src.providers.base import PullRequest

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 5},
                status=201,
            )

            exporter = self._make_exporter(mocker)
            origin_pr = PullRequest(
                id="42",
                title="Add feature",
                description="Details here",
                source_branch="feat/x",
                target_branch="main",
                author="Bob",
                is_draft=True,
                url="https://bitbucket.org/ws/repo/pull-requests/42",
            )
            res = self._make_importer().reconcile([origin_pr], exporter)
            assert res.created_prs == [5]
            payload = self._json_body(rsps.calls[1])
            assert payload["title"] == "Add feature"
            assert payload["head"] == "feat/x"
            assert payload["base"] == "main"
            assert payload["draft"] is True
            assert "<!-- gh-repo-sync:origin-pr-id=42 -->" in payload["body"]
            assert "Bob" in payload["body"]

    def test_given_github_422_no_diff_when_reconciling_then_skips_pr_without_crashing(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"message": "No commits between main and feat/empty"},
                status=422,
            )

            origin_pr = PullRequest(
                id="1",
                title="Empty",
                description="",
                source_branch="feat/empty",
                target_branch="main",
                author="Bob",
            )
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker)
            )
            assert res.created_prs == []
            assert res.errors == []

    def test_given_github_api_error_when_reconciling_then_records_error_and_continues(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                status=500,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 2},
                status=201,
            )

            prs = [
                PullRequest("1", "Fail", "", "b1", "main", "A"),
                PullRequest("2", "Pass", "", "b2", "main", "B"),
            ]
            res = self._make_importer().reconcile(prs, self._make_exporter(mocker))
            assert res.created_prs == [2]
            assert len(res.errors) == 1

    def test_given_unchanged_synced_pr_when_reconciling_then_skips_update(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest

        body = (
            "> **Synced from origin** | Author: **Alice** | Original PR: #7\n\n"
            "Same body\n\n"
            "<!-- gh-repo-sync:origin-pr-id=7 -->"
        )
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 70,
                        "title": "Same title",
                        "body": body,
                        "head": {"ref": "feat/a"},
                        "base": {"ref": "main"},
                        "state": "open",
                    }
                ],
                status=200,
            )

            origin_pr = PullRequest(
                "7", "Same title", "Same body", "feat/a", "main", "Alice"
            )
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker)
            )
            assert res.updated_prs == []
            assert len(rsps.calls) == 1

    def test_given_modified_origin_pr_when_reconciling_then_updates_github_pr(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 70,
                        "title": "Old title",
                        "body": "Old\n\n<!-- gh-repo-sync:origin-pr-id=7 -->",
                        "head": {"ref": "feat/a"},
                        "base": {"ref": "main"},
                        "state": "open",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.PATCH,
                "https://api.github.com/repos/my-org/my-repo/pulls/70",
                json={"number": 70},
                status=200,
            )

            origin_pr = PullRequest(
                "7", "New title", "New body", "feat/a", "develop", "Alice"
            )
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker)
            )
            assert res.updated_prs == [70]

    def test_given_branch_mapping_when_reconciling_then_translates_source_and_target_branches(
        self, mocker: MockerFixture
    ) -> None:

        import responses

        from src.providers.base import PullRequest

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 11},
                status=201,
            )

            origin_pr = PullRequest("1", "Mapped", "", "dev-feat", "master", "Alice")
            res = self._make_importer().reconcile(
                [origin_pr],
                self._make_exporter(mocker),
                branch_mapping={"master": "main", "dev-feat": "feat/mapped"},
                available_branches={"main", "feat/mapped"},
            )
            assert res.created_prs == [11]
            payload = self._json_body(rsps.calls[1])
            assert payload["head"] == "feat/mapped"
            assert payload["base"] == "main"

    def test_given_missing_destination_branch_when_reconciling_then_skips_pr(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[],
                status=200,
            )
            origin_pr = PullRequest(
                "1", "Missing branch", "", "feat/missing", "main", "Alice"
            )
            res = self._make_importer().reconcile(
                [origin_pr],
                self._make_exporter(mocker),
                available_branches={"main"},
            )
            assert res.created_prs == []
            assert len(rsps.calls) == 1

    def test_given_fork_origin_pr_when_reconciling_then_skips_pr(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[],
                status=200,
            )
            origin_pr = PullRequest(
                "1", "Fork", "", "feat/fork", "main", "External", is_from_fork=True
            )
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker)
            )
            assert res.created_prs == []
            assert len(rsps.calls) == 1

    def test_given_new_general_and_inline_comments_when_reconciling_then_creates_github_comments(
        self, mocker: MockerFixture
    ) -> None:

        import responses

        from src.providers.base import PullRequest, PullRequestComment

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 3},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/3/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/3/comments",
                json={"id": 100, "node_id": "IC_100"},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/3/comments",
                json={"id": 101, "node_id": "IC_101"},
                status=201,
            )

            comments = [
                PullRequestComment(id="1", body="Looks good", author="Alice"),
                PullRequestComment(
                    id="2", body="Rename var", author="Bob", file_path="a.py", line=12
                ),
            ]
            origin_pr = PullRequest("10", "PR", "", "feat/a", "main", "Alice")
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 2
            body2 = self._json_body(rsps.calls[4])["body"]
            assert "`a.py` (line 12)" in body2
            assert "<!-- gh-repo-sync:origin-comment-id=2 -->" in body2

    def test_given_edited_origin_comment_when_reconciling_then_updates_existing_github_comment(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest, PullRequestComment

        pr_body = (
            "> **Synced from origin** | Author: **Alice** | Original PR: #10\n\n"
            "<!-- gh-repo-sync:origin-pr-id=10 -->"
        )
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 3,
                        "title": "PR",
                        "body": pr_body,
                        "head": {"ref": "feat/a"},
                        "base": {"ref": "main"},
                        "state": "open",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/3/comments?per_page=100",
                json=[
                    {
                        "id": 500,
                        "node_id": "IC_500",
                        "body": "> **Alice**\n\nOld text\n\n<!-- gh-repo-sync:origin-comment-id=1 -->",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={"data": {"nodes": [{"id": "IC_500", "isMinimized": False}]}},
                status=200,
            )
            rsps.add(
                responses.PATCH,
                "https://api.github.com/repos/my-org/my-repo/issues/comments/500",
                json={"id": 500},
                status=200,
            )

            comments = [PullRequestComment(id="1", body="Edited text", author="Alice")]
            origin_pr = PullRequest("10", "PR", "", "feat/a", "main", "Alice")
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1

    def test_given_unchanged_origin_comment_when_reconciling_then_skips_comment_update(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest, PullRequestComment

        pr_body = (
            "> **Synced from origin** | Author: **Alice** | Original PR: #10\n\n"
            "<!-- gh-repo-sync:origin-pr-id=10 -->"
        )
        comment_body = (
            "> **Alice**\n\nSame text\n\n<!-- gh-repo-sync:origin-comment-id=1 -->"
        )
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 3,
                        "title": "PR",
                        "body": pr_body,
                        "head": {"ref": "feat/a"},
                        "base": {"ref": "main"},
                        "state": "open",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/3/comments?per_page=100",
                json=[{"id": 500, "node_id": "IC_500", "body": comment_body}],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={"data": {"nodes": [{"id": "IC_500", "isMinimized": False}]}},
                status=200,
            )

            comments = [PullRequestComment(id="1", body="Same text", author="Alice")]
            origin_pr = PullRequest("10", "PR", "", "feat/a", "main", "Alice")
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 0

    def test_given_resolved_origin_comment_when_reconciling_then_minimizes_github_comment_as_resolved(
        self, mocker: MockerFixture
    ) -> None:

        import responses

        from src.providers.base import PullRequest, PullRequestComment

        pr_body = (
            "> **Synced from origin** | Author: **Alice** | Original PR: #10\n\n"
            "<!-- gh-repo-sync:origin-pr-id=10 -->"
        )
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 3,
                        "title": "PR",
                        "body": pr_body,
                        "head": {"ref": "feat/a"},
                        "base": {"ref": "main"},
                        "state": "open",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/3/comments?per_page=100",
                json=[
                    {
                        "id": 500,
                        "node_id": "IC_500",
                        "body": "> **Alice**\n\nFix\n\n<!-- gh-repo-sync:origin-comment-id=1 -->",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={"data": {"nodes": [{"id": "IC_500", "isMinimized": False}]}},
                status=200,
            )
            rsps.add(
                responses.PATCH,
                "https://api.github.com/repos/my-org/my-repo/issues/comments/500",
                json={"id": 500},
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {
                        "minimizeComment": {"minimizedComment": {"isMinimized": True}}
                    }
                },
                status=200,
            )

            comments = [
                PullRequestComment(
                    id="1",
                    body="Fix",
                    author="Alice",
                    is_resolved=True,
                    resolved_by="Bob",
                )
            ]
            origin_pr = PullRequest("10", "PR", "", "feat/a", "main", "Alice")
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            gql_payload = self._json_body(rsps.calls[4])
            assert "minimizeComment" in gql_payload["query"]
            assert gql_payload["variables"]["id"] == "IC_500"

    def test_given_reopened_origin_comment_when_reconciling_then_unminimizes_github_comment(
        self, mocker: MockerFixture
    ) -> None:

        import responses

        from src.providers.base import PullRequest, PullRequestComment

        pr_body = (
            "> **Synced from origin** | Author: **Alice** | Original PR: #10\n\n"
            "<!-- gh-repo-sync:origin-pr-id=10 -->"
        )
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 3,
                        "title": "PR",
                        "body": pr_body,
                        "head": {"ref": "feat/a"},
                        "base": {"ref": "main"},
                        "state": "open",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/3/comments?per_page=100",
                json=[
                    {
                        "id": 500,
                        "node_id": "IC_500",
                        "body": "> **Alice** | ✅ Resolved\n\nFix\n\n<!-- gh-repo-sync:origin-comment-id=1 -->",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={"data": {"nodes": [{"id": "IC_500", "isMinimized": True}]}},
                status=200,
            )
            rsps.add(
                responses.PATCH,
                "https://api.github.com/repos/my-org/my-repo/issues/comments/500",
                json={"id": 500},
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {
                        "unminimizeComment": {
                            "unminimizedComment": {"isMinimized": False}
                        }
                    }
                },
                status=200,
            )

            comments = [
                PullRequestComment(
                    id="1", body="Fix", author="Alice", is_resolved=False
                )
            ]
            origin_pr = PullRequest("10", "PR", "", "feat/a", "main", "Alice")
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            gql_payload = self._json_body(rsps.calls[4])
            assert "unminimizeComment" in gql_payload["query"]

    def test_given_merged_origin_pr_when_reconciling_then_syncs_final_comments_posts_note_and_closes_pr(
        self, mocker: MockerFixture
    ) -> None:

        import responses

        from src.providers.base import PullRequest, PullRequestComment

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 9,
                        "title": "Done",
                        "body": "<!-- gh-repo-sync:origin-pr-id=99 -->",
                        "head": {"ref": "feat/done"},
                        "base": {"ref": "main"},
                        "state": "open",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/9/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/9/comments",
                json={"id": 1, "node_id": "IC_1"},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/9/comments",
                json={"id": 2, "node_id": "IC_2"},
                status=201,
            )
            rsps.add(
                responses.PATCH,
                "https://api.github.com/repos/my-org/my-repo/pulls/9",
                json={"number": 9, "state": "closed"},
                status=200,
            )

            exporter = self._make_exporter(
                mocker,
                comments=[
                    PullRequestComment(id="c9", body="Final note", author="Alice")
                ],
                pr_lookup=PullRequest(
                    "99", "Done", "", "feat/done", "main", "Alice", state="merged"
                ),
            )
            res = self._make_importer().reconcile([], exporter)
            assert res.closed_prs == [9]
            assert res.synced_pr_comments == 1
            closing_note = self._json_body(rsps.calls[3])["body"]
            assert "**merged**" in closing_note

    def test_given_declined_or_superseded_origin_pr_when_reconciling_then_posts_note_and_closes_pr(
        self, mocker: MockerFixture
    ) -> None:

        import responses

        from src.providers.base import PullRequest

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 12,
                        "title": "Declined",
                        "body": "<!-- gh-repo-sync:origin-pr-id=55 -->",
                        "head": {"ref": "feat/old"},
                        "base": {"ref": "main"},
                        "state": "open",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/12/comments",
                json={"id": 10, "node_id": "IC_10"},
                status=201,
            )
            rsps.add(
                responses.PATCH,
                "https://api.github.com/repos/my-org/my-repo/pulls/12",
                json={"number": 12, "state": "closed"},
                status=200,
            )

            exporter = self._make_exporter(
                mocker,
                pr_lookup=PullRequest(
                    "55", "Declined", "", "feat/old", "main", "Bob", state="declined"
                ),
            )
            res = self._make_importer().reconcile([], exporter)
            assert res.closed_prs == [12]
            closing_note = self._json_body(rsps.calls[1])["body"]
            assert "**declined**" in closing_note

    def test_given_native_github_pr_without_marker_when_reconciling_then_leaves_pr_untouched(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 99,
                        "title": "Native PR",
                        "body": "Created directly on GitHub",
                        "head": {"ref": "feat/native"},
                        "base": {"ref": "main"},
                        "state": "open",
                    }
                ],
                status=200,
            )

            res = self._make_importer().reconcile([], self._make_exporter(mocker))
            assert res.closed_prs == []
            assert len(rsps.calls) == 1

    def test_given_paginated_github_prs_and_comments_when_reconciling_then_follows_link_headers(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest, PullRequestComment

        pr_p1 = (
            "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100"
        )
        pr_p2 = "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100&page=2"
        cm_p1 = (
            "https://api.github.com/repos/my-org/my-repo/issues/2/comments?per_page=100"
        )
        cm_p2 = "https://api.github.com/repos/my-org/my-repo/issues/2/comments?per_page=100&page=2"
        pr2_body = (
            "> **Synced from origin** | Author: **Alice** | Original PR: #20\n\n"
            "<!-- gh-repo-sync:origin-pr-id=20 -->"
        )
        c2_body = "> **Alice**\n\nc2\n\n<!-- gh-repo-sync:origin-comment-id=c2 -->"

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                pr_p1,
                json=[
                    {
                        "number": 1,
                        "title": "Native",
                        "body": "",
                        "head": {"ref": "a"},
                        "base": {"ref": "main"},
                    }
                ],
                headers={"Link": f'<{pr_p2}>; rel="next"'},
                status=200,
            )
            rsps.add(
                responses.GET,
                pr_p2,
                json=[
                    {
                        "number": 2,
                        "title": "PR2",
                        "body": pr2_body,
                        "head": {"ref": "b"},
                        "base": {"ref": "main"},
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.GET,
                cm_p1,
                json=[{"id": 10, "node_id": "IC_10", "body": "native"}],
                headers={"Link": f'<{cm_p2}>; rel="next"'},
                status=200,
            )
            rsps.add(
                responses.GET,
                cm_p2,
                json=[{"id": 11, "node_id": "IC_11", "body": c2_body}],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {
                        "nodes": [
                            {"id": "IC_10", "isMinimized": False},
                            {"id": "IC_11", "isMinimized": False},
                        ]
                    }
                },
                status=200,
            )

            origin_pr = PullRequest("20", "PR2", "", "b", "main", "Alice")
            comments = [PullRequestComment(id="c2", body="c2", author="Alice")]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.created_prs == []
            assert res.updated_prs == []
            assert res.synced_pr_comments == 0

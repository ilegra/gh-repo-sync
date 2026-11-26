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


def _mock_org_members_graphql(
    rsps: Any,
    members: list[dict[str, Any]] | None = None,
    graphql_url: str = "https://api.github.com/graphql",
    has_next_page: bool = False,
    end_cursor: str | None = None,
) -> None:
    import responses

    rsps.add(
        responses.POST,
        graphql_url,
        json={
            "data": {
                "organization": {
                    "membersWithRole": {
                        "nodes": members or [],
                        "pageInfo": {
                            "hasNextPage": has_next_page,
                            "endCursor": end_cursor,
                        },
                    }
                }
            }
        },
        status=200,
    )


class TestGitHubUserResolver:
    def _make_resolver(
        self,
        explicit_mapping: dict[str, str] | None = None,
        org: str = "my-org",
    ) -> Any:
        import requests

        from src.providers.github import GitHubUserResolver

        return GitHubUserResolver(
            org=org,
            graphql_url="https://api.github.com/graphql",
            session=requests.Session(),
            headers={"Authorization": "Bearer gh-token"},
            explicit_mapping=explicit_mapping,
        )

    def test_given_unique_org_member_match_when_resolving_display_name_then_returns_login_case_and_whitespace_insensitively(
        self,
    ) -> None:
        import responses

        with responses.RequestsMock() as rsps:
            _mock_org_members_graphql(
                rsps,
                members=[
                    {"login": "jdoe", "name": "Jane Doe"},
                    {"login": "bsmith", "name": None},
                ],
            )
            resolver = self._make_resolver()
            assert resolver.resolve("  jane   DOE ") == "jdoe"
            assert resolver.resolve("Unknown User") is None
            assert len(rsps.calls) == 1

    def test_given_paginated_org_members_when_resolving_display_name_then_follows_graphql_cursor_and_caches_result(
        self,
    ) -> None:
        import responses

        with responses.RequestsMock() as rsps:
            _mock_org_members_graphql(
                rsps,
                members=[{"login": "alice", "name": "Alice One"}],
                has_next_page=True,
                end_cursor="CUR1",
            )
            _mock_org_members_graphql(
                rsps,
                members=[{"login": "bob", "name": "Bob Two"}],
            )
            resolver = self._make_resolver()
            assert resolver.resolve("Bob Two") == "bob"
            assert resolver.resolve("Alice One") == "alice"
            assert len(rsps.calls) == 2

    def test_given_ambiguous_org_member_display_name_when_resolving_then_returns_none(
        self,
    ) -> None:
        import responses

        with responses.RequestsMock() as rsps:
            _mock_org_members_graphql(
                rsps,
                members=[
                    {"login": "jsmith1", "name": "John Smith"},
                    {"login": "jsmith2", "name": "john  smith"},
                ],
            )
            resolver = self._make_resolver()
            assert resolver.resolve("John Smith") is None

    def test_given_explicit_user_mapping_when_resolving_then_takes_precedence_and_disambiguates_duplicate_names(
        self,
    ) -> None:
        import responses

        with responses.RequestsMock() as rsps:
            resolver = self._make_resolver(
                explicit_mapping={"John Smith": "@jsmith-explicit"}
            )
            assert resolver.resolve("john smith") == "jsmith-explicit"
            assert len(rsps.calls) == 0

    def test_given_missing_members_read_permission_or_graphql_error_when_resolving_then_returns_none_without_retrying(
        self,
    ) -> None:
        import responses

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {"organization": None},
                    "errors": [{"type": "FORBIDDEN", "message": "Missing scope"}],
                },
                status=200,
            )
            resolver = self._make_resolver()
            assert resolver.resolve("Jane Doe") is None
            assert resolver.resolve("Bob Smith") is None
            assert len(rsps.calls) == 1

    def test_given_non_org_personal_owner_when_resolving_then_returns_none_gracefully(
        self,
    ) -> None:
        import responses

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {"organization": None},
                    "errors": [
                        {
                            "type": "NOT_FOUND",
                            "message": "Could not resolve to an Organization",
                        }
                    ],
                },
                status=200,
            )
            resolver = self._make_resolver(org="personal-user")
            assert resolver.resolve("Jane Doe") is None
            assert len(rsps.calls) == 1

    def test_given_network_exception_when_resolving_then_returns_none_gracefully(
        self,
    ) -> None:
        import requests
        import responses

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                body=requests.ConnectionError("network down"),
            )
            resolver = self._make_resolver()
            assert resolver.resolve("Jane Doe") is None
            assert resolver.resolve("Another User") is None
            assert len(rsps.calls) == 1

    def test_given_empty_or_whitespace_display_name_when_resolving_then_returns_none_without_api_call(
        self,
    ) -> None:
        import responses

        with responses.RequestsMock() as rsps:
            resolver = self._make_resolver()
            assert resolver.resolve("") is None
            assert resolver.resolve("   ") is None
            assert len(rsps.calls) == 0


class TestGitHubPrImporter:
    @staticmethod
    def _mock_org_members(
        rsps: Any,
        members: list[dict[str, Any]] | None = None,
        graphql_url: str = "https://api.github.com/graphql",
    ) -> None:
        _mock_org_members_graphql(rsps, members=members, graphql_url=graphql_url)

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
            self._mock_org_members(
                rsps, graphql_url="https://ghe.example.com/api/graphql"
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
                responses.GET,
                "https://ghe.example.com/api/v3/repos/my-org/my-repo/pulls/10/comments?per_page=100",
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
            self._mock_org_members(rsps)
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
            payload = self._json_body(rsps.calls[2])
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
            self._mock_org_members(rsps)

            origin_pr = PullRequest(
                "7", "Same title", "Same body", "feat/a", "main", "Alice"
            )
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker)
            )
            assert res.updated_prs == []
            assert len(rsps.calls) == 2

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
            self._mock_org_members(rsps)
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
            payload = self._json_body(rsps.calls[2])
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
            self._mock_org_members(rsps)
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
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/3/comments?per_page=100",
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
            body2 = self._json_body(rsps.calls[6])["body"]
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
            self._mock_org_members(rsps)
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={"data": {"nodes": [{"id": "IC_500", "isMinimized": False}]}},
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/3/comments?per_page=100",
                json=[],
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
            self._mock_org_members(rsps)
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
            self._mock_org_members(rsps)
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={"data": {"nodes": [{"id": "IC_500", "isMinimized": False}]}},
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/3/comments?per_page=100",
                json=[],
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
            gql_payload = self._json_body(rsps.calls[-1])
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
            self._mock_org_members(rsps)
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={"data": {"nodes": [{"id": "IC_500", "isMinimized": True}]}},
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/3/comments?per_page=100",
                json=[],
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
            gql_payload = self._json_body(rsps.calls[-1])
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
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/9/comments?per_page=100",
                json=[],
                status=200,
            )
            self._mock_org_members(rsps)
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
            closing_note = self._json_body(rsps.calls[5])["body"]
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
            self._mock_org_members(rsps)
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

    def test_given_resolved_author_and_reviewers_when_creating_pr_then_assigns_author_requests_reviewers_and_mentions_in_headers(
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
            self._mock_org_members(
                rsps,
                members=[
                    {"login": "jdoe", "name": "Jane Doe"},
                    {"login": "bsmith", "name": "Bob Smith"},
                    {"login": "cwhite", "name": "Carol White"},
                ],
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 21},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/21/assignees",
                json={"assignees": [{"login": "jdoe"}]},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/21/requested_reviewers",
                json={
                    "requested_reviewers": [
                        {"login": "bsmith"},
                        {"login": "cwhite"},
                    ]
                },
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/21/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/21/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/21/comments",
                json={"id": 300, "node_id": "IC_300"},
                status=201,
            )

            origin_pr = PullRequest(
                id="100",
                title="Resolved PR",
                description="Details",
                source_branch="feat/users",
                target_branch="main",
                author="Jane Doe",
                reviewers=["Bob Smith", "Carol White"],
            )
            comments = [
                PullRequestComment(id="c1", body="Nice work", author="Bob Smith")
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.created_prs == [21]
            assert res.synced_pr_comments == 1
            pr_body = self._json_body(rsps.calls[2])["body"]
            assert "Author: @jdoe" in pr_body
            assert self._json_body(rsps.calls[3]) == {"assignees": ["jdoe"]}
            assert self._json_body(rsps.calls[4]) == {"reviewers": ["bsmith", "cwhite"]}
            comment_body = self._json_body(rsps.calls[7])["body"]
            assert comment_body.startswith("> @bsmith\n\nNice work")

    def test_given_unresolved_author_and_commenter_when_reconciling_then_falls_back_to_plain_text_headers_without_assignees(
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
            self._mock_org_members(rsps, members=[])
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 22},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/22/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/22/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/22/comments",
                json={"id": 301, "node_id": "IC_301"},
                status=201,
            )

            origin_pr = PullRequest(
                id="101",
                title="Unresolved PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Unknown Author",
                reviewers=["Unknown Reviewer"],
            )
            comments = [
                PullRequestComment(id="c2", body="Note", author="Unknown Commenter")
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.created_prs == [22]
            assert (
                "Author: **Unknown Author**" in self._json_body(rsps.calls[2])["body"]
            )
            assert self._json_body(rsps.calls[5])["body"].startswith(
                "> **Unknown Commenter**\n\nNote"
            )

    def test_given_comment_with_resolved_by_when_formatting_then_mentions_comment_author_and_keeps_resolved_by_plain_text(
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
            self._mock_org_members(
                rsps,
                members=[
                    {"login": "jdoe", "name": "Jane Doe"},
                    {"login": "bsmith", "name": "Bob Smith"},
                ],
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 23},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/23/assignees",
                json={"assignees": [{"login": "jdoe"}]},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/23/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/23/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/23/comments",
                json={"id": 302, "node_id": "IC_302"},
                status=201,
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

            origin_pr = PullRequest(
                id="102",
                title="Resolved comment PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Jane Doe",
            )
            comments = [
                PullRequestComment(
                    id="c3",
                    body="Fixed",
                    author="Bob Smith",
                    is_resolved=True,
                    resolved_by="Jane Doe",
                )
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            comment_body = self._json_body(rsps.calls[6])["body"]
            assert comment_body.startswith(
                "> @bsmith | ✅ Resolved by Jane Doe\n\nFixed"
            )

    def test_given_422_on_batch_requested_reviewers_when_reconciling_then_falls_back_to_individual_requests_and_skips_inaccessible_user(
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
            self._mock_org_members(
                rsps,
                members=[
                    {"login": "bsmith", "name": "Bob Smith"},
                    {"login": "noaccess", "name": "No Access"},
                ],
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 24},
                status=201,
            )
            # Batch call fails with 422
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/24/requested_reviewers",
                json={"message": "Reviews may only be requested from collaborators."},
                status=422,
            )
            # Individual call 1 succeeds
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/24/requested_reviewers",
                json={"requested_reviewers": [{"login": "bsmith"}]},
                status=201,
            )
            # Individual call 2 fails with 422 and is skipped
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/24/requested_reviewers",
                json={"message": "Reviews may only be requested from collaborators."},
                status=422,
            )

            origin_pr = PullRequest(
                id="103",
                title="Partial reviewers",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Unknown",
                reviewers=["Bob Smith", "No Access"],
            )
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker)
            )
            assert res.created_prs == [24]
            assert res.errors == []
            assert self._json_body(rsps.calls[3]) == {
                "reviewers": ["bsmith", "noaccess"]
            }
            assert self._json_body(rsps.calls[4]) == {"reviewers": ["bsmith"]}
            assert self._json_body(rsps.calls[5]) == {"reviewers": ["noaccess"]}

    def test_given_422_or_403_on_add_assignees_when_reconciling_then_logs_warning_and_does_not_fail_sync(
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
            self._mock_org_members(
                rsps, members=[{"login": "jdoe", "name": "Jane Doe"}]
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 25},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/25/assignees",
                json={"message": "Resource not accessible by integration"},
                status=403,
            )

            origin_pr = PullRequest(
                id="104",
                title="Assignee 403",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Jane Doe",
            )
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker)
            )
            assert res.created_prs == [25]
            assert res.errors == []

    def test_given_existing_pr_with_already_assigned_author_and_pending_reviewer_when_reconciling_then_makes_no_redundant_user_api_calls(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest

        pr_body = (
            "> **Synced from origin** | Author: @jdoe | Original PR: #105\n\n"
            "<!-- gh-repo-sync:origin-pr-id=105 -->"
        )
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 26,
                        "title": "Already synced",
                        "body": pr_body,
                        "head": {"ref": "feat/x"},
                        "base": {"ref": "main"},
                        "state": "open",
                        "assignees": [{"login": "jdoe"}],
                        "requested_reviewers": [{"login": "bsmith"}],
                    }
                ],
                status=200,
            )
            self._mock_org_members(
                rsps,
                members=[
                    {"login": "jdoe", "name": "Jane Doe"},
                    {"login": "bsmith", "name": "Bob Smith"},
                ],
            )

            origin_pr = PullRequest(
                id="105",
                title="Already synced",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Jane Doe",
                reviewers=["Bob Smith"],
            )
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker)
            )
            assert res.updated_prs == []
            assert len(rsps.calls) == 2

    def test_given_existing_pr_where_reviewer_already_submitted_review_when_reconciling_then_does_not_re_request_reviewer(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest

        pr_body = (
            "> **Synced from origin** | Author: @jdoe | Original PR: #106\n\n"
            "<!-- gh-repo-sync:origin-pr-id=106 -->"
        )
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 27,
                        "title": "Reviewed PR",
                        "body": pr_body,
                        "head": {"ref": "feat/x"},
                        "base": {"ref": "main"},
                        "state": "open",
                        "assignees": [{"login": "jdoe"}],
                        "requested_reviewers": [],
                    }
                ],
                status=200,
            )
            self._mock_org_members(
                rsps,
                members=[
                    {"login": "jdoe", "name": "Jane Doe"},
                    {"login": "bsmith", "name": "Bob Smith"},
                ],
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/27/reviews?per_page=100",
                json=[{"id": 1, "user": {"login": "bsmith"}, "state": "APPROVED"}],
                status=200,
            )

            origin_pr = PullRequest(
                id="106",
                title="Reviewed PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Jane Doe",
                reviewers=["Bob Smith"],
            )
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker)
            )
            assert res.updated_prs == []
            assert len(rsps.calls) == 3

    def test_given_existing_pr_with_added_and_removed_origin_reviewers_when_reconciling_then_adds_new_and_removes_dropped_reviewers(
        self, mocker: MockerFixture
    ) -> None:
        import responses

        from src.providers.base import PullRequest

        pr_body = (
            "> **Synced from origin** | Author: @jdoe | Original PR: #107\n\n"
            "<!-- gh-repo-sync:origin-pr-id=107 -->"
        )
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls?state=open&per_page=100",
                json=[
                    {
                        "number": 28,
                        "title": "Reviewer diff PR",
                        "body": pr_body,
                        "head": {"ref": "feat/x"},
                        "base": {"ref": "main"},
                        "state": "open",
                        "assignees": [{"login": "jdoe"}],
                        "requested_reviewers": [{"login": "oldrev"}],
                    }
                ],
                status=200,
            )
            self._mock_org_members(
                rsps,
                members=[
                    {"login": "jdoe", "name": "Jane Doe"},
                    {"login": "newrev", "name": "New Reviewer"},
                ],
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/28/reviews?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/28/requested_reviewers",
                json={"requested_reviewers": [{"login": "newrev"}]},
                status=201,
            )
            rsps.add(
                responses.DELETE,
                "https://api.github.com/repos/my-org/my-repo/pulls/28/requested_reviewers",
                json={"requested_reviewers": [{"login": "newrev"}]},
                status=200,
            )

            origin_pr = PullRequest(
                id="107",
                title="Reviewer diff PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Jane Doe",
                reviewers=["New Reviewer"],
            )
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker)
            )
            assert res.updated_prs == [28]
            assert self._json_body(rsps.calls[3]) == {"reviewers": ["newrev"]}
            assert self._json_body(rsps.calls[4]) == {"reviewers": ["oldrev"]}

    def test_given_explicit_user_mapping_when_reconciling_then_uses_mapped_github_logins(
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
                json={"number": 29},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/29/assignees",
                json={"assignees": [{"login": "jdoe"}]},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/29/requested_reviewers",
                json={"requested_reviewers": [{"login": "bsmith"}]},
                status=201,
            )

            origin_pr = PullRequest(
                id="108",
                title="Mapped PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Doe, Jane",
                reviewers=["Smith, Bob"],
            )
            res = self._make_importer().reconcile(
                [origin_pr],
                self._make_exporter(mocker),
                user_mapping={"Doe, Jane": "jdoe", "Smith, Bob": "bsmith"},
            )
            assert res.created_prs == [29]
            assert "Author: @jdoe" in self._json_body(rsps.calls[1])["body"]
            assert self._json_body(rsps.calls[2]) == {"assignees": ["jdoe"]}
            assert self._json_body(rsps.calls[3]) == {"reviewers": ["bsmith"]}

    def test_given_single_line_right_and_left_inline_comments_when_reconciling_then_creates_review_comments_with_destination_head_sha(
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
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 30, "head": {"sha": "dest-sha-30"}},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/30/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/30/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/30/comments",
                json={"id": 1001, "node_id": "PRRC_1001"},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/30/comments",
                json={"id": 1002, "node_id": "PRRC_1002"},
                status=201,
            )

            origin_pr = PullRequest(
                id="201",
                title="Inline PR",
                description="",
                source_branch="feat/inline",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="c1",
                    body="Added line",
                    author="Bob",
                    file_path="README.md",
                    line=284,
                    side="RIGHT",
                ),
                PullRequestComment(
                    id="c2",
                    body="Deleted line",
                    author="Bob",
                    file_path="README.md",
                    line=280,
                    side="LEFT",
                ),
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.errors == []
            assert res.synced_pr_comments == 2
            post_calls = [
                c
                for c in rsps.calls
                if c.request.method == "POST"
                and c.request.url
                == "https://api.github.com/repos/my-org/my-repo/pulls/30/comments"
            ]
            assert len(post_calls) == 2
            p1 = self._json_body(post_calls[0])
            p2 = self._json_body(post_calls[1])
            assert p1["commit_id"] == "dest-sha-30"
            assert p1["path"] == "README.md"
            assert p1["line"] == 284
            assert p1["side"] == "RIGHT"
            assert "on `README.md`" not in p1["body"]
            assert p2["line"] == 280
            assert p2["side"] == "LEFT"

    def test_given_multiline_inline_comment_when_reconciling_then_creates_review_comment_with_start_line_and_start_side(
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
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 31, "head": {"sha": "dest-sha-31"}},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/31/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/31/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/31/comments",
                json={"id": 1003, "node_id": "PRRC_1003"},
                status=201,
            )

            origin_pr = PullRequest(
                id="202",
                title="Multiline PR",
                description="",
                source_branch="feat/multi",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="c3",
                    body="Refactor range",
                    author="Bob",
                    file_path="src/app.ts",
                    start_line=10,
                    start_side="RIGHT",
                    line=15,
                    side="RIGHT",
                )
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            payload = self._json_body(rsps.calls[-1])
            assert payload["start_line"] == 10
            assert payload["start_side"] == "RIGHT"
            assert payload["line"] == 15
            assert payload["side"] == "RIGHT"

    def test_given_file_level_inline_comment_when_reconciling_then_creates_review_comment_with_subject_type_file(
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
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 32, "head": {"sha": "dest-sha-32"}},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/32/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/32/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/32/comments",
                json={"id": 1004, "node_id": "PRRC_1004"},
                status=201,
            )

            origin_pr = PullRequest(
                id="203",
                title="File comment PR",
                description="",
                source_branch="feat/file",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="c4",
                    body="Whole file comment",
                    author="Bob",
                    file_path="src/app.ts",
                    line=None,
                )
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            payload = self._json_body(rsps.calls[-1])
            assert payload["subject_type"] == "file"
            assert payload["path"] == "src/app.ts"
            assert "line" not in payload

    def test_given_threaded_and_nested_replies_out_of_order_when_reconciling_then_creates_parents_first_and_attaches_replies_to_root_review_comment(
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
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 33, "head": {"sha": "dest-sha-33"}},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/33/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/33/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/33/comments",
                json={"id": 2001, "node_id": "PRRC_2001"},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/33/comments",
                json={"id": 2002, "node_id": "PRRC_2002", "in_reply_to_id": 2001},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/33/comments",
                json={"id": 2003, "node_id": "PRRC_2003", "in_reply_to_id": 2001},
                status=201,
            )

            origin_pr = PullRequest(
                id="204",
                title="Threaded PR",
                description="",
                source_branch="feat/thread",
                target_branch="main",
                author="Alice",
            )
            # Deliberately out of order: grandchild, child, root
            comments = [
                PullRequestComment(
                    id="c_grand", body="Grandchild", author="Alice", parent_id="c_child"
                ),
                PullRequestComment(
                    id="c_child", body="Child", author="Bob", parent_id="c_root"
                ),
                PullRequestComment(
                    id="c_root",
                    body="Root",
                    author="Alice",
                    file_path="app.py",
                    line=5,
                    side="RIGHT",
                ),
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 3
            post_calls = [
                self._json_body(c)
                for c in rsps.calls
                if c.request.method == "POST"
                and c.request.url
                == "https://api.github.com/repos/my-org/my-repo/pulls/33/comments"
            ]
            assert "origin-comment-id=c_root" in post_calls[0]["body"]
            assert post_calls[1]["in_reply_to"] == 2001
            assert post_calls[2]["in_reply_to"] == 2001

    def test_given_continuous_sync_reply_to_existing_review_comment_when_reconciling_then_attaches_via_origin_comment_id_marker(
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
                        "number": 34,
                        "title": "Existing PR",
                        "body": "> **Synced from origin** | Author: **Alice** | Original PR: #205\n\n<!-- gh-repo-sync:origin-pr-id=205 -->",
                        "head": {"ref": "feat/x", "sha": "dest-sha-34"},
                        "base": {"ref": "main"},
                        "state": "open",
                        "user": {"login": "bot"},
                    }
                ],
                status=200,
            )
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/34/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/34/comments?per_page=100",
                json=[
                    {
                        "id": 55501,
                        "node_id": "PRRC_55501",
                        "body": "> **Alice**\n\nRoot\n\n<!-- gh-repo-sync:origin-comment-id=100 -->",
                        "in_reply_to_id": None,
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "nodes": [
                                        {
                                            "id": "PRRT_1",
                                            "isResolved": False,
                                            "comments": {
                                                "nodes": [
                                                    {
                                                        "id": "PRRC_55501",
                                                        "databaseId": 55501,
                                                    }
                                                ]
                                            },
                                        }
                                    ],
                                    "pageInfo": {
                                        "hasNextPage": False,
                                        "endCursor": None,
                                    },
                                }
                            }
                        }
                    }
                },
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/34/comments",
                json={"id": 55502, "node_id": "PRRC_55502", "in_reply_to_id": 55501},
                status=201,
            )

            origin_pr = PullRequest(
                id="205",
                title="Existing PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="100",
                    body="Root",
                    author="Alice",
                    file_path="app.py",
                    line=10,
                    side="RIGHT",
                ),
                PullRequestComment(
                    id="101", body="New reply", author="Bob", parent_id="100"
                ),
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            payload = self._json_body(rsps.calls[-1])
            assert payload["in_reply_to"] == 55501
            assert "origin-comment-id=101" in payload["body"]

    def test_given_continuous_sync_nested_reply_when_original_root_deleted_on_origin_then_uses_github_in_reply_to_id_as_root(
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
                        "number": 35,
                        "title": "Existing PR",
                        "body": "> **Synced from origin** | Author: **Alice** | Original PR: #206\n\n<!-- gh-repo-sync:origin-pr-id=206 -->",
                        "head": {"ref": "feat/x", "sha": "dest-sha-35"},
                        "base": {"ref": "main"},
                        "state": "open",
                        "user": {"login": "bot"},
                    }
                ],
                status=200,
            )
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/35/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/35/comments?per_page=100",
                json=[
                    {
                        "id": 55502,
                        "node_id": "PRRC_55502",
                        "body": "> **Bob**\n\nFirst reply\n\n<!-- gh-repo-sync:origin-comment-id=101 -->",
                        "in_reply_to_id": 55501,
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "nodes": [],
                                    "pageInfo": {
                                        "hasNextPage": False,
                                        "endCursor": None,
                                    },
                                }
                            }
                        }
                    }
                },
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/35/comments",
                json={"id": 55503, "node_id": "PRRC_55503", "in_reply_to_id": 55501},
                status=201,
            )

            origin_pr = PullRequest(
                id="206",
                title="Existing PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Alice",
            )
            # Origin root 100 was deleted; 101 is now top surviving comment, 102 replies to 101
            comments = [
                PullRequestComment(
                    id="101", body="First reply", author="Bob", parent_id=None
                ),
                PullRequestComment(
                    id="102", body="Second reply", author="Alice", parent_id="101"
                ),
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            payload = self._json_body(rsps.calls[-1])
            assert payload["in_reply_to"] == 55501

    def test_given_reply_to_general_or_fallback_issue_comment_when_reconciling_then_posts_reply_as_issue_comment(
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
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 36, "head": {"sha": "dest-sha-36"}},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/36/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/36/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/36/comments",
                json={"id": 6001, "node_id": "IC_6001"},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/36/comments",
                json={"id": 6002, "node_id": "IC_6002"},
                status=201,
            )

            origin_pr = PullRequest(
                id="207",
                title="General reply PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(id="g1", body="General root", author="Alice"),
                PullRequestComment(
                    id="g2", body="General reply", author="Bob", parent_id="g1"
                ),
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 2
            issue_posts = [
                c
                for c in rsps.calls
                if c.request.method == "POST"
                and c.request.url
                == "https://api.github.com/repos/my-org/my-repo/issues/36/comments"
            ]
            assert len(issue_posts) == 2

    def test_given_github_422_on_review_comment_creation_when_reconciling_then_falls_back_to_issue_comment_with_location_header(
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
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 37, "head": {"sha": "dest-sha-37"}},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/37/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/37/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/37/comments",
                json={"message": "Validation Failed"},
                status=422,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/37/comments",
                json={"id": 6010, "node_id": "IC_6010"},
                status=201,
            )

            origin_pr = PullRequest(
                id="208",
                title="422 PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="c422",
                    body="Outdated line",
                    author="Bob",
                    file_path="old.py",
                    start_line=10,
                    start_side="RIGHT",
                    line=12,
                    side="RIGHT",
                )
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.errors == []
            assert res.synced_pr_comments == 1
            fallback_body = self._json_body(rsps.calls[-1])["body"]
            assert "on `old.py` (lines 10-12)" in fallback_body

    def test_given_empty_head_sha_when_reconciling_inline_comment_then_falls_back_to_issue_comment(
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
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 38},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/38/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/38/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/issues/38/comments",
                json={"id": 6020, "node_id": "IC_6020"},
                status=201,
            )

            origin_pr = PullRequest(
                id="209",
                title="No SHA PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="c_nosha",
                    body="No sha inline",
                    author="Bob",
                    file_path="app.py",
                    line=4,
                    side="RIGHT",
                )
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            assert (
                rsps.calls[-1].request.url
                == "https://api.github.com/repos/my-org/my-repo/issues/38/comments"
            )

    def test_given_edited_existing_review_comment_when_reconciling_then_updates_via_pulls_comments_patch_endpoint(
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
                        "number": 39,
                        "title": "Edit PR",
                        "body": "> **Synced from origin** | Author: **Alice** | Original PR: #210\n\n<!-- gh-repo-sync:origin-pr-id=210 -->",
                        "head": {"ref": "feat/x", "sha": "dest-sha-39"},
                        "base": {"ref": "main"},
                        "state": "open",
                        "user": {"login": "bot"},
                    }
                ],
                status=200,
            )
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/39/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/39/comments?per_page=100",
                json=[
                    {
                        "id": 7001,
                        "node_id": "PRRC_7001",
                        "body": "> **Bob**\n\nOld text\n\n<!-- gh-repo-sync:origin-comment-id=c_edit -->",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "nodes": [],
                                    "pageInfo": {
                                        "hasNextPage": False,
                                        "endCursor": None,
                                    },
                                }
                            }
                        }
                    }
                },
                status=200,
            )
            rsps.add(
                responses.PATCH,
                "https://api.github.com/repos/my-org/my-repo/pulls/comments/7001",
                json={"id": 7001},
                status=200,
            )

            origin_pr = PullRequest(
                id="210",
                title="Edit PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="c_edit",
                    body="New text",
                    author="Bob",
                    file_path="app.py",
                    line=10,
                    side="RIGHT",
                )
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            assert rsps.calls[-1].request.method == "PATCH"
            assert (
                rsps.calls[-1].request.url
                == "https://api.github.com/repos/my-org/my-repo/pulls/comments/7001"
            )
            assert "New text" in self._json_body(rsps.calls[-1])["body"]

    def test_given_newly_created_resolved_review_comment_when_reconciling_then_fetches_review_threads_and_resolves_thread(
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
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 40, "head": {"sha": "dest-sha-40"}},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/40/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/40/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/40/comments",
                json={"id": 8001, "node_id": "PRRC_8001"},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "nodes": [
                                        {
                                            "id": "PRRT_8001",
                                            "isResolved": False,
                                            "comments": {
                                                "nodes": [
                                                    {
                                                        "id": "PRRC_8001",
                                                        "databaseId": 8001,
                                                    }
                                                ]
                                            },
                                        }
                                    ],
                                    "pageInfo": {
                                        "hasNextPage": False,
                                        "endCursor": None,
                                    },
                                }
                            }
                        }
                    }
                },
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {
                        "resolveReviewThread": {
                            "thread": {"id": "PRRT_8001", "isResolved": True}
                        }
                    }
                },
                status=200,
            )

            origin_pr = PullRequest(
                id="211",
                title="Resolved inline PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="c_res",
                    body="Already fixed",
                    author="Bob",
                    file_path="app.py",
                    line=10,
                    side="RIGHT",
                    is_resolved=True,
                    resolved_by="Alice",
                )
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            resolve_call = self._json_body(rsps.calls[-1])
            assert "resolveReviewThread" in resolve_call["query"]
            assert resolve_call["variables"] == {"threadId": "PRRT_8001"}

    def test_given_existing_review_thread_resolved_or_unresolved_on_origin_when_reconciling_then_syncs_thread_resolution_via_graphql(
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
                        "number": 41,
                        "title": "Toggle resolve PR",
                        "body": "> **Synced from origin** | Author: **Alice** | Original PR: #212\n\n<!-- gh-repo-sync:origin-pr-id=212 -->",
                        "head": {"ref": "feat/x", "sha": "dest-sha-41"},
                        "base": {"ref": "main"},
                        "state": "open",
                        "user": {"login": "bot"},
                    }
                ],
                status=200,
            )
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/41/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/41/comments?per_page=100",
                json=[
                    {
                        "id": 8101,
                        "node_id": "PRRC_8101",
                        "body": "> **Bob**\n\nReopened\n\n<!-- gh-repo-sync:origin-comment-id=c_unres -->",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "nodes": [
                                        {
                                            "id": "PRRT_8101",
                                            "isResolved": True,
                                            "comments": {
                                                "nodes": [
                                                    {
                                                        "id": "PRRC_8101",
                                                        "databaseId": 8101,
                                                    }
                                                ]
                                            },
                                        }
                                    ],
                                    "pageInfo": {
                                        "hasNextPage": False,
                                        "endCursor": None,
                                    },
                                }
                            }
                        }
                    }
                },
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {
                        "unresolveReviewThread": {
                            "thread": {"id": "PRRT_8101", "isResolved": False}
                        }
                    }
                },
                status=200,
            )

            origin_pr = PullRequest(
                id="212",
                title="Toggle resolve PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="c_unres",
                    body="Reopened",
                    author="Bob",
                    file_path="app.py",
                    line=10,
                    side="RIGHT",
                    is_resolved=False,
                )
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            unresolve_call = self._json_body(rsps.calls[-1])
            assert "unresolveReviewThread" in unresolve_call["query"]
            assert unresolve_call["variables"] == {"threadId": "PRRT_8101"}

    def test_given_resolved_root_thread_with_unresolved_reply_when_reconciling_then_does_not_unresolve_thread(
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
                        "number": 42,
                        "title": "Keep resolved PR",
                        "body": "> **Synced from origin** | Author: **Alice** | Original PR: #213\n\n<!-- gh-repo-sync:origin-pr-id=213 -->",
                        "head": {"ref": "feat/x", "sha": "dest-sha-42"},
                        "base": {"ref": "main"},
                        "state": "open",
                        "user": {"login": "bot"},
                    }
                ],
                status=200,
            )
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/42/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/42/comments?per_page=100",
                json=[
                    {
                        "id": 8201,
                        "node_id": "PRRC_8201",
                        "body": "> **Alice** | ✅ Resolved by Alice\n\nRoot\n\n<!-- gh-repo-sync:origin-comment-id=r1 -->",
                        "in_reply_to_id": None,
                    },
                    {
                        "id": 8202,
                        "node_id": "PRRC_8202",
                        "body": "> **Bob**\n\nReply\n\n<!-- gh-repo-sync:origin-comment-id=r2 -->",
                        "in_reply_to_id": 8201,
                    },
                ],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "nodes": [
                                        {
                                            "id": "PRRT_8201",
                                            "isResolved": True,
                                            "comments": {
                                                "nodes": [
                                                    {
                                                        "id": "PRRC_8201",
                                                        "databaseId": 8201,
                                                    },
                                                    {
                                                        "id": "PRRC_8202",
                                                        "databaseId": 8202,
                                                    },
                                                ]
                                            },
                                        }
                                    ],
                                    "pageInfo": {
                                        "hasNextPage": False,
                                        "endCursor": None,
                                    },
                                }
                            }
                        }
                    }
                },
                status=200,
            )

            origin_pr = PullRequest(
                id="213",
                title="Keep resolved PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="r1",
                    body="Root",
                    author="Alice",
                    file_path="app.py",
                    line=10,
                    side="RIGHT",
                    is_resolved=True,
                    resolved_by="Alice",
                ),
                PullRequestComment(
                    id="r2",
                    body="Reply",
                    author="Bob",
                    parent_id="r1",
                    is_resolved=False,
                ),
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 0
            assert not any(
                "unresolveReviewThread" in str(c.request.body or "")
                for c in rsps.calls
                if c.request.url == "https://api.github.com/graphql"
            )

    def test_given_legacy_issue_comment_with_origin_marker_when_reconciling_then_updates_in_place_without_duplicating_review_comment(
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
                        "number": 43,
                        "title": "Legacy PR",
                        "body": "> **Synced from origin** | Author: **Alice** | Original PR: #214\n\n<!-- gh-repo-sync:origin-pr-id=214 -->",
                        "head": {"ref": "feat/x", "sha": "dest-sha-43"},
                        "base": {"ref": "main"},
                        "state": "open",
                        "user": {"login": "bot"},
                    }
                ],
                status=200,
            )
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/43/comments?per_page=100",
                json=[
                    {
                        "id": 9001,
                        "node_id": "IC_9001",
                        "body": "> **Bob** | on `app.py` (line 10)\n\nOld legacy\n\n<!-- gh-repo-sync:origin-comment-id=leg1 -->",
                    }
                ],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={"data": {"nodes": [{"id": "IC_9001", "isMinimized": False}]}},
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/43/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.PATCH,
                "https://api.github.com/repos/my-org/my-repo/issues/comments/9001",
                json={"id": 9001},
                status=200,
            )

            origin_pr = PullRequest(
                id="214",
                title="Legacy PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="leg1",
                    body="Updated legacy",
                    author="Bob",
                    file_path="app.py",
                    line=10,
                    side="RIGHT",
                )
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.synced_pr_comments == 1
            assert rsps.calls[-1].request.method == "PATCH"
            assert (
                rsps.calls[-1].request.url
                == "https://api.github.com/repos/my-org/my-repo/issues/comments/9001"
            )
            assert "on `app.py` (line 10)" in self._json_body(rsps.calls[-1])["body"]

    def test_given_graphql_error_when_fetching_or_resolving_review_threads_then_logs_warning_without_failing_pr_sync(
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
            _mock_org_members_graphql(rsps, members=[])
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls",
                json={"number": 44, "head": {"sha": "dest-sha-44"}},
                status=201,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/issues/44/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.GET,
                "https://api.github.com/repos/my-org/my-repo/pulls/44/comments?per_page=100",
                json=[],
                status=200,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/repos/my-org/my-repo/pulls/44/comments",
                json={"id": 9101, "node_id": "PRRC_9101"},
                status=201,
            )
            rsps.add(
                responses.POST,
                "https://api.github.com/graphql",
                json={
                    "data": {"repository": None},
                    "errors": [{"message": "Forbidden"}],
                },
                status=200,
            )

            origin_pr = PullRequest(
                id="215",
                title="GraphQL err PR",
                description="",
                source_branch="feat/x",
                target_branch="main",
                author="Alice",
            )
            comments = [
                PullRequestComment(
                    id="c_gql_err",
                    body="Resolved note",
                    author="Bob",
                    file_path="app.py",
                    line=10,
                    side="RIGHT",
                    is_resolved=True,
                )
            ]
            res = self._make_importer().reconcile(
                [origin_pr], self._make_exporter(mocker, comments=comments)
            )
            assert res.errors == []
            assert res.synced_pr_comments == 1

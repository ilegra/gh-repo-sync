from typing import Any

import pytest
import responses
from pytest_mock import MockerFixture

from src.providers.bitbucket_cloud import BitbucketCloudProvider


@pytest.mark.parametrize(
    "repo_url,expected_parsed,expected_name",
    [
        (
            "https://bitbucket.org/my-workspace/my-repo",
            ("my-workspace", "my-repo"),
            "my-repo",
        ),
        (
            "https://bitbucket.org/my-workspace/my-repo.git",
            ("my-workspace", "my-repo"),
            "my-repo",
        ),
        (
            "https://someuser@bitbucket.org/my-workspace/my-repo.git",
            ("my-workspace", "my-repo"),
            "my-repo",
        ),
        (
            "https://bitbucket.org/my-workspace/my-repo/",
            ("my-workspace", "my-repo"),
            "my-repo",
        ),
        (
            "git@bitbucket.org:my-workspace/my-repo.git",
            ("my-workspace", "my-repo"),
            "my-repo",
        ),
    ],
)
def test_bitbucket_url_parsing_and_repo_name(
    repo_url: str,
    expected_parsed: tuple[str, str],
    expected_name: str,
) -> None:
    provider = BitbucketCloudProvider(repo_url=repo_url, token="bb-secret")
    assert provider._parse_bitbucket_url() == expected_parsed
    assert provider.get_repo_name() == expected_name


def test_bitbucket_authenticated_url_access_token() -> None:
    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-access-token",
    )
    assert (
        provider.get_authenticated_url()
        == "https://x-token-auth:bb-access-token@bitbucket.org/my-workspace/my-repo.git"
    )


def test_bitbucket_authenticated_url_app_password() -> None:
    provider = BitbucketCloudProvider(
        repo_url="https://someuser@bitbucket.org/my-workspace/my-repo.git",
        token="bb-app-password",
        username="my-bb-user",
    )
    assert (
        provider.get_authenticated_url()
        == "https://my-bb-user:bb-app-password@bitbucket.org/my-workspace/my-repo.git"
    )


def test_bitbucket_authenticated_url_from_ssh() -> None:
    provider = BitbucketCloudProvider(
        repo_url="git@bitbucket.org:my-workspace/my-repo.git",
        token="bb-access-token",
    )
    assert (
        provider.get_authenticated_url()
        == "https://x-token-auth:bb-access-token@bitbucket.org/my-workspace/my-repo.git"
    )


@responses.activate
def test_bitbucket_is_repo_disabled_archived_true() -> None:
    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
    )
    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(
        responses.GET,
        api_url,
        json={"slug": "my-repo", "is_archived": True},
        status=200,
    )

    assert provider.is_repo_disabled() is True
    assert responses.calls[0].request.headers["Authorization"] == "Bearer bb-token"


@responses.activate
def test_bitbucket_is_repo_disabled_read_only_true() -> None:
    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-app-pass",
        username="bb-user",
    )
    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(
        responses.GET,
        api_url,
        json={"slug": "my-repo", "is_read_only": True},
        status=200,
    )

    assert provider.is_repo_disabled() is True
    auth_header = responses.calls[0].request.headers["Authorization"]
    assert str(auth_header).startswith("Basic ")


@responses.activate
def test_bitbucket_is_repo_disabled_false() -> None:
    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
    )
    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(
        responses.GET,
        api_url,
        json={"slug": "my-repo", "is_archived": False, "is_read_only": False},
        status=200,
    )

    assert provider.is_repo_disabled() is False


@responses.activate
def test_bitbucket_api_retries_and_failure() -> None:
    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
    )
    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(responses.GET, api_url, status=500)

    assert provider.is_repo_disabled() is False


def test_bitbucket_get_remote_ref() -> None:
    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        remote_name="custom_origin",
    )
    assert provider.get_remote_ref("main") == "refs/remotes/custom_origin/main"
    assert (
        provider.get_remote_ref("feature/foo")
        == "refs/remotes/custom_origin/feature/foo"
    )


@responses.activate
def test_bitbucket_get_default_branch_name_from_api(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(
        responses.GET,
        api_url,
        json={"slug": "my-repo", "mainbranch": {"name": "develop"}},
        status=200,
    )

    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        git=mock_git,
        remote_name="origin_remote",
    )
    assert provider._get_default_branch_name() == "develop"
    mock_git.symbolic_ref.assert_not_called()


@responses.activate
def test_bitbucket_get_default_branch_name_with_symbolic_ref(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_git.symbolic_ref.return_value = mocker.MagicMock(
        success=True, stdout="origin_remote/main"
    )
    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(responses.GET, api_url, status=404)

    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        git=mock_git,
        remote_name="origin_remote",
    )
    assert provider._get_default_branch_name() == "main"


@responses.activate
def test_bitbucket_get_default_branch_name_fallback(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    mock_git.symbolic_ref.return_value = mocker.MagicMock(success=False, stdout="")
    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(responses.GET, api_url, status=404)

    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        git=mock_git,
    )
    assert provider._get_default_branch_name() == "main"


@responses.activate
def test_bitbucket_get_default_branch_name_without_git() -> None:
    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(responses.GET, api_url, status=404)

    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        git=None,
    )
    assert provider._get_default_branch_name() == "main"


@responses.activate
def test_bitbucket_get_branches_success(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="origin_remote\n")
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.for_each_ref.return_value = [
        "refs/remotes/origin_remote/HEAD",
        "refs/remotes/origin_remote/main",
        "refs/remotes/origin_remote/feature/login",
        "refs/remotes/origin_remote/-bad-branch",
    ]
    mock_git.check_ref_format.return_value = True

    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(
        responses.GET,
        api_url,
        json={"slug": "my-repo", "mainbranch": {"name": "main"}},
        status=200,
    )

    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        git=mock_git,
        remote_name="origin_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 2
    assert branches[0].name == "main"
    assert branches[0].remote_ref == "refs/remotes/origin_remote/main"
    assert branches[0].is_default is True
    assert branches[1].name == "feature/login"
    assert branches[1].remote_ref == "refs/remotes/origin_remote/feature/login"
    assert branches[1].is_default is False
    mock_git.fetch.assert_called_once_with("origin_remote", prune=True)


@responses.activate
def test_bitbucket_get_branches_adds_remote_if_missing(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="other_remote\n")
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.for_each_ref.return_value = ["refs/remotes/origin_remote/main"]
    mock_git.check_ref_format.return_value = True

    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(responses.GET, api_url, status=404)

    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        git=mock_git,
        remote_name="origin_remote",
    )
    branches = provider.get_branches()

    mock_git.remote_add.assert_called_once_with(
        "origin_remote", provider.get_authenticated_url()
    )
    assert len(branches) == 1
    assert branches[0].name == "main"


def test_bitbucket_get_branches_handles_disabled_repo(mocker: MockerFixture) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="origin_remote\n")
    mock_git.fetch.return_value = mocker.MagicMock(
        success=False,
        exit_code=1,
        stderr="fatal: repository is archived",
    )

    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        git=mock_git,
        remote_name="origin_remote",
    )
    assert provider.get_branches() == []


def test_bitbucket_get_branches_requires_git() -> None:
    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        git=None,
    )
    with pytest.raises(RuntimeError, match="Git client is not initialized"):
        provider.get_branches()


@responses.activate
def test_bitbucket_get_branches_defines_custom_default_branch(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="origin_remote\n")
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.symbolic_ref.return_value = mocker.MagicMock(
        success=True, stdout="origin_remote/develop"
    )
    mock_git.for_each_ref.return_value = [
        "refs/remotes/origin_remote/HEAD",
        "refs/remotes/origin_remote/main",
        "refs/remotes/origin_remote/develop",
        "refs/remotes/origin_remote/feature/foo",
    ]
    mock_git.check_ref_format.return_value = True

    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(responses.GET, api_url, status=404)

    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        git=mock_git,
        remote_name="origin_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 3
    branch_map = {b.name: b for b in branches}
    assert branch_map["develop"].is_default is True
    assert branch_map["main"].is_default is False
    assert branch_map["feature/foo"].is_default is False


@responses.activate
def test_bitbucket_get_branches_defines_default_branch_fallback_to_master(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="origin_remote\n")
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.symbolic_ref.return_value = mocker.MagicMock(success=False, stdout="")
    mock_git.for_each_ref.return_value = [
        "refs/remotes/origin_remote/HEAD",
        "refs/remotes/origin_remote/master",
        "refs/remotes/origin_remote/feature/foo",
    ]
    mock_git.check_ref_format.return_value = True

    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(responses.GET, api_url, status=404)

    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        git=mock_git,
        remote_name="origin_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 2
    branch_map = {b.name: b for b in branches}
    assert branch_map["master"].is_default is True
    assert branch_map["feature/foo"].is_default is False


@responses.activate
def test_bitbucket_get_branches_defines_default_branch_fallback_to_first_branch(
    mocker: MockerFixture,
) -> None:
    mock_git = mocker.MagicMock()
    mock_git.run.return_value = mocker.MagicMock(success=True, stdout="origin_remote\n")
    mock_git.fetch.return_value = mocker.MagicMock(success=True, exit_code=0)
    mock_git.symbolic_ref.return_value = mocker.MagicMock(success=False, stdout="")
    mock_git.for_each_ref.return_value = [
        "refs/remotes/origin_remote/HEAD",
        "refs/remotes/origin_remote/release/v1",
        "refs/remotes/origin_remote/feature/foo",
    ]
    mock_git.check_ref_format.return_value = True

    api_url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo"
    responses.add(responses.GET, api_url, status=404)

    provider = BitbucketCloudProvider(
        repo_url="https://bitbucket.org/my-workspace/my-repo",
        token="bb-token",
        git=mock_git,
        remote_name="origin_remote",
    )
    branches = provider.get_branches()

    assert len(branches) == 2
    assert branches[0].name == "release/v1"
    assert branches[0].is_default is True
    assert branches[1].name == "feature/foo"
    assert branches[1].is_default is False


class TestBitbucketCloudProvider:
    def test_given_valid_bitbucket_url_when_getting_pr_exporter_then_returns_bitbucket_pr_exporter(
        self,
    ) -> None:
        from src.providers.bitbucket_cloud import BitbucketCloudPrExporter

        provider = BitbucketCloudProvider(
            repo_url="https://bitbucket.org/my-workspace/my-repo",
            token="bb-token",
        )
        exporter = provider.get_pr_exporter()
        assert isinstance(exporter, BitbucketCloudPrExporter)
        assert provider.get_pr_exporter() is exporter

    def test_given_unparseable_bitbucket_url_when_getting_pr_exporter_then_returns_none(
        self,
    ) -> None:
        provider = BitbucketCloudProvider(
            repo_url="https://example.com/not-bitbucket",
            token="bb-token",
        )
        assert provider.get_pr_exporter() is None


class TestBitbucketCloudPrExporter:
    def _make_exporter(self) -> Any:
        provider = BitbucketCloudProvider(
            repo_url="https://bitbucket.org/my-workspace/my-repo",
            token="bb-token",
        )
        exporter = provider.get_pr_exporter()
        assert exporter is not None
        return exporter

    @responses.activate
    def test_given_open_prs_single_page_when_getting_open_pull_requests_then_returns_parsed_prs(
        self,
    ) -> None:
        url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests?state=OPEN&pagelen=50&fields=%2Bvalues.reviewers"
        responses.add(
            responses.GET,
            url,
            json={
                "values": [
                    {
                        "id": 42,
                        "title": "feat: add sync",
                        "description": "Adds PR sync",
                        "state": "OPEN",
                        "draft": True,
                        "author": {"display_name": "Alice"},
                        "source": {
                            "branch": {"name": "feat/sync"},
                            "repository": {"full_name": "my-workspace/my-repo"},
                        },
                        "destination": {
                            "branch": {"name": "main"},
                            "repository": {"full_name": "my-workspace/my-repo"},
                        },
                        "links": {
                            "html": {
                                "href": "https://bitbucket.org/my-workspace/my-repo/pull-requests/42"
                            }
                        },
                    }
                ]
            },
            status=200,
        )

        prs = self._make_exporter().get_open_pull_requests()
        assert len(prs) == 1
        assert prs[0].id == "42"
        assert prs[0].title == "feat: add sync"
        assert prs[0].description == "Adds PR sync"
        assert prs[0].source_branch == "feat/sync"
        assert prs[0].target_branch == "main"
        assert prs[0].author == "Alice"
        assert prs[0].is_draft is True
        assert prs[0].is_from_fork is False
        assert prs[0].state == "open"
        assert (
            prs[0].url == "https://bitbucket.org/my-workspace/my-repo/pull-requests/42"
        )

    @responses.activate
    def test_given_paginated_open_prs_when_getting_open_pull_requests_then_follows_next_links(
        self,
    ) -> None:
        page1 = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests?state=OPEN&pagelen=50&fields=%2Bvalues.reviewers"
        page2 = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests?state=OPEN&pagelen=50&page=2"
        responses.add(
            responses.GET,
            page1,
            json={
                "values": [
                    {
                        "id": 1,
                        "title": "PR 1",
                        "source": {"branch": {"name": "b1"}},
                        "destination": {"branch": {"name": "main"}},
                    }
                ],
                "next": page2,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            page2,
            json={
                "values": [
                    {
                        "id": 2,
                        "title": "PR 2",
                        "source": {"branch": {"name": "b2"}},
                        "destination": {"branch": {"name": "main"}},
                    }
                ]
            },
            status=200,
        )

        prs = self._make_exporter().get_open_pull_requests()
        assert [p.id for p in prs] == ["1", "2"]

    @responses.activate
    def test_given_fork_pr_when_getting_open_pull_requests_then_marks_is_from_fork_true(
        self,
    ) -> None:
        url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests?state=OPEN&pagelen=50&fields=%2Bvalues.reviewers"
        responses.add(
            responses.GET,
            url,
            json={
                "values": [
                    {
                        "id": 7,
                        "title": "Fork PR",
                        "source": {
                            "branch": {"name": "fork-branch"},
                            "repository": {"full_name": "other-user/my-repo"},
                        },
                        "destination": {
                            "branch": {"name": "main"},
                            "repository": {"full_name": "my-workspace/my-repo"},
                        },
                    }
                ]
            },
            status=200,
        )

        prs = self._make_exporter().get_open_pull_requests()
        assert len(prs) == 1
        assert prs[0].is_from_fork is True

    @responses.activate
    def test_given_pr_with_missing_optional_fields_when_getting_open_pull_requests_then_uses_safe_defaults(
        self,
    ) -> None:
        url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests?state=OPEN&pagelen=50&fields=%2Bvalues.reviewers"
        responses.add(
            responses.GET,
            url,
            json={"values": [{"id": 9}]},
            status=200,
        )

        prs = self._make_exporter().get_open_pull_requests()
        assert len(prs) == 1
        assert prs[0].id == "9"
        assert prs[0].title == ""
        assert prs[0].description == ""
        assert prs[0].author == "Unknown"
        assert prs[0].is_draft is False
        assert prs[0].is_from_fork is False

    @responses.activate
    def test_given_forbidden_api_response_when_getting_open_pull_requests_then_returns_empty_list(
        self,
    ) -> None:
        url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests?state=OPEN&pagelen=50&fields=%2Bvalues.reviewers"
        responses.add(responses.GET, url, status=403)
        assert self._make_exporter().get_open_pull_requests() == []

    @responses.activate
    def test_given_network_error_when_getting_open_pull_requests_then_returns_empty_list(
        self,
    ) -> None:
        import requests

        url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests?state=OPEN&pagelen=50&fields=%2Bvalues.reviewers"
        responses.add(responses.GET, url, body=requests.ConnectionError("timeout"))
        assert self._make_exporter().get_open_pull_requests() == []

    @responses.activate
    def test_given_completed_pr_when_getting_pull_request_then_returns_normalized_state(
        self,
    ) -> None:
        url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests/15"
        responses.add(
            responses.GET,
            url,
            json={
                "id": 15,
                "title": "Done PR",
                "state": "MERGED",
                "source": {"branch": {"name": "feat/a"}},
                "destination": {"branch": {"name": "main"}},
            },
            status=200,
        )
        pr = self._make_exporter().get_pull_request("15")
        assert pr is not None
        assert pr.state == "merged"

    @responses.activate
    def test_given_missing_pr_404_when_getting_pull_request_then_returns_none(
        self,
    ) -> None:
        url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests/999"
        responses.add(responses.GET, url, status=404)
        assert self._make_exporter().get_pull_request("999") is None

    @responses.activate
    def test_given_general_inline_and_resolved_comments_when_getting_pr_comments_then_returns_parsed_comments(
        self,
    ) -> None:
        url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests/10/comments?pagelen=100"
        responses.add(
            responses.GET,
            url,
            json={
                "values": [
                    {
                        "id": 101,
                        "content": {"raw": "General comment"},
                        "user": {"display_name": "Bob"},
                        "created_on": "2026-01-01T00:00:00Z",
                    },
                    {
                        "id": 102,
                        "content": {"raw": "Fix this line"},
                        "user": {"display_name": "Carol"},
                        "inline": {"path": "src/app.py", "to": 25},
                        "resolution": {"user": {"display_name": "Alice"}},
                    },
                ]
            },
            status=200,
        )

        comments = self._make_exporter().get_pull_request_comments("10")
        assert len(comments) == 2
        assert comments[0].id == "101"
        assert comments[0].file_path is None
        assert comments[0].is_resolved is False
        assert comments[1].id == "102"
        assert comments[1].file_path == "src/app.py"
        assert comments[1].line == 25
        assert comments[1].is_resolved is True
        assert comments[1].resolved_by == "Alice"

    @responses.activate
    def test_given_deleted_and_empty_comments_when_getting_pr_comments_then_skips_them(
        self,
    ) -> None:
        url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests/10/comments?pagelen=100"
        responses.add(
            responses.GET,
            url,
            json={
                "values": [
                    {"id": 1, "deleted": True, "content": {"raw": "gone"}},
                    {"id": 2, "deleted": False, "content": {"raw": "   "}},
                    {"id": 3, "deleted": False, "content": {"raw": "valid"}},
                ]
            },
            status=200,
        )

        comments = self._make_exporter().get_pull_request_comments("10")
        assert [c.id for c in comments] == ["3"]

    @responses.activate
    def test_given_paginated_pr_comments_when_getting_pr_comments_then_follows_next_links(
        self,
    ) -> None:
        p1 = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests/10/comments?pagelen=100"
        p2 = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests/10/comments?pagelen=100&page=2"
        responses.add(
            responses.GET,
            p1,
            json={
                "values": [{"id": 1, "content": {"raw": "c1"}}],
                "next": p2,
            },
            status=200,
        )
        responses.add(
            responses.GET,
            p2,
            json={"values": [{"id": 2, "content": {"raw": "c2"}}]},
            status=200,
        )

        comments = self._make_exporter().get_pull_request_comments("10")
        assert [c.id for c in comments] == ["1", "2"]

    @responses.activate
    def test_given_open_pr_with_reviewers_when_getting_open_pull_requests_then_parses_display_names_and_nickname_fallback(
        self,
    ) -> None:
        url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests?state=OPEN&pagelen=50&fields=%2Bvalues.reviewers"
        responses.add(
            responses.GET,
            url,
            json={
                "values": [
                    {
                        "id": 50,
                        "title": "PR with reviewers",
                        "author": {"display_name": "Jane Doe"},
                        "reviewers": [
                            {"display_name": "Alice Smith", "nickname": "asmith"},
                            {"nickname": "bwayne"},
                            {"display_name": "   "},
                        ],
                        "source": {"branch": {"name": "feat/rev"}},
                        "destination": {"branch": {"name": "main"}},
                    }
                ]
            },
            status=200,
        )

        prs = self._make_exporter().get_open_pull_requests()
        assert len(prs) == 1
        assert prs[0].reviewers == ["Alice Smith", "bwayne"]

    @responses.activate
    def test_given_open_pr_with_missing_or_malformed_reviewers_when_getting_open_pull_requests_then_returns_empty_reviewers_list(
        self,
    ) -> None:
        url = "https://api.bitbucket.org/2.0/repositories/my-workspace/my-repo/pullrequests?state=OPEN&pagelen=50&fields=%2Bvalues.reviewers"
        responses.add(
            responses.GET,
            url,
            json={
                "values": [
                    {
                        "id": 51,
                        "title": "No reviewers",
                        "source": {"branch": {"name": "feat/a"}},
                        "destination": {"branch": {"name": "main"}},
                    },
                    {
                        "id": 52,
                        "title": "Malformed reviewers",
                        "reviewers": ["not-a-dict", None, {}],
                        "source": {"branch": {"name": "feat/b"}},
                        "destination": {"branch": {"name": "main"}},
                    },
                ]
            },
            status=200,
        )

        prs = self._make_exporter().get_open_pull_requests()
        assert len(prs) == 2
        assert prs[0].reviewers == []
        assert prs[1].reviewers == []

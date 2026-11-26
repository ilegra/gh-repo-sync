import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

import requests
import structlog
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from src.git.client import Git
from src.providers.base import (
    Branch,
    DestinationProvider,
    PrExporter,
    PrImporter,
    PrSyncResult,
    PullRequest,
    PullRequestComment,
    validate_branch_name,
)

logger = structlog.get_logger(__name__)

_ORIGIN_PR_ID_PATTERN = re.compile(r"<!--\s*gh-repo-sync:origin-pr-id=([^\s]+)\s*-->")
_ORIGIN_COMMENT_ID_PATTERN = re.compile(
    r"<!--\s*gh-repo-sync:origin-comment-id=([^\s]+)\s*-->"
)
_NEXT_LINK_PATTERN = re.compile(r'<([^>]+)>;\s*rel="next"')

_ORG_MEMBERS_QUERY = """
query($org: String!, $cursor: String) {
  organization(login: $org) {
    membersWithRole(first: 100, after: $cursor) {
      nodes {
        login
        name
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""

_REVIEW_THREADS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        nodes {
          id
          isResolved
          comments(first: 100) {
            nodes {
              id
              databaseId
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
"""

_RESOLVE_REVIEW_THREAD_MUTATION = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread {
      id
      isResolved
    }
  }
}
"""

_UNRESOLVE_REVIEW_THREAD_MUTATION = """
mutation($threadId: ID!) {
  unresolveReviewThread(input: {threadId: $threadId}) {
    thread {
      id
      isResolved
    }
  }
}
"""


@dataclass
class _GitHubTrackedComment:
    comment_id: str
    body: str
    node_id: str | None = None
    is_review_comment: bool = False
    is_resolved: bool = False
    thread_id: str | None = None
    in_reply_to_id: str | None = None


class GitHubUserResolver:
    """Resolves origin display names to GitHub logins via org members and overrides."""

    def __init__(
        self,
        org: str,
        graphql_url: str,
        session: requests.Session,
        headers: dict[str, str],
        explicit_mapping: dict[str, str] | None = None,
    ):
        """
        Initializes the GitHub user resolver.

        Args:
            org: Destination GitHub organization (or user) login.
            graphql_url: GitHub GraphQL API endpoint URL.
            session: Configured requests.Session instance.
            headers: HTTP authentication and API headers.
            explicit_mapping: Optional explicit origin display name to GitHub login
                mapping that takes precedence over organization member lookup.
        """
        self._org = org
        self._graphql_url = graphql_url
        self._session = session
        self._headers = headers
        self._explicit_map: dict[str, str] = {}
        for origin_name, gh_login in (explicit_mapping or {}).items():
            norm_key = self._normalize_name(origin_name)
            clean_login = gh_login.strip().lstrip("@")
            if norm_key and clean_login:
                self._explicit_map[norm_key] = clean_login

        self._loaded = False
        self._org_name_to_login: dict[str, str] = {}

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.lower().split())

    def _load_org_members(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        ambiguous_names: set[str] = set()
        cursor: str | None = None
        try:
            while True:
                response = self._session.post(
                    self._graphql_url,
                    headers=self._headers,
                    json={
                        "query": _ORG_MEMBERS_QUERY,
                        "variables": {"org": self._org, "cursor": cursor},
                    },
                    timeout=15,
                )
                if response.status_code != 200:
                    logger.warning(
                        "Failed to fetch GitHub organization members via GraphQL; "
                        "falling back to plain-text user attribution",
                        org=self._org,
                        status_code=response.status_code,
                    )
                    return

                payload: dict[str, Any] = response.json()
                org_data = (payload.get("data") or {}).get("organization")
                if not isinstance(org_data, dict):
                    errors = payload.get("errors")
                    logger.warning(
                        "Unable to load GitHub organization members "
                        "(ensure 'Organization -> Members: Read' permission is granted "
                        "and destination owner is an organization)",
                        org=self._org,
                        errors=errors,
                    )
                    return

                members_conn = org_data.get("membersWithRole") or {}
                nodes = members_conn.get("nodes") or []
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    login = node.get("login")
                    name = node.get("name")
                    if not isinstance(login, str) or not login.strip():
                        continue
                    if not isinstance(name, str) or not name.strip():
                        continue

                    norm_name = self._normalize_name(name)
                    clean_login = login.strip()
                    if norm_name in ambiguous_names:
                        continue
                    existing = self._org_name_to_login.get(norm_name)
                    if existing is not None and existing.lower() != clean_login.lower():
                        del self._org_name_to_login[norm_name]
                        ambiguous_names.add(norm_name)
                        logger.debug(
                            "Ambiguous GitHub org member display name; "
                            "skipping automatic resolution",
                            org=self._org,
                            display_name=name,
                        )
                    else:
                        self._org_name_to_login[norm_name] = clean_login

                page_info = members_conn.get("pageInfo") or {}
                has_next = bool(page_info.get("hasNextPage", False))
                end_cursor = page_info.get("endCursor")
                if has_next and isinstance(end_cursor, str) and end_cursor:
                    cursor = end_cursor
                else:
                    break
        except Exception as e:
            logger.warning(
                "Failed to query GitHub organization members; "
                "falling back to plain-text user attribution",
                org=self._org,
                error=str(e),
            )

    def resolve(self, display_name: str) -> str | None:
        """
        Resolves an origin user display name to a GitHub login (without '@').

        Checks explicit mappings first, then falls back to unique destination
        organization member display-name matching. Returns None if unresolved
        or ambiguous.

        Args:
            display_name: Origin platform user display name.

        Returns:
            str | None: Resolved GitHub login without '@', or None if unresolved.
        """
        norm = self._normalize_name(display_name)
        if not norm:
            return None

        explicit = self._explicit_map.get(norm)
        if explicit is not None:
            return explicit

        self._load_org_members()
        return self._org_name_to_login.get(norm)


class GitHubPrImporter(PrImporter):
    """Pull request importer implementation for GitHub (github.com & Enterprise)."""

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str,
        host: str = "github.com",
        session: requests.Session | None = None,
        api_base_url: str | None = None,
        graphql_url: str | None = None,
    ):
        """
        Initializes the GitHub PR importer.

        Args:
            owner: GitHub repository owner or organization.
            repo: GitHub repository name.
            token: GitHub authentication token.
            host: GitHub hostname (defaults to 'github.com').
            session: Optional requests.Session instance.
            api_base_url: Optional REST API base URL override.
            graphql_url: Optional GraphQL endpoint URL override.
        """
        self.owner = owner
        self.repo = repo
        self.host = host
        self._token = token
        self._session = session or self._create_session()

        if api_base_url:
            self._api_base = api_base_url.rstrip("/")
            self._graphql_url = (
                graphql_url.rstrip("/") if graphql_url else f"{self._api_base}/graphql"
            )
        elif host.lower() == "github.com":
            self._api_base = "https://api.github.com"
            self._graphql_url = graphql_url or "https://api.github.com/graphql"
        else:
            self._api_base = f"https://{host}/api/v3"
            self._graphql_url = graphql_url or f"https://{host}/api/graphql"

    @staticmethod
    def _create_session() -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo_api_url(self) -> str:
        owner_q = urllib.parse.quote(self.owner, safe="")
        repo_q = urllib.parse.quote(self.repo, safe="")
        return f"{self._api_base}/repos/{owner_q}/{repo_q}"

    @staticmethod
    def _next_link(headers: Any) -> str | None:
        link_header = headers.get("Link") or headers.get("link") or ""
        match = _NEXT_LINK_PATTERN.search(str(link_header))
        return match.group(1) if match else None

    @staticmethod
    def _extract_origin_pr_id(body: str) -> str | None:
        match = _ORIGIN_PR_ID_PATTERN.search(body or "")
        return match.group(1) if match else None

    @staticmethod
    def _extract_origin_comment_id(body: str) -> str | None:
        match = _ORIGIN_COMMENT_ID_PATTERN.search(body or "")
        return match.group(1) if match else None

    @staticmethod
    def _format_user_mention(
        display_name: str, resolver: GitHubUserResolver | None = None
    ) -> str:
        resolved = resolver.resolve(display_name) if resolver else None
        return f"@{resolved}" if resolved else f"**{display_name}**"

    @staticmethod
    def _extract_user_logins(raw_users: Any) -> list[str]:
        if not isinstance(raw_users, list):
            return []
        return [
            str(u["login"]) for u in raw_users if isinstance(u, dict) and u.get("login")
        ]

    @classmethod
    def _format_pr_body(
        cls, pr: PullRequest, resolver: GitHubUserResolver | None = None
    ) -> str:
        origin_ref = f"[#{pr.id}]({pr.url})" if pr.url else f"#{pr.id}"
        author_display = cls._format_user_mention(pr.author, resolver)
        header = (
            f"> **Synced from origin** | Author: {author_display} | "
            f"Original PR: {origin_ref}"
        )
        parts = [header]
        if pr.description.strip():
            parts.append(pr.description.strip())
        parts.append(f"<!-- gh-repo-sync:origin-pr-id={pr.id} -->")
        return "\n\n".join(parts)

    @classmethod
    def _format_comment_body(
        cls,
        comment: PullRequestComment,
        resolver: GitHubUserResolver | None = None,
        include_location: bool = True,
    ) -> str:
        meta = [cls._format_user_mention(comment.author, resolver)]
        if include_location and comment.file_path:
            if comment.start_line is not None and comment.line is not None:
                loc = (
                    f"`{comment.file_path}` (lines {comment.start_line}-{comment.line})"
                )
            elif comment.line is not None:
                loc = f"`{comment.file_path}` (line {comment.line})"
            else:
                loc = f"`{comment.file_path}`"
            meta.append(f"on {loc}")
        if comment.is_resolved:
            resolved_tag = (
                f"✅ Resolved by {comment.resolved_by}"
                if comment.resolved_by
                else "✅ Resolved"
            )
            meta.append(resolved_tag)

        header = "> " + " | ".join(meta)
        return (
            f"{header}\n\n{comment.body.strip()}\n\n"
            f"<!-- gh-repo-sync:origin-comment-id={comment.id} -->"
        )

    def _list_open_pull_requests(self) -> list[PullRequest]:
        url: str | None = f"{self._repo_api_url()}/pulls?state=open&per_page=100"
        prs: list[PullRequest] = []

        while url:
            response = self._session.get(url, headers=self._headers(), timeout=15)
            response.raise_for_status()
            items = response.json()
            for item in items:
                if not isinstance(item, dict):
                    continue
                head_obj = item.get("head") or {}
                prs.append(
                    PullRequest(
                        id=str(item.get("number", "")),
                        number=int(item["number"]) if "number" in item else None,
                        title=str(item.get("title") or ""),
                        description=str(item.get("body") or ""),
                        source_branch=str(head_obj.get("ref") or ""),
                        target_branch=str((item.get("base") or {}).get("ref") or ""),
                        author=str((item.get("user") or {}).get("login") or ""),
                        state=str(item.get("state") or "open").lower(),
                        is_draft=bool(item.get("draft", False)),
                        url=str(item.get("html_url") or ""),
                        reviewers=self._extract_user_logins(
                            item.get("requested_reviewers")
                        ),
                        assignees=self._extract_user_logins(item.get("assignees")),
                        head_sha=str(head_obj.get("sha") or ""),
                    )
                )
            url = self._next_link(response.headers)

        return prs

    def _create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool,
    ) -> tuple[int, str] | None:
        url = f"{self._repo_api_url()}/pulls"
        payload: dict[str, Any] = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        }
        response = self._session.post(
            url, headers=self._headers(), json=payload, timeout=15
        )
        if response.status_code == 422:
            logger.warning(
                "Skipping PR creation due to GitHub 422 validation error",
                head=head,
                base=base,
                body=response.text[:200],
            )
            return None
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        head_sha = str((data.get("head") or {}).get("sha") or "")
        return int(data["number"]), head_sha

    def _update_pull_request(
        self, pr_number: int, title: str, body: str, base: str
    ) -> None:
        url = f"{self._repo_api_url()}/pulls/{pr_number}"
        payload = {"title": title, "body": body, "base": base}
        response = self._session.patch(
            url, headers=self._headers(), json=payload, timeout=15
        )
        response.raise_for_status()

    def _close_pull_request(self, pr_number: int) -> None:
        url = f"{self._repo_api_url()}/pulls/{pr_number}"
        response = self._session.patch(
            url, headers=self._headers(), json={"state": "closed"}, timeout=15
        )
        response.raise_for_status()

    def _add_assignees(self, pr_number: int, assignees: list[str]) -> bool:
        if not assignees:
            return False
        url = f"{self._repo_api_url()}/issues/{pr_number}/assignees"
        response = self._session.post(
            url, headers=self._headers(), json={"assignees": assignees}, timeout=15
        )
        if response.status_code in (403, 422):
            logger.warning(
                "Skipping PR assignees update due to GitHub API error",
                pr_number=pr_number,
                assignees=assignees,
                status_code=response.status_code,
                body=response.text[:200],
            )
            return False
        response.raise_for_status()
        return True

    def _list_pr_review_authors(self, pr_number: int) -> set[str]:
        url: str | None = (
            f"{self._repo_api_url()}/pulls/{pr_number}/reviews?per_page=100"
        )
        authors: set[str] = set()
        try:
            while url:
                response = self._session.get(url, headers=self._headers(), timeout=15)
                if response.status_code != 200:
                    return authors
                items = response.json()
                if isinstance(items, list):
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        login = (item.get("user") or {}).get("login")
                        if isinstance(login, str) and login.strip():
                            authors.add(login.strip().lower())
                url = self._next_link(response.headers)
        except Exception as e:
            logger.warning(
                "Failed to list existing PR reviews",
                pr_number=pr_number,
                error=str(e),
            )
        return authors

    def _request_reviewers(self, pr_number: int, reviewers: list[str]) -> bool:
        if not reviewers:
            return False
        url = f"{self._repo_api_url()}/pulls/{pr_number}/requested_reviewers"
        response = self._session.post(
            url, headers=self._headers(), json={"reviewers": reviewers}, timeout=15
        )
        if response.status_code == 422:
            if len(reviewers) > 1:
                any_added = False
                for reviewer in reviewers:
                    if self._request_reviewers(pr_number, [reviewer]):
                        any_added = True
                return any_added
            logger.warning(
                "Skipping requested reviewer due to GitHub 422 validation error",
                pr_number=pr_number,
                reviewers=reviewers,
                body=response.text[:200],
            )
            return False
        if response.status_code == 403:
            logger.warning(
                "Skipping requested reviewers due to GitHub 403 permission error",
                pr_number=pr_number,
                reviewers=reviewers,
            )
            return False
        response.raise_for_status()
        return True

    def _remove_requested_reviewers(self, pr_number: int, reviewers: list[str]) -> bool:
        if not reviewers:
            return False
        url = f"{self._repo_api_url()}/pulls/{pr_number}/requested_reviewers"
        response = self._session.delete(
            url, headers=self._headers(), json={"reviewers": reviewers}, timeout=15
        )
        if response.status_code in (403, 404, 422):
            logger.warning(
                "Skipping removal of requested reviewers due to GitHub API error",
                pr_number=pr_number,
                reviewers=reviewers,
                status_code=response.status_code,
            )
            return False
        response.raise_for_status()
        return True

    def _reconcile_pr_users(
        self,
        pr_number: int,
        origin_pr: PullRequest,
        existing_gh_pr: PullRequest | None,
        resolver: GitHubUserResolver,
    ) -> bool:
        changed = False

        author_login = resolver.resolve(origin_pr.author)
        existing_assignees = {
            a.lower() for a in (existing_gh_pr.assignees if existing_gh_pr else [])
        }
        if author_login and author_login.lower() not in existing_assignees:
            if self._add_assignees(pr_number, [author_login]):
                changed = True

        desired_by_lower: dict[str, str] = {}
        for reviewer_name in origin_pr.reviewers:
            login = resolver.resolve(reviewer_name)
            if login:
                desired_by_lower.setdefault(login.lower(), login)

        desired_reviewers = list(desired_by_lower.values())
        if existing_gh_pr is None:
            if desired_reviewers and self._request_reviewers(
                pr_number, desired_reviewers
            ):
                changed = True
            return changed

        existing_requested = existing_gh_pr.reviewers
        existing_requested_lower = {r.lower() for r in existing_requested}

        to_add = [
            login
            for login_lower, login in desired_by_lower.items()
            if login_lower not in existing_requested_lower
        ]
        to_remove = [r for r in existing_requested if r.lower() not in desired_by_lower]

        if to_add:
            already_reviewed = self._list_pr_review_authors(pr_number)
            to_add = [r for r in to_add if r.lower() not in already_reviewed]
            if to_add and self._request_reviewers(pr_number, to_add):
                changed = True

        if to_remove and self._remove_requested_reviewers(pr_number, to_remove):
            changed = True

        return changed

    def _fetch_comment_minimized_states(self, node_ids: list[str]) -> dict[str, bool]:
        if not node_ids:
            return {}
        query = """
        query($ids: [ID!]!) {
          nodes(ids: $ids) {
            ... on IssueComment {
              id
              isMinimized
            }
          }
        }
        """
        try:
            response = self._session.post(
                self._graphql_url,
                headers=self._headers(),
                json={"query": query, "variables": {"ids": node_ids}},
                timeout=15,
            )
            if response.status_code != 200:
                return {}
            data = response.json()
            nodes = (data.get("data") or {}).get("nodes") or []
            states: dict[str, bool] = {}
            for node in nodes:
                if isinstance(node, dict) and node.get("id"):
                    states[str(node["id"])] = bool(node.get("isMinimized", False))
            return states
        except Exception as e:
            logger.warning(
                "Failed to query comment minimized states via GraphQL", error=str(e)
            )
            return {}

    def _list_pull_request_comments(
        self, pr_number: int
    ) -> list[_GitHubTrackedComment]:
        url: str | None = (
            f"{self._repo_api_url()}/issues/{pr_number}/comments?per_page=100"
        )
        comments: list[_GitHubTrackedComment] = []

        while url:
            response = self._session.get(url, headers=self._headers(), timeout=15)
            response.raise_for_status()
            items = response.json()
            for item in items:
                if not isinstance(item, dict):
                    continue
                comments.append(
                    _GitHubTrackedComment(
                        comment_id=str(item.get("id", "")),
                        body=str(item.get("body") or ""),
                        node_id=str(item["node_id"]) if item.get("node_id") else None,
                        is_review_comment=False,
                    )
                )
            url = self._next_link(response.headers)

        node_ids = [c.node_id for c in comments if c.node_id]
        minimized_map = self._fetch_comment_minimized_states(node_ids)
        for comment in comments:
            if comment.node_id and comment.node_id in minimized_map:
                comment.is_resolved = minimized_map[comment.node_id]

        return comments

    def _list_pull_request_review_comments(
        self, pr_number: int
    ) -> list[_GitHubTrackedComment]:
        url: str | None = (
            f"{self._repo_api_url()}/pulls/{pr_number}/comments?per_page=100"
        )
        comments: list[_GitHubTrackedComment] = []

        while url:
            response = self._session.get(url, headers=self._headers(), timeout=15)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            items = response.json()
            for item in items:
                if not isinstance(item, dict):
                    continue
                in_reply_to = item.get("in_reply_to_id")
                comments.append(
                    _GitHubTrackedComment(
                        comment_id=str(item.get("id", "")),
                        body=str(item.get("body") or ""),
                        node_id=str(item["node_id"]) if item.get("node_id") else None,
                        is_review_comment=True,
                        in_reply_to_id=(
                            str(in_reply_to) if in_reply_to is not None else None
                        ),
                    )
                )
            url = self._next_link(response.headers)

        return comments

    def _fetch_review_threads(self, pr_number: int) -> dict[str, tuple[str, bool]]:
        thread_by_comment: dict[str, tuple[str, bool]] = {}
        cursor: str | None = None
        try:
            while True:
                response = self._session.post(
                    self._graphql_url,
                    headers=self._headers(),
                    json={
                        "query": _REVIEW_THREADS_QUERY,
                        "variables": {
                            "owner": self.owner,
                            "repo": self.repo,
                            "number": pr_number,
                            "cursor": cursor,
                        },
                    },
                    timeout=15,
                )
                if response.status_code != 200:
                    logger.warning(
                        "Failed to fetch PR review threads via GraphQL",
                        pr_number=pr_number,
                        status_code=response.status_code,
                    )
                    return thread_by_comment

                payload: dict[str, Any] = response.json()
                if payload.get("errors"):
                    logger.warning(
                        "GraphQL returned errors while fetching PR review threads",
                        pr_number=pr_number,
                        errors=payload.get("errors"),
                    )
                pr_data = (
                    (payload.get("data") or {}).get("repository", {}).get("pullRequest")
                )
                if not isinstance(pr_data, dict):
                    return thread_by_comment

                threads_conn = pr_data.get("reviewThreads") or {}
                for thread in threads_conn.get("nodes") or []:
                    if not isinstance(thread, dict) or not thread.get("id"):
                        continue
                    thread_id = str(thread["id"])
                    is_resolved = bool(thread.get("isResolved", False))
                    comments_nodes = (thread.get("comments") or {}).get("nodes") or []
                    for c_node in comments_nodes:
                        if not isinstance(c_node, dict):
                            continue
                        if c_node.get("id"):
                            thread_by_comment[str(c_node["id"])] = (
                                thread_id,
                                is_resolved,
                            )
                        if c_node.get("databaseId") is not None:
                            thread_by_comment[str(c_node["databaseId"])] = (
                                thread_id,
                                is_resolved,
                            )

                page_info = threads_conn.get("pageInfo") or {}
                has_next = bool(page_info.get("hasNextPage", False))
                end_cursor = page_info.get("endCursor")
                if has_next and isinstance(end_cursor, str) and end_cursor:
                    cursor = end_cursor
                else:
                    break
        except Exception as e:
            logger.warning(
                "Failed to query PR review threads via GraphQL",
                pr_number=pr_number,
                error=str(e),
            )
        return thread_by_comment

    def _list_tracked_comments(
        self, pr_number: int
    ) -> dict[str, _GitHubTrackedComment]:
        tracked: dict[str, _GitHubTrackedComment] = {}

        for gh_comment in self._list_pull_request_comments(pr_number):
            marker_id = self._extract_origin_comment_id(gh_comment.body)
            if marker_id:
                tracked[marker_id] = gh_comment

        review_comments = self._list_pull_request_review_comments(pr_number)
        if review_comments:
            thread_map = self._fetch_review_threads(pr_number)
            for review_comment in review_comments:
                thread_info = (
                    thread_map.get(review_comment.node_id)
                    if review_comment.node_id
                    else None
                ) or thread_map.get(review_comment.comment_id)
                if thread_info is not None:
                    review_comment.thread_id, review_comment.is_resolved = thread_info
                marker_id = self._extract_origin_comment_id(review_comment.body)
                if marker_id:
                    tracked[marker_id] = review_comment

        return tracked

    def _create_pull_request_comment(
        self, pr_number: int, body: str
    ) -> _GitHubTrackedComment:
        url = f"{self._repo_api_url()}/issues/{pr_number}/comments"
        response = self._session.post(
            url, headers=self._headers(), json={"body": body}, timeout=15
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return _GitHubTrackedComment(
            comment_id=str(data.get("id", "")),
            body=body,
            node_id=str(data["node_id"]) if data.get("node_id") else None,
            is_review_comment=False,
        )

    def _create_pull_request_review_comment(
        self,
        pr_number: int,
        body: str,
        head_sha: str,
        comment: PullRequestComment,
        in_reply_to: str | None = None,
    ) -> _GitHubTrackedComment | None:
        url = f"{self._repo_api_url()}/pulls/{pr_number}/comments"
        payload: dict[str, Any]
        if in_reply_to is not None:
            try:
                reply_id = int(in_reply_to)
            except ValueError:
                return None
            payload = {"body": body, "in_reply_to": reply_id}
        else:
            if not head_sha or not comment.file_path:
                return None
            clean_path = comment.file_path.lstrip("/")
            payload = {
                "body": body,
                "commit_id": head_sha,
                "path": clean_path,
            }
            if comment.line is None:
                payload["subject_type"] = "file"
            else:
                side = comment.side or "RIGHT"
                payload["line"] = comment.line
                payload["side"] = side
                if comment.start_line is not None:
                    payload["start_line"] = comment.start_line
                    payload["start_side"] = comment.start_side or side

        response = self._session.post(
            url, headers=self._headers(), json=payload, timeout=15
        )
        if response.status_code == 422:
            logger.warning(
                "Falling back to issue comment due to GitHub 422 on review comment",
                pr_number=pr_number,
                origin_comment_id=comment.id,
                file_path=comment.file_path,
                line=comment.line,
                in_reply_to=in_reply_to,
                body=response.text[:200],
            )
            return None
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        resp_in_reply_to = data.get("in_reply_to_id")
        return _GitHubTrackedComment(
            comment_id=str(data.get("id", "")),
            body=body,
            node_id=str(data["node_id"]) if data.get("node_id") else None,
            is_review_comment=True,
            in_reply_to_id=(
                str(resp_in_reply_to) if resp_in_reply_to is not None else in_reply_to
            ),
        )

    def _update_pull_request_comment(self, comment_id: str, body: str) -> None:
        url = f"{self._repo_api_url()}/issues/comments/{comment_id}"
        response = self._session.patch(
            url, headers=self._headers(), json={"body": body}, timeout=15
        )
        response.raise_for_status()

    def _update_pull_request_review_comment(self, comment_id: str, body: str) -> None:
        url = f"{self._repo_api_url()}/pulls/comments/{comment_id}"
        response = self._session.patch(
            url, headers=self._headers(), json={"body": body}, timeout=15
        )
        response.raise_for_status()

    def _resolve_pull_request_comment(self, comment_node_id: str) -> None:
        mutation = """
        mutation($id: ID!) {
          minimizeComment(input: {subjectId: $id, classifier: RESOLVED}) {
            minimizedComment {
              isMinimized
            }
          }
        }
        """
        response = self._session.post(
            self._graphql_url,
            headers=self._headers(),
            json={"query": mutation, "variables": {"id": comment_node_id}},
            timeout=15,
        )
        response.raise_for_status()

    def _unresolve_pull_request_comment(self, comment_node_id: str) -> None:
        mutation = """
        mutation($id: ID!) {
          unminimizeComment(input: {subjectId: $id}) {
            unminimizedComment {
              isMinimized
            }
          }
        }
        """
        response = self._session.post(
            self._graphql_url,
            headers=self._headers(),
            json={"query": mutation, "variables": {"id": comment_node_id}},
            timeout=15,
        )
        response.raise_for_status()

    def _resolve_review_thread(self, thread_id: str) -> None:
        try:
            response = self._session.post(
                self._graphql_url,
                headers=self._headers(),
                json={
                    "query": _RESOLVE_REVIEW_THREAD_MUTATION,
                    "variables": {"threadId": thread_id},
                },
                timeout=15,
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            if payload.get("errors"):
                logger.warning(
                    "GraphQL returned errors while resolving review thread",
                    thread_id=thread_id,
                    errors=payload.get("errors"),
                )
        except Exception as e:
            logger.warning(
                "Failed to resolve PR review thread via GraphQL",
                thread_id=thread_id,
                error=str(e),
            )

    def _unresolve_review_thread(self, thread_id: str) -> None:
        try:
            response = self._session.post(
                self._graphql_url,
                headers=self._headers(),
                json={
                    "query": _UNRESOLVE_REVIEW_THREAD_MUTATION,
                    "variables": {"threadId": thread_id},
                },
                timeout=15,
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            if payload.get("errors"):
                logger.warning(
                    "GraphQL returned errors while unresolving review thread",
                    thread_id=thread_id,
                    errors=payload.get("errors"),
                )
        except Exception as e:
            logger.warning(
                "Failed to unresolve PR review thread via GraphQL",
                thread_id=thread_id,
                error=str(e),
            )

    @staticmethod
    def _sort_comments_parents_first(
        comments: list[PullRequestComment],
    ) -> list[PullRequestComment]:
        by_id = {c.id: c for c in comments}
        ordered: list[PullRequestComment] = []
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(comment: PullRequestComment) -> None:
            if comment.id in visited or comment.id in visiting:
                return
            visiting.add(comment.id)
            if comment.parent_id and comment.parent_id in by_id:
                visit(by_id[comment.parent_id])
            visiting.remove(comment.id)
            visited.add(comment.id)
            ordered.append(comment)

        for item in comments:
            visit(item)
        return ordered

    @staticmethod
    def _resolve_root_origin_id(
        comment: PullRequestComment,
        comments_by_id: dict[str, PullRequestComment],
    ) -> str | None:
        if not comment.parent_id:
            return None
        visited: set[str] = {comment.id}
        curr_id: str = comment.parent_id
        while curr_id not in visited:
            visited.add(curr_id)
            parent = comments_by_id.get(curr_id)
            if parent is None or not parent.parent_id:
                return curr_id
            curr_id = parent.parent_id
        return comment.parent_id

    def _sync_pr_comments(
        self,
        pr_number: int,
        origin_pr_id: str,
        pr_exporter: PrExporter,
        result: PrSyncResult,
        resolver: GitHubUserResolver | None = None,
        head_sha: str = "",
    ) -> None:
        origin_comments = pr_exporter.get_pull_request_comments(origin_pr_id)
        if not origin_comments:
            return

        tracked_comments = self._list_tracked_comments(pr_number)
        ordered_comments = self._sort_comments_parents_first(origin_comments)
        comments_by_id = {c.id: c for c in ordered_comments}
        newly_created_resolved_review_comments: list[_GitHubTrackedComment] = []

        for origin_comment in ordered_comments:
            existing = tracked_comments.get(origin_comment.id)

            if existing is None:
                root_origin_id = self._resolve_root_origin_id(
                    origin_comment, comments_by_id
                )
                parent_tracked = (
                    tracked_comments.get(root_origin_id) if root_origin_id else None
                )

                created_review: _GitHubTrackedComment | None = None
                if parent_tracked is not None:
                    if parent_tracked.is_review_comment:
                        github_root_id = (
                            parent_tracked.in_reply_to_id or parent_tracked.comment_id
                        )
                        review_body = self._format_comment_body(
                            origin_comment,
                            resolver=resolver,
                            include_location=False,
                        )
                        created_review = self._create_pull_request_review_comment(
                            pr_number=pr_number,
                            body=review_body,
                            head_sha=head_sha,
                            comment=origin_comment,
                            in_reply_to=github_root_id,
                        )
                elif origin_comment.file_path and head_sha:
                    review_body = self._format_comment_body(
                        origin_comment,
                        resolver=resolver,
                        include_location=False,
                    )
                    created_review = self._create_pull_request_review_comment(
                        pr_number=pr_number,
                        body=review_body,
                        head_sha=head_sha,
                        comment=origin_comment,
                    )

                if created_review is not None:
                    tracked_comments[origin_comment.id] = created_review
                    result.synced_pr_comments += 1
                    if origin_comment.is_resolved and origin_comment.parent_id is None:
                        newly_created_resolved_review_comments.append(created_review)
                else:
                    issue_body = self._format_comment_body(
                        origin_comment,
                        resolver=resolver,
                        include_location=True,
                    )
                    created_issue = self._create_pull_request_comment(
                        pr_number, issue_body
                    )
                    tracked_comments[origin_comment.id] = created_issue
                    result.synced_pr_comments += 1
                    if origin_comment.is_resolved and created_issue.node_id:
                        self._resolve_pull_request_comment(created_issue.node_id)
            else:
                formatted_body = self._format_comment_body(
                    origin_comment,
                    resolver=resolver,
                    include_location=not existing.is_review_comment,
                )
                changed = False
                if existing.body != formatted_body:
                    if existing.is_review_comment:
                        self._update_pull_request_review_comment(
                            existing.comment_id, formatted_body
                        )
                    else:
                        self._update_pull_request_comment(
                            existing.comment_id, formatted_body
                        )
                    existing.body = formatted_body
                    changed = True

                if existing.is_review_comment:
                    is_root = (
                        origin_comment.parent_id is None
                        and existing.in_reply_to_id is None
                    )
                    if is_root and existing.thread_id:
                        if origin_comment.is_resolved and not existing.is_resolved:
                            self._resolve_review_thread(existing.thread_id)
                            existing.is_resolved = True
                            changed = True
                        elif not origin_comment.is_resolved and existing.is_resolved:
                            self._unresolve_review_thread(existing.thread_id)
                            existing.is_resolved = False
                            changed = True
                elif existing.node_id:
                    if origin_comment.is_resolved and not existing.is_resolved:
                        self._resolve_pull_request_comment(existing.node_id)
                        existing.is_resolved = True
                        changed = True
                    elif not origin_comment.is_resolved and existing.is_resolved:
                        self._unresolve_pull_request_comment(existing.node_id)
                        existing.is_resolved = False
                        changed = True

                if changed:
                    result.synced_pr_comments += 1

        if newly_created_resolved_review_comments:
            thread_map = self._fetch_review_threads(pr_number)
            for created_cm in newly_created_resolved_review_comments:
                thread_info = (
                    thread_map.get(created_cm.node_id) if created_cm.node_id else None
                ) or thread_map.get(created_cm.comment_id)
                if thread_info is not None:
                    thread_id, is_resolved = thread_info
                    if not is_resolved:
                        self._resolve_review_thread(thread_id)

    def _close_completed_pull_request(
        self,
        gh_pr: PullRequest,
        origin_pr_id: str,
        pr_exporter: PrExporter,
        result: PrSyncResult,
        resolver: GitHubUserResolver | None = None,
    ) -> None:
        if gh_pr.number is None:
            return

        origin_pr = pr_exporter.get_pull_request(origin_pr_id)
        final_state = origin_pr.state if origin_pr else "closed"

        self._sync_pr_comments(
            gh_pr.number,
            origin_pr_id,
            pr_exporter,
            result,
            resolver=resolver,
            head_sha=gh_pr.head_sha,
        )

        note = (
            f"This pull request was **{final_state}** on Bitbucket Cloud "
            "and has been closed automatically by `gh-repo-sync`."
        )
        self._create_pull_request_comment(gh_pr.number, note)
        self._close_pull_request(gh_pr.number)
        result.closed_prs.append(gh_pr.number)

    def reconcile(
        self,
        origin_prs: list[PullRequest],
        pr_exporter: PrExporter,
        branch_mapping: dict[str, str] | None = None,
        available_branches: set[str] | None = None,
        user_mapping: dict[str, str] | None = None,
    ) -> PrSyncResult:
        """
        Reconciles open and completed pull requests and their comments on GitHub.

        Args:
            origin_prs: Open pull requests fetched from the origin provider.
            pr_exporter: Exporter used to fetch comments and final PR states.
            branch_mapping: Optional mapping from origin to destination branch names.
            available_branches: Optional set of destination branch names that exist.
            user_mapping: Optional explicit mapping from origin display names to
                GitHub logins.

        Returns:
            PrSyncResult: Summary of created, updated, closed PRs, comments, and errors.
        """
        result = PrSyncResult()
        mapping = branch_mapping or {}
        resolver = GitHubUserResolver(
            org=self.owner,
            graphql_url=self._graphql_url,
            session=self._session,
            headers=self._headers(),
            explicit_mapping=user_mapping,
        )

        try:
            open_gh_prs = self._list_open_pull_requests()
        except Exception as e:
            msg = f"Failed to list open GitHub pull requests: {e}"
            logger.error("Failed to list open GitHub pull requests", error=str(e))
            result.errors.append(msg)
            return result

        tracked_gh_prs: dict[str, PullRequest] = {}
        for gh_pr in open_gh_prs:
            origin_id = self._extract_origin_pr_id(gh_pr.description)
            if origin_id:
                tracked_gh_prs[origin_id] = gh_pr

        active_origin_ids: set[str] = set()

        for origin_pr in origin_prs:
            if origin_pr.is_from_fork:
                logger.info(
                    "Skipping fork pull request",
                    origin_pr_id=origin_pr.id,
                    title=origin_pr.title,
                )
                continue

            mapped_source = mapping.get(
                origin_pr.source_branch, origin_pr.source_branch
            )
            mapped_target = mapping.get(
                origin_pr.target_branch, origin_pr.target_branch
            )

            if available_branches is not None and (
                mapped_source not in available_branches
                or mapped_target not in available_branches
            ):
                logger.info(
                    "Skipping pull request with missing destination branch",
                    origin_pr_id=origin_pr.id,
                    head=mapped_source,
                    base=mapped_target,
                )
                continue

            active_origin_ids.add(origin_pr.id)
            formatted_body = self._format_pr_body(origin_pr, resolver=resolver)

            try:
                existing_gh_pr = tracked_gh_prs.get(origin_pr.id)
                if existing_gh_pr is not None and existing_gh_pr.number is not None:
                    pr_updated = False
                    if (
                        existing_gh_pr.title != origin_pr.title
                        or existing_gh_pr.description != formatted_body
                        or existing_gh_pr.target_branch != mapped_target
                    ):
                        self._update_pull_request(
                            existing_gh_pr.number,
                            origin_pr.title,
                            formatted_body,
                            mapped_target,
                        )
                        pr_updated = True

                    if self._reconcile_pr_users(
                        existing_gh_pr.number, origin_pr, existing_gh_pr, resolver
                    ):
                        pr_updated = True

                    if pr_updated:
                        result.updated_prs.append(existing_gh_pr.number)

                    self._sync_pr_comments(
                        existing_gh_pr.number,
                        origin_pr.id,
                        pr_exporter,
                        result,
                        resolver=resolver,
                        head_sha=existing_gh_pr.head_sha,
                    )
                else:
                    created = self._create_pull_request(
                        title=origin_pr.title,
                        body=formatted_body,
                        head=mapped_source,
                        base=mapped_target,
                        draft=origin_pr.is_draft,
                    )
                    if created is not None:
                        pr_number, head_sha = created
                        result.created_prs.append(pr_number)
                        self._reconcile_pr_users(pr_number, origin_pr, None, resolver)
                        self._sync_pr_comments(
                            pr_number,
                            origin_pr.id,
                            pr_exporter,
                            result,
                            resolver=resolver,
                            head_sha=head_sha,
                        )
            except Exception as e:
                msg = f"Failed to reconcile origin PR #{origin_pr.id}: {e}"
                logger.error(
                    "Failed to reconcile pull request",
                    origin_pr_id=origin_pr.id,
                    error=str(e),
                )
                result.errors.append(msg)

        for origin_id, gh_pr in tracked_gh_prs.items():
            if origin_id not in active_origin_ids:
                try:
                    self._close_completed_pull_request(
                        gh_pr, origin_id, pr_exporter, result, resolver=resolver
                    )
                except Exception as e:
                    msg = (
                        f"Failed to close completed PR #{gh_pr.number} "
                        f"(origin #{origin_id}): {e}"
                    )
                    logger.error(
                        "Failed to close completed pull request",
                        pr_number=gh_pr.number,
                        origin_pr_id=origin_id,
                        error=str(e),
                    )
                    result.errors.append(msg)

        return result


class GitHubProvider(DestinationProvider):
    """Destination repository provider implementation for GitHub."""

    def __init__(
        self,
        repo_url: str,
        token: str,
        git: Git,
        remote_name: str = "destination_remote",
        api_base_url: str | None = None,
    ):
        """
        Initializes the GitHub Provider.

        Args:
            repo_url: The destination GitHub repository URL.
            token: Authentication token.
            git: Initialized Git client for executing commits.
            remote_name: Name of git remote tracking this repository.
            api_base_url: Optional REST API base URL override.
        """
        self.repo_url = repo_url
        self.token = token
        self.git = git
        self.remote_name = remote_name
        self._api_base_url = api_base_url
        self._pr_importer: GitHubPrImporter | None = None

    def _parse_github_url(self) -> tuple[str, str, str] | None:
        clean_url = self.repo_url.strip().rstrip("/")
        https_regex = r"^https?://(?:[^/@]+@)?([^/]+)/([^/]+)/([^/]+?)(?:\.git)?$"
        ssh_regex = r"^git@([^:]+):([^/]+)/([^/]+?)(?:\.git)?$"

        for pattern in (https_regex, ssh_regex):
            match = re.match(pattern, clean_url)
            if match:
                return match.group(1), match.group(2), match.group(3)
        return None

    def get_pr_importer(self) -> PrImporter | None:
        """Returns a GitHubPrImporter if the repository URL can be parsed."""
        if self._pr_importer is not None:
            return self._pr_importer
        parsed = self._parse_github_url()
        if not parsed:
            return None
        host, owner, repo = parsed
        self._pr_importer = GitHubPrImporter(
            owner=owner,
            repo=repo,
            token=self.token,
            host=host,
            api_base_url=self._api_base_url,
        )
        return self._pr_importer

    def get_authenticated_url(self) -> str:
        """Returns the destination remote git URL with authentication credentials."""
        clean_url = self.repo_url
        if clean_url.startswith("https://"):
            clean_url = clean_url[len("https://") :]
        elif clean_url.startswith("http://"):
            clean_url = clean_url[len("http://") :]
        return f"https://x-access-token:{self.token}@{clean_url}"

    def get_repo_name(self) -> str:
        """Returns the base repository name."""
        clean = self.repo_url.rstrip("/").removesuffix(".git")
        return clean.split("/")[-1]

    def _ensure_remote(self) -> None:
        if not self.git:
            raise RuntimeError("Git client is not initialized for GitHubProvider")
        remotes_out = self.git.run("remote", check=False)
        existing_remotes = (
            remotes_out.stdout.splitlines() if remotes_out.success else []
        )
        if self.remote_name not in existing_remotes:
            if "origin" in existing_remotes:
                self.git.run("remote", "rename", "origin", self.remote_name, check=True)
            else:
                self.git.remote_add(self.remote_name, self.get_authenticated_url())

    def get_remote_ref(self, branch_name: str) -> str:
        """
        Returns the remote reference string for a given branch name.

        Args:
            branch_name: Unqualified branch name.

        Returns:
            str: Full remote reference path for git operations.
        """
        return f"refs/remotes/{self.remote_name}/{branch_name}"

    def _get_default_branch_name(self) -> str:
        if not self.git:
            return "main"

        sym_res = self.git.symbolic_ref(
            f"refs/remotes/{self.remote_name}/HEAD", short=True
        )
        if (
            sym_res.success
            and isinstance(sym_res.stdout, str)
            and sym_res.stdout.strip()
        ):
            return sym_res.stdout.strip().removeprefix(f"{self.remote_name}/")
        return "main"

    def get_branches(self) -> list[Branch]:
        """
        Fetches remote references from destination and returns all valid branches.

        Returns:
            list[Branch]: List of valid branch objects available at destination,
                with the default branch indicated via `is_default=True`.
        """
        if not self.git:
            raise RuntimeError("Git client is not initialized for GitHubProvider")

        self._ensure_remote()
        fetch_res = self.git.fetch(self.remote_name, prune=True)
        if not fetch_res.success:
            fetch_res.raise_for_status()

        default_branch_name = self._get_default_branch_name()
        prefix = f"refs/remotes/{self.remote_name}/"
        raw_refs = self.git.for_each_ref(prefix)
        branches: list[Branch] = []
        for ref in raw_refs:
            branch_name = ref.removeprefix(prefix)
            if branch_name == "HEAD":
                continue
            if not validate_branch_name(branch_name, self.git):
                logger.warning(
                    "Ignoring invalid Destination branch name", branch=branch_name
                )
                continue
            branches.append(
                Branch(
                    name=branch_name,
                    remote_ref=f"{prefix}{branch_name}",
                    is_default=(branch_name == default_branch_name),
                )
            )

        if branches and not any(b.is_default for b in branches):
            fallback_index = 0
            for idx, b in enumerate(branches):
                if b.name in ("main", "master"):
                    fallback_index = idx
                    break
            branches[fallback_index] = branches[fallback_index].model_copy(
                update={"is_default": True}
            )

        return branches

    def commit(
        self,
        subject: str,
        author: str,
        body: str | None = None,
        allow_empty: bool = False,
    ) -> None:
        """
        Commits changes to the GitHub repository, injecting '[skip actions]' into the
        commit subject if it is not already present, preventing recursive workflow runs.

        Args:
            subject: The commit message subject line.
            author: The author of the commit (e.g. 'Name <email>').
            body: Optional commit message body.
            allow_empty: Allow creating an empty commit if there are no changes.
        """
        marker = "[skip actions]"

        # Prevent duplication if upstream already skips CI/actions
        skip_patterns = [
            r"\[skip actions\]",
            r"\[skip ci\]",
            r"\[ci skip\]",
            r"\[no ci\]",
            r"\[actions skip\]",
        ]
        pattern = "|".join(skip_patterns)

        if not re.search(pattern, subject, re.IGNORECASE):
            subject = f"{subject} {marker}"

        msg = f"{subject}\n\n{body}" if body else subject

        if self.git.status_porcelain():
            self.git.commit(msg, author=author)
        elif allow_empty:
            self.git.commit(msg, author=author, allow_empty=True)

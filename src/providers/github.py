import re
import urllib.parse
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


class GitHubPrImporter(PrImporter):
    """Pull request importer implementation for GitHub (github.com & Enterprise)."""

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str,
        host: str = "github.com",
        session: requests.Session | None = None,
    ):
        """
        Initializes the GitHub PR importer.

        Args:
            owner: GitHub repository owner or organization.
            repo: GitHub repository name.
            token: GitHub authentication token.
            host: GitHub hostname (defaults to 'github.com').
            session: Optional requests.Session instance.
        """
        self.owner = owner
        self.repo = repo
        self.host = host
        self._token = token
        self._session = session or self._create_session()

        if host.lower() == "github.com":
            self._api_base = "https://api.github.com"
            self._graphql_url = "https://api.github.com/graphql"
        else:
            self._api_base = f"https://{host}/api/v3"
            self._graphql_url = f"https://{host}/api/graphql"

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
    def _format_pr_body(pr: PullRequest) -> str:
        origin_ref = f"[#{pr.id}]({pr.url})" if pr.url else f"#{pr.id}"
        header = (
            f"> **Synced from origin** | Author: **{pr.author}** | "
            f"Original PR: {origin_ref}"
        )
        parts = [header]
        if pr.description.strip():
            parts.append(pr.description.strip())
        parts.append(f"<!-- gh-repo-sync:origin-pr-id={pr.id} -->")
        return "\n\n".join(parts)

    @staticmethod
    def _format_comment_body(comment: PullRequestComment) -> str:
        meta = [f"**{comment.author}**"]
        if comment.file_path:
            loc = (
                f"`{comment.file_path}` (line {comment.line})"
                if comment.line is not None
                else f"`{comment.file_path}`"
            )
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
                prs.append(
                    PullRequest(
                        id=str(item.get("number", "")),
                        number=int(item["number"]) if "number" in item else None,
                        title=str(item.get("title") or ""),
                        description=str(item.get("body") or ""),
                        source_branch=str((item.get("head") or {}).get("ref") or ""),
                        target_branch=str((item.get("base") or {}).get("ref") or ""),
                        author=str((item.get("user") or {}).get("login") or ""),
                        state=str(item.get("state") or "open").lower(),
                        is_draft=bool(item.get("draft", False)),
                        url=str(item.get("html_url") or ""),
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
    ) -> int | None:
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
        return int(data["number"])

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

    def _list_pull_request_comments(self, pr_number: int) -> list[PullRequestComment]:
        url: str | None = (
            f"{self._repo_api_url()}/issues/{pr_number}/comments?per_page=100"
        )
        comments: list[PullRequestComment] = []

        while url:
            response = self._session.get(url, headers=self._headers(), timeout=15)
            response.raise_for_status()
            items = response.json()
            for item in items:
                if not isinstance(item, dict):
                    continue
                comments.append(
                    PullRequestComment(
                        id=str(item.get("id", "")),
                        body=str(item.get("body") or ""),
                        author=str((item.get("user") or {}).get("login") or ""),
                        created_at=str(item.get("created_at") or ""),
                        updated_at=str(item.get("updated_at") or ""),
                        node_id=str(item["node_id"]) if item.get("node_id") else None,
                    )
                )
            url = self._next_link(response.headers)

        node_ids = [c.node_id for c in comments if c.node_id]
        minimized_map = self._fetch_comment_minimized_states(node_ids)
        for comment in comments:
            if comment.node_id and comment.node_id in minimized_map:
                comment.is_resolved = minimized_map[comment.node_id]

        return comments

    def _create_pull_request_comment(self, pr_number: int, body: str) -> str | None:
        url = f"{self._repo_api_url()}/issues/{pr_number}/comments"
        response = self._session.post(
            url, headers=self._headers(), json={"body": body}, timeout=15
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return str(data["node_id"]) if data.get("node_id") else None

    def _update_pull_request_comment(self, comment_id: str, body: str) -> None:
        url = f"{self._repo_api_url()}/issues/comments/{comment_id}"
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

    def _sync_pr_comments(
        self,
        pr_number: int,
        origin_pr_id: str,
        pr_exporter: PrExporter,
        result: PrSyncResult,
    ) -> None:
        origin_comments = pr_exporter.get_pull_request_comments(origin_pr_id)
        if not origin_comments:
            return

        existing_comments = self._list_pull_request_comments(pr_number)
        tracked_comments: dict[str, PullRequestComment] = {}
        for gh_comment in existing_comments:
            marker_id = self._extract_origin_comment_id(gh_comment.body)
            if marker_id:
                tracked_comments[marker_id] = gh_comment

        for origin_comment in origin_comments:
            formatted_body = self._format_comment_body(origin_comment)
            existing = tracked_comments.get(origin_comment.id)

            if existing is None:
                node_id = self._create_pull_request_comment(pr_number, formatted_body)
                result.synced_pr_comments += 1
                if origin_comment.is_resolved and node_id:
                    self._resolve_pull_request_comment(node_id)
            else:
                changed = False
                if existing.body != formatted_body:
                    self._update_pull_request_comment(existing.id, formatted_body)
                    changed = True

                if existing.node_id:
                    if origin_comment.is_resolved and not existing.is_resolved:
                        self._resolve_pull_request_comment(existing.node_id)
                        changed = True
                    elif not origin_comment.is_resolved and existing.is_resolved:
                        self._unresolve_pull_request_comment(existing.node_id)
                        changed = True

                if changed:
                    result.synced_pr_comments += 1

    def _close_completed_pull_request(
        self,
        gh_pr: PullRequest,
        origin_pr_id: str,
        pr_exporter: PrExporter,
        result: PrSyncResult,
    ) -> None:
        if gh_pr.number is None:
            return

        origin_pr = pr_exporter.get_pull_request(origin_pr_id)
        final_state = origin_pr.state if origin_pr else "closed"

        self._sync_pr_comments(gh_pr.number, origin_pr_id, pr_exporter, result)

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
    ) -> PrSyncResult:
        """
        Reconciles open and completed pull requests and their comments on GitHub.

        Args:
            origin_prs: Open pull requests fetched from the origin provider.
            pr_exporter: Exporter used to fetch comments and final PR states.
            branch_mapping: Optional mapping from origin to destination branch names.
            available_branches: Optional set of destination branch names that exist.

        Returns:
            PrSyncResult: Summary of created, updated, closed PRs, comments, and errors.
        """
        result = PrSyncResult()
        mapping = branch_mapping or {}

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
            formatted_body = self._format_pr_body(origin_pr)

            try:
                existing_gh_pr = tracked_gh_prs.get(origin_pr.id)
                if existing_gh_pr is not None and existing_gh_pr.number is not None:
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
                        result.updated_prs.append(existing_gh_pr.number)

                    self._sync_pr_comments(
                        existing_gh_pr.number, origin_pr.id, pr_exporter, result
                    )
                else:
                    pr_number = self._create_pull_request(
                        title=origin_pr.title,
                        body=formatted_body,
                        head=mapped_source,
                        base=mapped_target,
                        draft=origin_pr.is_draft,
                    )
                    if pr_number is not None:
                        result.created_prs.append(pr_number)
                        self._sync_pr_comments(
                            pr_number, origin_pr.id, pr_exporter, result
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
                        gh_pr, origin_id, pr_exporter, result
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
    ):
        """
        Initializes the GitHub Provider.

        Args:
            repo_url: The destination GitHub repository URL.
            token: Authentication token.
            git: Initialized Git client for executing commits.
            remote_name: Name of git remote tracking this repository.
        """
        self.repo_url = repo_url
        self.token = token
        self.git = git
        self.remote_name = remote_name
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

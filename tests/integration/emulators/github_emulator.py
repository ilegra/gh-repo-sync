"""Stateful GitHub REST v3 + GraphQL emulator for containerized integration tests."""

from __future__ import annotations

import http.server
import json
import os
import re
import urllib.parse
from typing import Any

_STATE: dict[str, Any] = {
    "next_pr_number": 1,
    "next_comment_id": 1,
    "next_thread_id": 1,
    "prs": {},
    "comments_by_pr": {},
    "comments_by_id": {},
    "comments_by_node_id": {},
    "review_comments_by_pr": {},
    "review_comments_by_id": {},
    "review_threads_by_pr": {},
    "review_threads_by_id": {},
    "reject_review_comment_paths": set(),
    "org_members": {},
    "reviews_by_pr": {},
}


def _reset_state() -> None:
    _STATE["next_pr_number"] = 1
    _STATE["next_comment_id"] = 1
    _STATE["next_thread_id"] = 1
    _STATE["prs"] = {}
    _STATE["comments_by_pr"] = {}
    _STATE["comments_by_id"] = {}
    _STATE["comments_by_node_id"] = {}
    _STATE["review_comments_by_pr"] = {}
    _STATE["review_comments_by_id"] = {}
    _STATE["review_threads_by_pr"] = {}
    _STATE["review_threads_by_id"] = {}
    _STATE["reject_review_comment_paths"] = set()
    _STATE["org_members"] = {}
    _STATE["reviews_by_pr"] = {}


class GitHubEmulatorHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data: dict[str, Any] = json.loads(raw) if raw else {}
        return data

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/health":
            self._send_json({"status": "ok"})
            return

        # GET /repos/{owner}/{repo}/pulls
        if re.match(r"^/repos/[^/]+/[^/]+/pulls$", path):
            state_filter = (qs.get("state") or ["open"])[0]
            prs = list(_STATE["prs"].values())
            if state_filter != "all":
                prs = [p for p in prs if p["state"] == state_filter]
            self._send_json(prs)
            return

        # GET /repos/{owner}/{repo}/pulls/{number}
        m_pr = re.match(r"^/repos/[^/]+/[^/]+/pulls/(\d+)$", path)
        if m_pr:
            pr_num = int(m_pr.group(1))
            pr = _STATE["prs"].get(pr_num)
            if not pr:
                self._send_json({"message": "Not Found"}, status=404)
                return
            self._send_json(pr)
            return

        # GET /repos/{owner}/{repo}/pulls/{number}/reviews
        m_rev = re.match(r"^/repos/[^/]+/[^/]+/pulls/(\d+)/reviews$", path)
        if m_rev:
            pr_num = int(m_rev.group(1))
            self._send_json(_STATE["reviews_by_pr"].get(pr_num, []))
            return

        # GET /repos/{owner}/{repo}/pulls/{number}/comments
        m_rcm = re.match(r"^/repos/[^/]+/[^/]+/pulls/(\d+)/comments$", path)
        if m_rcm:
            pr_num = int(m_rcm.group(1))
            self._send_json(_STATE["review_comments_by_pr"].get(pr_num, []))
            return

        # GET /repos/{owner}/{repo}/issues/{number}/comments
        m_cm = re.match(r"^/repos/[^/]+/[^/]+/issues/(\d+)/comments$", path)
        if m_cm:
            pr_num = int(m_cm.group(1))
            comments = _STATE["comments_by_pr"].get(pr_num, [])
            self._send_json(comments)
            return

        self._send_json({"message": f"Unhandled GET {path}"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        payload = self._read_json()

        if path == "/_seed/reset":
            _reset_state()
            self._send_json({"status": "reset"})
            return

        if path == "/_seed/org_members":
            org = str(payload.get("org") or "test-org")
            members = payload.get("members") or []
            _STATE["org_members"][org] = members
            self._send_json({"org": org, "members": members}, status=201)
            return

        if path == "/_seed/reject_review_comment_path":
            reject_path = str(payload.get("path") or "")
            if reject_path:
                _STATE["reject_review_comment_paths"].add(reject_path)
            self._send_json({"path": reject_path}, status=201)
            return

        # POST /repos/{owner}/{repo}/pulls
        if re.match(r"^/repos/[^/]+/[^/]+/pulls$", path):
            num = _STATE["next_pr_number"]
            _STATE["next_pr_number"] += 1
            pr = {
                "number": num,
                "title": payload.get("title", ""),
                "body": payload.get("body", ""),
                "head": {"ref": payload.get("head", ""), "sha": f"emu-sha-{num}"},
                "base": {"ref": payload.get("base", "")},
                "draft": bool(payload.get("draft", False)),
                "state": "open",
                "user": {"login": "gh-repo-sync[bot]"},
                "assignees": [],
                "requested_reviewers": [],
                "html_url": f"https://github.com/org/repo/pull/{num}",
            }
            _STATE["prs"][num] = pr
            _STATE["comments_by_pr"][num] = []
            _STATE["review_comments_by_pr"][num] = []
            _STATE["review_threads_by_pr"][num] = []
            _STATE["reviews_by_pr"][num] = []
            self._send_json(pr, status=201)
            return

        # POST /repos/{owner}/{repo}/issues/{number}/assignees
        m_as = re.match(r"^/repos/[^/]+/[^/]+/issues/(\d+)/assignees$", path)
        if m_as:
            pr_num = int(m_as.group(1))
            pr = _STATE["prs"].get(pr_num)
            if not pr:
                self._send_json({"message": "Not Found"}, status=404)
                return
            existing = {u["login"] for u in pr["assignees"]}
            for login in payload.get("assignees") or []:
                if login not in existing:
                    pr["assignees"].append({"login": login})
                    existing.add(login)
            self._send_json(pr, status=201)
            return

        # POST /repos/{owner}/{repo}/pulls/{number}/requested_reviewers
        m_rr = re.match(r"^/repos/[^/]+/[^/]+/pulls/(\d+)/requested_reviewers$", path)
        if m_rr:
            pr_num = int(m_rr.group(1))
            pr = _STATE["prs"].get(pr_num)
            if not pr:
                self._send_json({"message": "Not Found"}, status=404)
                return
            existing = {u["login"] for u in pr["requested_reviewers"]}
            for login in payload.get("reviewers") or []:
                if login not in existing:
                    pr["requested_reviewers"].append({"login": login})
                    existing.add(login)
            self._send_json(pr, status=201)
            return

        # POST /repos/{owner}/{repo}/pulls/{number}/comments
        m_rcm = re.match(r"^/repos/[^/]+/[^/]+/pulls/(\d+)/comments$", path)
        if m_rcm:
            pr_num = int(m_rcm.group(1))
            req_path = payload.get("path")
            if req_path and req_path in _STATE["reject_review_comment_paths"]:
                self._send_json(
                    {"message": "Validation Failed", "errors": ["outdated hunk"]},
                    status=422,
                )
                return

            in_reply_to = payload.get("in_reply_to")
            target_thread: dict[str, Any] | None = None
            if in_reply_to is not None:
                root_cm = _STATE["review_comments_by_id"].get(int(in_reply_to))
                if root_cm is None or root_cm.get("in_reply_to_id") is not None:
                    self._send_json(
                        {"message": "in_reply_to must be a top-level comment"},
                        status=422,
                    )
                    return
                target_thread = _STATE["review_threads_by_id"].get(
                    root_cm["_thread_id"]
                )

            cid = _STATE["next_comment_id"]
            _STATE["next_comment_id"] += 1
            node_id = f"PRRC_emu_{cid}"

            if target_thread is None:
                tid = _STATE["next_thread_id"]
                _STATE["next_thread_id"] += 1
                thread_id = f"PRRT_emu_{tid}"
                target_thread = {
                    "id": thread_id,
                    "isResolved": False,
                    "comments": [],
                }
                _STATE["review_threads_by_pr"].setdefault(pr_num, []).append(
                    target_thread
                )
                _STATE["review_threads_by_id"][thread_id] = target_thread

            review_comment: dict[str, Any] = {
                "id": cid,
                "node_id": node_id,
                "body": payload.get("body", ""),
                "user": {"login": "gh-repo-sync[bot]"},
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "commit_id": payload.get("commit_id"),
                "path": payload.get("path"),
                "line": payload.get("line"),
                "side": payload.get("side"),
                "start_line": payload.get("start_line"),
                "start_side": payload.get("start_side"),
                "subject_type": payload.get("subject_type"),
                "in_reply_to_id": int(in_reply_to) if in_reply_to is not None else None,
                "_thread_id": target_thread["id"],
            }
            target_thread["comments"].append({"id": node_id, "databaseId": cid})
            _STATE["review_comments_by_pr"].setdefault(pr_num, []).append(
                review_comment
            )
            _STATE["review_comments_by_id"][cid] = review_comment
            self._send_json(review_comment, status=201)
            return

        # POST /repos/{owner}/{repo}/issues/{number}/comments
        m_cm = re.match(r"^/repos/[^/]+/[^/]+/issues/(\d+)/comments$", path)
        if m_cm:
            pr_num = int(m_cm.group(1))
            cid = _STATE["next_comment_id"]
            _STATE["next_comment_id"] += 1
            node_id = f"IC_emu_{cid}"
            comment = {
                "id": cid,
                "node_id": node_id,
                "body": payload.get("body", ""),
                "user": {"login": "gh-repo-sync[bot]"},
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "_is_minimized": False,
                "_minimized_reason": None,
            }
            _STATE["comments_by_pr"].setdefault(pr_num, []).append(comment)
            _STATE["comments_by_id"][cid] = comment
            _STATE["comments_by_node_id"][node_id] = comment
            self._send_json(comment, status=201)
            return

        # POST /graphql
        if path == "/graphql":
            query = str(payload.get("query") or "")
            variables = payload.get("variables") or {}

            if "membersWithRole" in query:
                org = str(variables.get("org") or "")
                members = _STATE["org_members"].get(org) or []
                self._send_json(
                    {
                        "data": {
                            "organization": {
                                "membersWithRole": {
                                    "nodes": members,
                                    "pageInfo": {
                                        "hasNextPage": False,
                                        "endCursor": None,
                                    },
                                }
                            }
                        }
                    }
                )
                return

            if "reviewThreads" in query:
                pr_num = int(variables.get("number") or 0)
                threads = _STATE["review_threads_by_pr"].get(pr_num, [])
                nodes = [
                    {
                        "id": t["id"],
                        "isResolved": t["isResolved"],
                        "comments": {"nodes": t["comments"]},
                    }
                    for t in threads
                ]
                self._send_json(
                    {
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "reviewThreads": {
                                        "nodes": nodes,
                                        "pageInfo": {
                                            "hasNextPage": False,
                                            "endCursor": None,
                                        },
                                    }
                                }
                            }
                        }
                    }
                )
                return

            if "unresolveReviewThread" in query:
                thread_id = str(variables.get("threadId") or "")
                thread = _STATE["review_threads_by_id"].get(thread_id)
                if thread is not None:
                    thread["isResolved"] = False
                self._send_json(
                    {
                        "data": {
                            "unresolveReviewThread": {
                                "thread": {"id": thread_id, "isResolved": False}
                            }
                        }
                    }
                )
                return

            if "resolveReviewThread" in query:
                thread_id = str(variables.get("threadId") or "")
                thread = _STATE["review_threads_by_id"].get(thread_id)
                if thread is not None:
                    thread["isResolved"] = True
                self._send_json(
                    {
                        "data": {
                            "resolveReviewThread": {
                                "thread": {"id": thread_id, "isResolved": True}
                            }
                        }
                    }
                )
                return

            if "minimizeComment" in query:
                node_id = str(variables.get("id") or "")
                cm = _STATE["comments_by_node_id"].get(node_id)
                if cm is not None:
                    cm["_is_minimized"] = True
                    cm["_minimized_reason"] = "RESOLVED"
                self._send_json(
                    {
                        "data": {
                            "minimizeComment": {
                                "minimizedComment": {"isMinimized": True}
                            }
                        }
                    }
                )
                return

            if "unminimizeComment" in query:
                node_id = str(variables.get("id") or "")
                cm = _STATE["comments_by_node_id"].get(node_id)
                if cm is not None:
                    cm["_is_minimized"] = False
                    cm["_minimized_reason"] = None
                self._send_json(
                    {
                        "data": {
                            "unminimizeComment": {
                                "unminimizedComment": {"isMinimized": False}
                            }
                        }
                    }
                )
                return

            if "nodes(" in query:
                ids = variables.get("ids") or []
                nodes = []
                for nid in ids:
                    cm = _STATE["comments_by_node_id"].get(str(nid))
                    if cm is not None:
                        nodes.append(
                            {
                                "id": cm["node_id"],
                                "isMinimized": cm["_is_minimized"],
                                "minimizedReason": cm["_minimized_reason"],
                            }
                        )
                self._send_json({"data": {"nodes": nodes}})
                return

            if "node(" in query:
                nid = str(variables.get("id") or "")
                cm = _STATE["comments_by_node_id"].get(nid)
                node_data = (
                    {
                        "id": cm["node_id"],
                        "isMinimized": cm["_is_minimized"],
                        "minimizedReason": cm["_minimized_reason"],
                        "body": cm["body"],
                    }
                    if cm is not None
                    else None
                )
                self._send_json({"data": {"node": node_data}})
                return

            self._send_json({"data": {}})
            return

        self._send_json({"message": f"Unhandled POST {path}"}, status=404)

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        payload = self._read_json()

        # PATCH /repos/{owner}/{repo}/pulls/{number}
        m_pr = re.match(r"^/repos/[^/]+/[^/]+/pulls/(\d+)$", path)
        if m_pr:
            pr_num = int(m_pr.group(1))
            pr = _STATE["prs"].get(pr_num)
            if not pr:
                self._send_json({"message": "Not Found"}, status=404)
                return
            for key in ("title", "body", "state"):
                if key in payload:
                    pr[key] = payload[key]
            if "base" in payload:
                pr["base"]["ref"] = payload["base"]
            self._send_json(pr)
            return

        # PATCH /repos/{owner}/{repo}/pulls/comments/{comment_id}
        m_rcm = re.match(r"^/repos/[^/]+/[^/]+/pulls/comments/(\d+)$", path)
        if m_rcm:
            cid = int(m_rcm.group(1))
            cm = _STATE["review_comments_by_id"].get(cid)
            if not cm:
                self._send_json({"message": "Not Found"}, status=404)
                return
            if "body" in payload:
                cm["body"] = payload["body"]
            self._send_json(cm)
            return

        # PATCH /repos/{owner}/{repo}/issues/comments/{comment_id}
        m_cm = re.match(r"^/repos/[^/]+/[^/]+/issues/comments/(\d+)$", path)
        if m_cm:
            cid = int(m_cm.group(1))
            cm = _STATE["comments_by_id"].get(cid)
            if not cm:
                self._send_json({"message": "Not Found"}, status=404)
                return
            if "body" in payload:
                cm["body"] = payload["body"]
            self._send_json(cm)
            return

        self._send_json({"message": f"Unhandled PATCH {path}"}, status=404)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        payload = self._read_json()

        # DELETE /repos/{owner}/{repo}/pulls/{number}/requested_reviewers
        m_rr = re.match(r"^/repos/[^/]+/[^/]+/pulls/(\d+)/requested_reviewers$", path)
        if m_rr:
            pr_num = int(m_rr.group(1))
            pr = _STATE["prs"].get(pr_num)
            if not pr:
                self._send_json({"message": "Not Found"}, status=404)
                return
            to_remove = {str(r).lower() for r in (payload.get("reviewers") or [])}
            pr["requested_reviewers"] = [
                u
                for u in pr["requested_reviewers"]
                if str(u.get("login", "")).lower() not in to_remove
            ]
            self._send_json(pr, status=200)
            return

        self._send_json({"message": f"Unhandled DELETE {path}"}, status=404)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    server = http.server.HTTPServer(("0.0.0.0", port), GitHubEmulatorHandler)
    server.serve_forever()

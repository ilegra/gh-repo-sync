"""Stateful Bitbucket Cloud REST 2.0 emulator for containerized integration tests."""

from __future__ import annotations

import http.server
import json
import os
import re
import urllib.parse
from typing import Any

_STATE: dict[str, Any] = {
    "next_pr_id": 1,
    "next_comment_id": 1,
    "prs": {},
    "comments": {},
}


def _reset_state() -> None:
    _STATE["next_pr_id"] = 1
    _STATE["next_comment_id"] = 1
    _STATE["prs"] = {}
    _STATE["comments"] = {}


class BitbucketCloudEmulatorHandler(http.server.BaseHTTPRequestHandler):
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

        # GET /2.0/repositories/{ws}/{repo}
        if re.match(r"^/2\.0/repositories/[^/]+/[^/]+$", path):
            self._send_json(
                {
                    "is_archived": False,
                    "is_read_only": False,
                    "mainbranch": {"name": "main"},
                }
            )
            return

        # GET /2.0/repositories/{ws}/{repo}/pullrequests
        if re.match(r"^/2\.0/repositories/[^/]+/[^/]+/pullrequests$", path):
            state_values = qs.get("state")
            state_filter = state_values[0] if state_values else None
            prs = list(_STATE["prs"].values())
            if state_filter:
                prs = [
                    p
                    for p in prs
                    if str(p.get("state", "")).upper() == state_filter.upper()
                ]
            self._send_json({"values": prs})
            return

        # GET /2.0/repositories/{ws}/{repo}/pullrequests/{pr_id}
        m_pr = re.match(r"^/2\.0/repositories/[^/]+/[^/]+/pullrequests/([^/]+)$", path)
        if m_pr:
            pr_id = m_pr.group(1)
            pr = _STATE["prs"].get(pr_id)
            if not pr:
                self._send_json({"error": "not found"}, status=404)
                return
            self._send_json(pr)
            return

        # GET /2.0/repositories/{ws}/{repo}/pullrequests/{pr_id}/comments
        m_cm = re.match(
            r"^/2\.0/repositories/[^/]+/[^/]+/pullrequests/([^/]+)/comments$", path
        )
        if m_cm:
            pr_id = m_cm.group(1)
            comments = list(_STATE["comments"].get(pr_id, {}).values())
            self._send_json({"values": comments})
            return

        self._send_json({"error": f"Unhandled GET {path}"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        payload = self._read_json()

        if path == "/_seed/reset":
            _reset_state()
            self._send_json({"status": "reset"})
            return

        if path == "/_seed/pullrequests":
            pr_id = str(payload.get("id") or _STATE["next_pr_id"])
            _STATE["next_pr_id"] = max(_STATE["next_pr_id"] + 1, int(pr_id) + 1)
            ws = payload.get("workspace", "test-ws")
            repo = payload.get("repo", "test-repo")
            pr = {
                "id": int(pr_id),
                "title": payload.get("title", "Seeded PR"),
                "description": payload.get("description", ""),
                "state": payload.get("state", "OPEN"),
                "draft": bool(payload.get("draft", False)),
                "author": {"display_name": payload.get("author", "Alice")},
                "source": {
                    "branch": {"name": payload.get("source_branch", "feat/pr")},
                    "repository": {"full_name": f"{ws}/{repo}"},
                },
                "destination": {
                    "branch": {"name": payload.get("target_branch", "main")},
                    "repository": {"full_name": f"{ws}/{repo}"},
                },
                "links": {
                    "html": {
                        "href": f"https://bitbucket.org/{ws}/{repo}/pull-requests/{pr_id}"
                    }
                },
            }
            _STATE["prs"][pr_id] = pr
            _STATE["comments"].setdefault(pr_id, {})
            self._send_json(pr, status=201)
            return

        m_cm = re.match(r"^/_seed/pullrequests/([^/]+)/comments$", path)
        if m_cm:
            pr_id = m_cm.group(1)
            cm_id = str(payload.get("id") or _STATE["next_comment_id"])
            _STATE["next_comment_id"] = max(
                _STATE["next_comment_id"] + 1, int(cm_id) + 1
            )
            comment: dict[str, Any] = {
                "id": int(cm_id),
                "deleted": False,
                "content": {"raw": payload.get("body", "")},
                "user": {"display_name": payload.get("author", "Bob")},
                "created_on": "2026-01-01T00:00:00Z",
                "updated_on": "2026-01-01T00:00:00Z",
            }
            if payload.get("file_path"):
                comment["inline"] = {
                    "path": payload["file_path"],
                    "to": payload.get("line"),
                }
            if payload.get("is_resolved"):
                comment["resolution"] = {
                    "user": {"display_name": payload.get("resolved_by", "Alice")}
                }
            _STATE["comments"].setdefault(pr_id, {})[cm_id] = comment
            self._send_json(comment, status=201)
            return

        m_res = re.match(
            r"^/_seed/pullrequests/([^/]+)/comments/([^/]+)/resolve$", path
        )
        if m_res:
            pr_id, cm_id = m_res.group(1), m_res.group(2)
            comment_obj = _STATE["comments"].get(pr_id, {}).get(cm_id)
            if not comment_obj:
                self._send_json({"error": "comment not found"}, status=404)
                return
            comment_obj["resolution"] = {
                "user": {"display_name": payload.get("resolved_by", "Alice")}
            }
            self._send_json(comment_obj)
            return

        self._send_json({"error": f"Unhandled POST {path}"}, status=404)

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        payload = self._read_json()

        m_pr = re.match(r"^/_seed/pullrequests/([^/]+)$", path)
        if m_pr:
            pr_id = m_pr.group(1)
            pr = _STATE["prs"].get(pr_id)
            if not pr:
                self._send_json({"error": "PR not found"}, status=404)
                return
            if "state" in payload:
                pr["state"] = payload["state"]
            if "title" in payload:
                pr["title"] = payload["title"]
            if "description" in payload:
                pr["description"] = payload["description"]
            self._send_json(pr)
            return

        self._send_json({"error": f"Unhandled PATCH {path}"}, status=404)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    server = http.server.HTTPServer(("0.0.0.0", port), BitbucketCloudEmulatorHandler)
    server.serve_forever()

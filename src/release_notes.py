"""Release notes generator based on Git history and Conventional Commits."""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path


def _get_git_commit_range(
    from_tag: str | None = None, to_ref: str = "HEAD"
) -> list[str]:
    """Retrieve commit subjects within a revision range."""
    cmd = ["git", "log", "--pretty=format:%h|||%s"]
    if from_tag:
        cmd.append(f"{from_tag}..{to_ref}")
    else:
        cmd.append(to_ref)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.strip().splitlines()
        return [line.strip() for line in lines if line.strip()]
    except Exception:
        return []


def _get_latest_tag() -> str | None:
    """Retrieve the most recent reachable tag before HEAD."""
    try:
        res = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "HEAD^"],
            capture_output=True,
            text=True,
            check=True,
        )
        tag = res.stdout.strip()
        return tag if tag else None
    except Exception:
        return None


def _categorize_commits(commit_lines: list[str]) -> dict[str, list[str]]:
    """Parse Conventional Commits into logical categories."""
    categories: dict[str, list[str]] = defaultdict(list)

    # Conventional commit pattern: type(scope)!: description
    pattern = re.compile(
        r"^(?P<hash>[a-f0-9]+)\|\|\|(?P<type>[a-zA-Z]+)"
        r"(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s*(?P<desc>.+)$"
    )
    merge_pr_pattern = re.compile(
        r"^(?P<hash>[a-f0-9]+)\|\|\|Merge pull request #(?P<pr>\d+) "
        r"from (?P<branch>\S+)(?:\s+(?P<desc>.*))?$"
    )

    for line in commit_lines:
        match = pattern.match(line)
        if match:
            c_type = match.group("type").lower()
            scope = match.group("scope")
            is_breaking = bool(match.group("breaking"))
            desc = match.group("desc").strip()
            item = f"{desc} ({scope})" if scope else desc

            if is_breaking:
                categories["breaking"].append(item)

            if c_type in ("feat", "feature"):
                categories["features"].append(item)
            elif c_type in ("fix", "bug"):
                categories["fixes"].append(item)
            elif c_type in ("refactor", "perf"):
                categories["improvements"].append(item)
            elif c_type in ("test", "ci", "docs", "chore", "style"):
                categories["maintenance"].append(item)
            else:
                categories["other"].append(item)
            continue

        pr_match = merge_pr_pattern.match(line)
        if pr_match:
            pr_num = pr_match.group("pr")
            branch = pr_match.group("branch")
            desc = pr_match.group("desc")
            summary = desc if desc else f"Merged from `{branch}`"
            categories["prs"].append(f"#{pr_num}: {summary}")
            continue

        # Non-conventional commit fallback
        if "|||" in line:
            _, msg = line.split("|||", 1)
            categories["other"].append(msg.strip())

    return categories


def generate_release_notes(from_tag: str | None = None, to_ref: str = "HEAD") -> str:
    """
    Generate markdown formatted release notes.

    Args:
        from_tag: Base tag to compare from (or None to auto-detect).
        to_ref: Target git reference (defaults to HEAD).

    Returns:
        Formatted Markdown release notes.
    """
    if from_tag is None:
        from_tag = _get_latest_tag()

    commits = _get_git_commit_range(from_tag=from_tag, to_ref=to_ref)
    if not commits:
        return "No changes detected for this release."

    categories = _categorize_commits(commits)
    sections: list[str] = []

    if categories["breaking"]:
        items = "\n".join(f"- ⚠️ {item}" for item in categories["breaking"])
        sections.append(f"### ⚠️ Breaking Changes\n{items}")

    if categories["features"]:
        items = "\n".join(f"- {item}" for item in categories["features"])
        sections.append(f"### 🚀 Features\n{items}")

    if categories["fixes"]:
        items = "\n".join(f"- {item}" for item in categories["fixes"])
        sections.append(f"### 🐛 Bug Fixes\n{items}")

    if categories["improvements"]:
        items = "\n".join(f"- {item}" for item in categories["improvements"])
        sections.append(f"### ⚡ Performance & Improvements\n{items}")

    if categories["prs"]:
        items = "\n".join(f"- {item}" for item in categories["prs"])
        sections.append(f"### 🔀 Pull Requests\n{items}")

    if categories["maintenance"]:
        items = "\n".join(f"- {item}" for item in categories["maintenance"])
        sections.append(f"### 🧰 Maintenance & CI\n{items}")

    if categories["other"]:
        items = "\n".join(f"- {item}" for item in categories["other"])
        sections.append(f"### 📋 Other Changes\n{items}")

    return "\n\n".join(sections)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate release notes from git history."
    )
    parser.add_argument("--from-tag", default=None, help="Starting tag")
    parser.add_argument("--to-ref", default="HEAD", help="Target reference")
    parser.add_argument("--output", default=None, help="Output file path")

    args = parser.parse_args()
    notes = generate_release_notes(from_tag=args.from_tag, to_ref=args.to_ref)

    if args.output:
        Path(args.output).write_text(notes + "\n", encoding="utf-8")
    else:
        print(notes)

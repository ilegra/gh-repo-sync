"""Canonical version provider for gh-repo-sync."""

from __future__ import annotations

import re
from pathlib import Path


def _read_version_from_pyproject(pyproject_path: Path) -> str | None:
    """Read the version defined in pyproject.toml."""
    if not pyproject_path.is_file():
        return None

    content = pyproject_path.read_text(encoding="utf-8")

    # Robust regex matching [tool.poetry] version field
    match = re.search(r'(?m)^\s*version\s*=\s*["\']([^"\']+)["\']', content)
    if match:
        return match.group(1)

    return None


def get_version() -> str:
    """
    Return the canonical application version.

    Resolves the canonical version by locating pyproject.toml from the project root.
    Falls back to importlib.metadata if running as an installed package.

    Returns:
        The SemVer string of the application.
    """
    # 1. Search upwards for pyproject.toml starting from current file
    current_dir = Path(__file__).resolve().parent
    for candidate_dir in [current_dir.parent, current_dir]:
        candidate_file = candidate_dir / "pyproject.toml"
        parsed = _read_version_from_pyproject(candidate_file)
        if parsed:
            return parsed

    # 2. Fallback to package metadata if package is installed
    try:
        from importlib.metadata import version

        return version("gh-repo-sync")
    except Exception:
        pass

    # 3. Static fallback
    return "0.1.0"


if __name__ == "__main__":
    print(get_version())

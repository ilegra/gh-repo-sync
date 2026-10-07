import re
from pathlib import Path

from src import __version__
from src.version import _read_version_from_pyproject, get_version


def test_get_version_format() -> None:
    version = get_version()
    assert isinstance(version, str)
    # Check SemVer format (e.g., 0.1.0 or 1.2.3-alpha.1)
    assert re.match(r"^\d+\.\d+\.\d+", version) is not None


def test_package_dunder_version() -> None:
    assert __version__ == get_version()


def test_read_version_from_pyproject_success(tmp_path: Path) -> None:
    test_pyproject = tmp_path / "pyproject.toml"
    test_pyproject.write_text(
        """
[tool.poetry]
name = "test-pkg"
version = "1.2.3"
""",
        encoding="utf-8",
    )
    assert _read_version_from_pyproject(test_pyproject) == "1.2.3"


def test_read_version_from_pyproject_missing(tmp_path: Path) -> None:
    missing_file = tmp_path / "nonexistent.toml"
    assert _read_version_from_pyproject(missing_file) is None

"""
gh-repo-sync - Multi-platform Git repository synchronization engine.

Synchronize repositories between Origin (ADO, etc.) and Destination (GitHub).
"""

from src.config import SyncConfig, SyncResult
from src.core.sync import SyncManager
from src.main import main
from src.version import get_version

__version__ = get_version()

__all__ = [
    "SyncConfig",
    "SyncManager",
    "SyncResult",
    "__version__",
    "get_version",
    "main",
]

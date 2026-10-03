"""Derive a short project name from a working directory."""

import sys
from functools import lru_cache
from pathlib import Path

# Folders guarded by macOS privacy (TCC). Probing them from a background launchd job pops a
# permission prompt or fails, so names under them come from the path alone.
PROTECTED = ("Documents", "Desktop", "Downloads", "Library/Mobile Documents")


def _is_protected(path: Path) -> bool:
    if sys.platform != "darwin":  # TCC is a macOS mechanism
        return False
    home = Path.home()
    return any(path == home / p or home / p in path.parents for p in PROTECTED)


@lru_cache(maxsize=1024)
def project_name(cwd: str | None) -> str | None:
    """Name of the enclosing git repository if it still exists on disk, else the cwd basename."""
    if not cwd:
        return None
    path = Path(cwd)
    if _is_protected(path):
        return path.name or cwd
    for candidate in (path, *path.parents):
        if candidate == candidate.parent or candidate == Path.home():
            break
        if (candidate / ".git").exists():
            return candidate.name
    return path.name or cwd

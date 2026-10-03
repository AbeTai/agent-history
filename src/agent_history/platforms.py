"""OS-specific behaviour behind one seam, so every branch is testable on any machine.

Functions take an explicit `platform` ("darwin" | "win32" | "linux" | "other"); callers pass
`current_platform()`. Tests pass the platform they want to exercise.
"""

import locale
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import PurePosixPath, PureWindowsPath


def current_platform() -> str:
    p = sys.platform
    if p == "darwin":
        return "darwin"
    if p in ("win32", "cygwin"):
        return "win32"
    if p.startswith("linux"):
        return "linux"
    return "other"


def default_locations(platform: str, env: Mapping[str, str], home: str) -> dict[str, str]:
    """Where each tool keeps its data on this OS, honouring the tools' own env overrides."""
    P = PureWindowsPath if platform == "win32" else PurePosixPath
    h = P(home)
    if platform == "darwin":
        desktop = h / "Library" / "Application Support" / "Claude"
        data = h / ".local" / "share"
    elif platform == "win32":
        # Electron apps keep userData in %APPDATA%\<App>; per-machine caches in %LOCALAPPDATA%.
        desktop = P(env.get("APPDATA") or h / "AppData" / "Roaming") / "Claude"
        data = P(env.get("LOCALAPPDATA") or h / "AppData" / "Local")
    else:
        desktop = P(env.get("XDG_CONFIG_HOME") or h / ".config") / "Claude"
        data = P(env.get("XDG_DATA_HOME") or h / ".local" / "share")
    return {
        "claude_home": env.get("CLAUDE_CONFIG_DIR") or str(h / ".claude"),
        "codex_home": env.get("CODEX_HOME") or str(h / ".codex"),
        "claude_desktop": env.get("AGENT_HISTORY_CLAUDE_DESKTOP")
        or str(desktop / "claude-code-sessions"),
        "data_fallback": str(data / "agent-history"),
    }


if sys.platform == "win32":  # pragma: no cover - exercised on Windows CI only

    def _win_pid_alive(pid: int) -> bool:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            # ERROR_ACCESS_DENIED means the process exists but belongs to someone else.
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

else:

    def _win_pid_alive(pid: int) -> bool:
        raise OSError("Windows process query is only available on Windows")


def is_pid_alive(
    pid: int,
    platform: str | None = None,
    win_alive: Callable[[int], bool] = _win_pid_alive,
) -> bool:
    if (platform or current_platform()) == "win32":
        # Never os.kill(pid, 0) here: on Windows signal 0 is CTRL_C_EVENT.
        return win_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def decode_output(data: bytes | str | None, fallback: str | None = None) -> str:
    """Decode a tool's stdout/stderr: UTF-16 (schtasks /XML), UTF-8, or the console code page."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if len(data) >= 2 and data[1:2] == b"\x00":
        return data.decode("utf-16-le")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(fallback or locale.getpreferredencoding(False), errors="replace")

"""Best-effort desktop notification for failed background runs (never raises)."""

import json
import os
import subprocess
from collections.abc import Callable

from agent_history.platforms import current_platform

# Windows: a toast via the WinRT API from Windows PowerShell 5.1 (present on Windows 10/11).
# Text arrives through environment variables so no quoting/escaping of user content is needed.
_WIN_TOAST = (
    "$ErrorActionPreference='Stop';"
    "[void][Windows.UI.Notifications.ToastNotificationManager,"
    "Windows.UI.Notifications,ContentType=WindowsRuntime];"
    "$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
    "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
    "$t=$x.GetElementsByTagName('text');"
    "[void]$t.Item(0).AppendChild($x.CreateTextNode($env:AGENT_HISTORY_TITLE));"
    "[void]$t.Item(1).AppendChild($x.CreateTextNode($env:AGENT_HISTORY_BODY));"
    "$app='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show("
    "[Windows.UI.Notifications.ToastNotification]::new($x))"
)

CREATE_NO_WINDOW = 0x08000000


def notification_command(
    title: str, message: str, platform: str
) -> tuple[list[str], dict[str, str] | None] | None:
    if platform == "darwin":
        # AppleScript understands \" and \\ but not \uXXXX, so keep non-ASCII text as is.
        quote = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731
        script = f"display notification {quote(message)} with title {quote(title)}"
        return ["osascript", "-e", script], None
    if platform == "win32":
        argv = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-Command",
            _WIN_TOAST,
        ]
        return argv, {"AGENT_HISTORY_TITLE": title, "AGENT_HISTORY_BODY": message}
    if platform == "linux":
        return ["notify-send", "--app-name=agent-history", title, message], None
    return None


def _spawn(argv: list[str], env: dict[str, str] | None, platform: str) -> None:
    kwargs: dict = {"capture_output": True, "timeout": 15}
    if env:
        kwargs["env"] = {**os.environ, **env}
    if platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW  # no console flash from a hidden task
    subprocess.run(argv, **kwargs)


def notify(
    title: str,
    message: str,
    platform: str | None = None,
    spawn: Callable[[list[str], dict[str, str] | None, str], None] = _spawn,
) -> None:
    platform = platform or current_platform()
    command = notification_command(title, message, platform)
    if command is None:
        return
    try:
        spawn(command[0], command[1], platform)
    except (OSError, subprocess.SubprocessError):
        pass  # notifications are a convenience; the run log is the source of truth

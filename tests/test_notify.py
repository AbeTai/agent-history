from agent_history.notify import notification_command, notify

EVIL = 'can\'t open "C:\\x" $(Remove-Item ~) `whoami` ✓'


def test_macos_osascript():
    argv, env = notification_command("t", "本文", "darwin")
    assert argv[:2] == ["osascript", "-e"]
    assert '"本文"' in argv[2] and env is None


def test_windows_toast_passes_text_via_env_not_command_line():
    argv, env = notification_command("タイトル", EVIL, "win32")
    assert argv[0] == "powershell.exe"
    assert "-NoProfile" in argv and "-NonInteractive" in argv
    assert all(EVIL not in a and "タイトル" not in a for a in argv)
    assert env == {"AGENT_HISTORY_TITLE": "タイトル", "AGENT_HISTORY_BODY": EVIL}
    assert "ToastNotificationManager" in argv[-1]
    assert "$env:AGENT_HISTORY_BODY" in argv[-1]


def test_linux_notify_send():
    argv, env = notification_command("t", EVIL, "linux")
    assert argv == ["notify-send", "--app-name=agent-history", "t", EVIL]
    assert env is None


def test_unknown_platform_has_no_notifier():
    assert notification_command("t", "m", "other") is None


def test_notify_is_best_effort(monkeypatch):
    calls = []

    def spawn(argv, env, platform):
        calls.append((argv[0], platform))
        raise FileNotFoundError(argv[0])

    notify("t", "m", platform="linux", spawn=spawn)  # must not raise
    notify("t", "m", platform="other", spawn=spawn)
    assert calls == [("notify-send", "linux")]

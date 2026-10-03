import os
import sys

import pytest

from agent_history.platforms import (
    current_platform,
    decode_output,
    default_locations,
    is_pid_alive,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("darwin", "darwin"),
        ("win32", "win32"),
        ("linux", "linux"),
        ("linux2", "linux"),
        ("cygwin", "win32"),
        ("freebsd14", "other"),
    ],
)
def test_current_platform_normalizes(raw, expected, monkeypatch):
    monkeypatch.setattr("sys.platform", raw)
    assert current_platform() == expected


class TestDefaultLocations:
    def test_macos(self):
        loc = default_locations("darwin", env={}, home="/Users/me")
        assert loc == {
            "claude_home": "/Users/me/.claude",
            "codex_home": "/Users/me/.codex",
            "claude_desktop": "/Users/me/Library/Application Support/Claude/claude-code-sessions",
            "data_fallback": "/Users/me/.local/share/agent-history",
        }

    def test_windows_uses_appdata_and_localappdata(self):
        env = {
            "APPDATA": r"C:\Users\me\AppData\Roaming",
            "LOCALAPPDATA": r"C:\Users\me\AppData\Local",
        }
        loc = default_locations("win32", env=env, home=r"C:\Users\me")
        assert loc == {
            "claude_home": r"C:\Users\me\.claude",
            "codex_home": r"C:\Users\me\.codex",
            "claude_desktop": r"C:\Users\me\AppData\Roaming\Claude\claude-code-sessions",
            "data_fallback": r"C:\Users\me\AppData\Local\agent-history",
        }

    def test_windows_without_appdata_env_falls_back_under_profile(self):
        loc = default_locations("win32", env={}, home=r"C:\Users\me")
        assert loc["claude_desktop"] == r"C:\Users\me\AppData\Roaming\Claude\claude-code-sessions"
        assert loc["data_fallback"] == r"C:\Users\me\AppData\Local\agent-history"

    def test_linux_follows_xdg(self):
        loc = default_locations(
            "linux", env={"XDG_CONFIG_HOME": "/cfg", "XDG_DATA_HOME": "/dat"}, home="/home/me"
        )
        assert loc["claude_desktop"] == "/cfg/Claude/claude-code-sessions"
        assert loc["data_fallback"] == "/dat/agent-history"
        assert default_locations("linux", env={}, home="/home/me")["data_fallback"] == (
            "/home/me/.local/share/agent-history"
        )

    def test_tool_env_vars_win_everywhere(self):
        env = {
            "CLAUDE_CONFIG_DIR": r"D:\claude",
            "CODEX_HOME": r"D:\codex",
            "AGENT_HISTORY_CLAUDE_DESKTOP": r"D:\desk",
        }
        loc = default_locations("win32", env=env, home=r"C:\Users\me")
        assert (loc["claude_home"], loc["codex_home"], loc["claude_desktop"]) == (
            r"D:\claude",
            r"D:\codex",
            r"D:\desk",
        )


class TestIsPidAlive:
    def test_windows_never_sends_a_signal(self, monkeypatch):
        # os.kill(pid, 0) on Windows is CTRL_C_EVENT: it would interrupt the user's session.
        def forbidden(*a):
            raise AssertionError("os.kill must not be used on Windows")

        monkeypatch.setattr(os, "kill", forbidden)
        assert is_pid_alive(1234, platform="win32", win_alive=lambda pid: pid == 1234) is True
        assert is_pid_alive(99, platform="win32", win_alive=lambda pid: False) is False

    @pytest.mark.skipif(sys.platform == "win32", reason="os.kill(pid, 0) is CTRL_C_EVENT here")
    def test_posix_uses_signal_zero(self):
        assert is_pid_alive(os.getpid(), platform="darwin") is True
        assert is_pid_alive(2**22 + 12345, platform="linux") is False

    @pytest.mark.skipif(sys.platform != "win32", reason="real WinAPI query")
    def test_windows_query_on_real_windows(self):
        assert is_pid_alive(os.getpid()) is True
        assert is_pid_alive(2**22 + 12345) is False


class TestDecodeOutput:
    def test_utf8(self):
        assert decode_output("タスク".encode()) == "タスク"

    def test_windows_console_codepage(self):
        # schtasks prints in the console code page (cp932 on Japanese Windows).
        assert (
            decode_output(
                "エラー: 指定されたファイルが見つかりません。".encode("cp932"), fallback="cp932"
            )
            == "エラー: 指定されたファイルが見つかりません。"
        )

    def test_utf16_xml(self):
        xml = '<?xml version="1.0" encoding="UTF-16"?><Task/>'
        assert decode_output(xml.encode("utf-16")) == xml
        assert decode_output(xml.encode("utf-16-le")) == xml

    def test_passthrough_and_none(self):
        assert decode_output("already text") == "already text"
        assert decode_output(None) == ""

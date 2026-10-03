import json
import shutil
from pathlib import Path

from agent_history.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_ingest_command_uses_env_paths_and_prints_report(tmp_path, monkeypatch, capsys):
    shutil.copytree(FIXTURES / "codex", tmp_path / "codex")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-claude"))
    monkeypatch.setenv("AGENT_HISTORY_CLAUDE_DESKTOP", str(tmp_path / "no-desktop"))
    monkeypatch.setenv("AGENT_HISTORY_HOME", str(tmp_path / "data"))

    assert main(["ingest", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["parsed"] == 2
    assert (tmp_path / "data" / "history.db").exists()

    assert main(["ingest"]) == 0
    assert "skipped 2" in capsys.readouterr().out


def _env(tmp_path, monkeypatch):
    shutil.copytree(FIXTURES / "codex", tmp_path / "codex")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-claude"))
    monkeypatch.setenv("AGENT_HISTORY_CLAUDE_DESKTOP", str(tmp_path / "no-desktop"))
    monkeypatch.setenv("AGENT_HISTORY_HOME", str(tmp_path / "data"))
    notes: list[str] = []
    monkeypatch.setattr("agent_history.cli.notify", lambda title, msg: notes.append(msg))
    return notes


def test_scheduled_ingest_logs_run_and_status_is_healthy(tmp_path, monkeypatch, capsys):
    notes = _env(tmp_path, monkeypatch)
    assert main(["status"]) == 1  # never ran yet
    assert main(["ingest", "--scheduled"]) == 0
    log = (tmp_path / "data" / "logs" / "ingest.jsonl").read_text(encoding="utf-8").splitlines()
    run = json.loads(log[-1])
    assert run["status"] == "ok" and run["parsed"] == 2
    assert notes == []
    capsys.readouterr()
    assert main(["status"]) == 0
    assert "OK" in capsys.readouterr().out


def test_scheduled_ingest_failure_is_logged_and_notified(tmp_path, monkeypatch):
    notes = _env(tmp_path, monkeypatch)

    def explode(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("agent_history.cli.run_ingest", explode)
    assert main(["ingest", "--scheduled"]) == 1
    run = json.loads(
        (tmp_path / "data" / "logs" / "ingest.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert run["status"] == "failed" and "disk full" in run["error"]
    assert notes and "disk full" in notes[0]
    assert main(["status"]) == 1


def test_serve_binds_localhost_and_mounts_built_ui(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: captured.update(app=app, **kw))
    assert main(["serve", "--port", "9999"]) == 0
    assert captured["host"] == "127.0.0.1" and captured["port"] == 9999
    paths = {getattr(r, "path", None) for r in captured["app"].routes}
    assert "/api/sessions" in paths


def test_schedule_on_unsupported_os_explains_instead_of_crashing(tmp_path, monkeypatch, capsys):
    _env(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.platform", "freebsd14")
    assert main(["schedule", "install"]) == 2
    out = capsys.readouterr().out
    assert "agent-history ingest --scheduled" in out
    main(["status"])
    assert "未対応" in capsys.readouterr().out


def test_schedule_install_and_status_on_windows(tmp_path, monkeypatch, capsys):
    from test_schedule_win_linux import FakeSchtasks

    _env(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.platform", "win32")
    fake = FakeSchtasks()
    monkeypatch.setattr("agent_history.schedule._run", fake)
    assert main(["schedule", "install"]) == 0
    assert "タスクスケジューラ" in capsys.readouterr().out
    assert "<Command>" in fake.xml and "--scheduled" in fake.xml
    # env overrides travel as --env arguments because tasks cannot carry environment variables
    assert "--env" in fake.xml and "CODEX_HOME=" in fake.xml
    main(["status"])
    assert "有効（タスクスケジューラ）" in capsys.readouterr().out
    assert main(["schedule", "uninstall"]) == 0
    assert fake.xml is None


def test_schedule_install_on_linux_uses_crontab(tmp_path, monkeypatch, capsys):
    from test_schedule_win_linux import FakeCrontab

    _env(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.platform", "linux")
    fake = FakeCrontab("15 3 * * * backup.sh\n")
    monkeypatch.setattr("agent_history.schedule._run", fake)
    assert main(["schedule", "install", "--interval", "1800"]) == 0
    assert "*/30 * * * *" in fake.content and "backup.sh" in fake.content
    assert "起動時（@reboot）" in capsys.readouterr().out
    assert main(["schedule", "install", "--interval", "5400"]) == 1  # not expressible in cron
    assert "cron" in capsys.readouterr().err


def test_ingest_env_option_overrides_for_one_run(tmp_path, monkeypatch, capsys):
    _env(tmp_path, monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nowhere"))
    assert main(["ingest", "--json", "--env", f"CODEX_HOME={tmp_path / 'codex'}"]) == 0
    assert json.loads(capsys.readouterr().out)["parsed"] == 2
    assert main(["ingest", "--env", "BROKEN"]) == 2


def test_output_survives_cp932_console(tmp_path, monkeypatch):
    import io
    import sys

    _env(tmp_path, monkeypatch)
    monkeypatch.setenv("AGENT_HISTORY_HOME", str(tmp_path / "data✓🙂"))  # not encodable in cp932
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp932", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    main(["status"])  # must not raise UnicodeEncodeError
    stream.flush()
    text = raw.getvalue().decode("cp932")
    assert "定期実行" in text and "data??" in text  # Japanese intact, unencodable chars replaced


def test_ingest_warns_when_no_history_found(tmp_path, monkeypatch, capsys):
    _env(tmp_path, monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex"))
    assert main(["ingest"]) == 0
    out = capsys.readouterr().out
    assert "Claude Code の履歴が見つかりません" in out
    assert "Codex の履歴が見つかりません" in out


def test_serve_without_built_ui_prints_build_hint(tmp_path, monkeypatch, capsys):
    _env(tmp_path, monkeypatch)
    monkeypatch.setattr("agent_history.cli.REPO_ROOT", tmp_path)
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: None)
    assert main(["serve"]) == 0
    assert "npm run build" in capsys.readouterr().out

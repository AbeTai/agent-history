import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from agent_history.schedule import (
    CRON_BEGIN,
    TASK_NAME,
    CronSchedule,
    LaunchdSchedule,
    ScheduleConflict,
    TaskSchedulerSchedule,
    build_task_xml,
    cron_expression,
    make_scheduler,
    scheduled_program,
)

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
WIN_REPO = r"C:\Users\me\src\agent history & co"
WIN_PROGRAM = [
    rf"{WIN_REPO}\.venv\Scripts\pythonw.exe",
    "-m",
    "agent_history.cli",
    "ingest",
    "--scheduled",
]


def done(args, code=0, out=b"", err=b""):
    return subprocess.CompletedProcess(args, code, out, err)


# ---------------------------------------------------------------- program selection


def test_windows_runs_hidden_via_pythonw():
    exe = r"C:\r\.venv\Scripts\python.exe"
    prog = scheduled_program("win32", exe, exists=lambda p: True)
    assert prog[0] == r"C:\r\.venv\Scripts\pythonw.exe"
    assert prog[1:] == ["-m", "agent_history.cli", "ingest", "--scheduled"]
    assert scheduled_program("win32", exe, exists=lambda p: False)[0] == exe


def test_env_is_passed_as_arguments_where_the_scheduler_cannot_set_it():
    prog = scheduled_program(
        "win32", r"C:\p.exe", env={"CODEX_HOME": r"D:\codex"}, exists=lambda p: False
    )
    assert prog[-2:] == ["--env", r"CODEX_HOME=D:\codex"]
    assert "--env" not in scheduled_program("darwin", "/v/python", env={"CODEX_HOME": "/c"})


# ---------------------------------------------------------------- Windows Task Scheduler


def parse(xml: str) -> ET.Element:
    return ET.fromstring(xml.split("?>", 1)[1])


def test_task_xml_contents():
    xml = build_task_xml(
        WIN_PROGRAM,
        PureWindowsPath(WIN_REPO),
        3600,
        user=r"PC\me",
        start=datetime(2026, 10, 3, 21, 30),
    )
    assert xml.startswith('<?xml version="1.0" encoding="UTF-16"?>')
    task = parse(xml)
    exec_ = task.find("t:Actions/t:Exec", NS)
    assert exec_.findtext("t:Command", namespaces=NS) == WIN_PROGRAM[0]  # '&' round-trips
    assert exec_.findtext("t:Arguments", namespaces=NS) == "-m agent_history.cli ingest --scheduled"
    assert exec_.findtext("t:WorkingDirectory", namespaces=NS) == WIN_REPO
    rep = task.find("t:Triggers/t:TimeTrigger/t:Repetition", NS)
    assert rep.findtext("t:Interval", namespaces=NS) == "PT60M"
    assert task.findtext("t:Triggers/t:TimeTrigger/t:StartBoundary", namespaces=NS) == (
        "2026-10-03T21:30:00"
    )
    assert task.findtext("t:Triggers/t:LogonTrigger/t:UserId", namespaces=NS) == r"PC\me"
    settings = task.find("t:Settings", NS)
    assert settings.findtext("t:StartWhenAvailable", namespaces=NS) == "true"  # catch up
    assert settings.findtext("t:MultipleInstancesPolicy", namespaces=NS) == "IgnoreNew"
    assert settings.findtext("t:Hidden", namespaces=NS) == "true"
    assert settings.findtext("t:DisallowStartIfOnBatteries", namespaces=NS) == "false"
    principal = task.find("t:Principals/t:Principal", NS)
    assert principal.findtext("t:LogonType", namespaces=NS) == "InteractiveToken"
    assert principal.findtext("t:RunLevel", namespaces=NS) == "LeastPrivilege"


def test_task_xml_quotes_arguments_with_spaces_and_clamps_interval():
    prog = [r"C:\p\pythonw.exe", "-m", "agent_history.cli", "ingest", "--env", r"X=C:\a b"]
    xml = build_task_xml(prog, PureWindowsPath(r"C:\w"), 20, user=None, start=datetime(2026, 1, 1))
    task = parse(xml)
    assert task.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS).endswith(r'"X=C:\a b"')
    assert (
        task.findtext("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", namespaces=NS) == "PT1M"
    )
    assert task.find("t:Triggers/t:LogonTrigger/t:UserId", NS) is None


class FakeSchtasks:
    """Minimal schtasks: remembers the registered XML, answers queries in UTF-16 like Windows."""

    def __init__(self, registered_xml: str | None = None):
        self.xml = registered_xml
        self.calls: list[list[str]] = []

    def __call__(self, args, input=None):
        self.calls.append(args)
        verb = args[1]
        if verb == "/Create":
            self.xml = Path(args[args.index("/XML") + 1]).read_bytes().decode("utf-16")
            return done(args, 0, "成功: タスクが作成されました。".encode("cp932"))
        if verb == "/Query":
            if self.xml is None:
                return done(
                    args, 1, err="エラー: 指定されたファイルが見つかりません。".encode("cp932")
                )
            return done(args, 0, self.xml.encode("utf-16"))
        if verb == "/Delete":
            if self.xml is None:
                return done(args, 1, err="エラー: 見つかりません".encode("cp932"))
            self.xml = None
            return done(args, 0)
        raise AssertionError(args)


def win(tmp_path, fake, repo=WIN_REPO) -> TaskSchedulerSchedule:
    return TaskSchedulerSchedule(
        workdir=PureWindowsPath(repo),
        log_dir=tmp_path / "logs",
        program=WIN_PROGRAM,
        user=r"PC\me",
        run=fake,
        now=lambda: datetime(2026, 10, 3, 21, 0),
    )


def test_windows_install_registers_utf16_xml(tmp_path):
    fake = FakeSchtasks()
    sched = win(tmp_path, fake)
    sched.install(interval_s=1800)
    create = next(c for c in fake.calls if c[1] == "/Create")
    assert create[:4] == ["schtasks", "/Create", "/TN", TASK_NAME] and create[-1] == "/F"
    xml_file = Path(create[create.index("/XML") + 1])
    assert xml_file.read_bytes()[:2] == b"\xff\xfe"  # UTF-16 LE BOM, as Task Scheduler expects
    assert "<Interval>PT30M</Interval>" in fake.xml
    assert sched.is_loaded()
    assert sched.installed_workdir() == PureWindowsPath(WIN_REPO)


def test_windows_conflict_with_another_checkout_is_case_insensitive(tmp_path):
    fake = FakeSchtasks()
    win(tmp_path, fake).install()
    win(tmp_path, fake, repo=WIN_REPO.upper()).install()  # same folder, different case: OK
    with pytest.raises(ScheduleConflict):
        win(tmp_path, fake, repo=r"D:\other").install()
    win(tmp_path, fake, repo=r"D:\other").install(force=True)
    assert win(tmp_path, fake).installed_workdir() == PureWindowsPath(r"D:\other")


def test_windows_uninstall_and_missing_task(tmp_path):
    fake = FakeSchtasks()
    sched = win(tmp_path, fake)
    assert sched.uninstall() is False
    assert not sched.is_loaded() and sched.installed_workdir() is None
    sched.install()
    assert sched.uninstall() is True
    assert ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"] in fake.calls


def test_windows_create_failure_surfaces_console_message(tmp_path, monkeypatch):
    monkeypatch.setattr("locale.getpreferredencoding", lambda do_setlocale=True: "cp932")

    def run(args, input=None):
        if args[1] == "/Create":
            return done(args, 1, err="エラー: アクセスが拒否されました。".encode("cp932"))
        return done(args, 1)

    with pytest.raises(RuntimeError, match="アクセスが拒否されました"):
        win(tmp_path, run).install()


# ---------------------------------------------------------------- Linux cron


@pytest.mark.parametrize(
    ("seconds", "expr"),
    [
        (3600, "0 * * * *"),
        (1800, "*/30 * * * *"),
        (60, "*/1 * * * *"),
        (7200, "0 */2 * * *"),
        (86400, "0 0 * * *"),
    ],
)
def test_cron_expression(seconds, expr):
    assert cron_expression(seconds) == expr


def test_cron_expression_rejects_intervals_cron_cannot_express():
    with pytest.raises(ValueError, match="cron"):
        cron_expression(5400)


class FakeCrontab:
    def __init__(self, content: str | None = None):
        self.content = content
        self.calls = []

    def __call__(self, args, input=None):
        self.calls.append(args)
        if args == ["crontab", "-l"]:
            if self.content is None:
                return done(args, 1, err=b"no crontab for me\n")
            return done(args, 0, self.content.encode())
        if args == ["crontab", "-"]:
            self.content = input.decode()
            return done(args, 0)
        raise AssertionError(args)


LINUX_PROGRAM = [
    "/home/me/agent history/.venv/bin/python",
    "-m",
    "agent_history.cli",
    "ingest",
    "--scheduled",
]


def cron(tmp_path, fake, repo="/home/me/agent history") -> CronSchedule:
    return CronSchedule(
        workdir=Path(repo), log_dir=Path(repo) / "data" / "logs", program=LINUX_PROGRAM, run=fake
    )


def test_cron_install_keeps_other_entries_and_quotes_paths(tmp_path):
    fake = FakeCrontab("MAILTO=me\n15 3 * * * backup.sh\n")
    sched = cron(tmp_path, fake)
    sched.install()
    lines = fake.content.splitlines()
    assert lines[:2] == ["MAILTO=me", "15 3 * * * backup.sh"]
    assert any(line.startswith(CRON_BEGIN) and "/home/me/agent history" in line for line in lines)
    hourly = next(line for line in lines if line.startswith("0 * * * * "))
    assert "cd '/home/me/agent history' && '/home/me/agent history/.venv/bin/python'" in hourly
    assert ">> '/home/me/agent history/data/logs/cron.log' 2>&1" in hourly
    assert any(line.startswith("@reboot ") for line in lines)  # cron doesn't catch up by itself
    assert fake.content.endswith("\n")
    assert sched.is_loaded() and sched.installed_workdir() == PurePosixPath(
        "/home/me/agent history"
    )


def test_cron_reinstall_replaces_block_and_uninstall_restores(tmp_path):
    fake = FakeCrontab("15 3 * * * backup.sh\n")
    sched = cron(tmp_path, fake)
    sched.install()
    sched.install(interval_s=1800)
    assert fake.content.count(CRON_BEGIN) == 1
    assert "*/30 * * * *" in fake.content
    assert sched.uninstall() is True
    assert fake.content == "15 3 * * * backup.sh\n"
    assert sched.uninstall() is False


def test_cron_works_without_existing_crontab_and_detects_conflict(tmp_path):
    fake = FakeCrontab(None)
    cron(tmp_path, fake).install()
    with pytest.raises(ScheduleConflict):
        cron(tmp_path, fake, repo="/srv/other").install()


def test_cron_missing_binary_is_a_clear_error(tmp_path):
    def run(args, input=None):
        raise FileNotFoundError("crontab")

    sched = cron(tmp_path, run)
    with pytest.raises(RuntimeError, match="crontab"):
        sched.install()
    assert sched.is_loaded() is False


# ---------------------------------------------------------------- factory


def test_make_scheduler_picks_backend(tmp_path):
    common = dict(
        workdir=tmp_path,
        log_dir=tmp_path / "logs",
        program=["p"],
        run=lambda a, input=None: done(a),
    )
    assert isinstance(make_scheduler("darwin", **common), LaunchdSchedule)
    assert isinstance(make_scheduler("win32", **common), TaskSchedulerSchedule)
    assert isinstance(make_scheduler("linux", **common), CronSchedule)
    assert make_scheduler("other", **common) is None


def test_each_backend_describes_its_own_catch_up(tmp_path):
    common = dict(
        workdir=tmp_path,
        log_dir=tmp_path / "logs",
        program=["p"],
        run=lambda a, input=None: done(a),
    )
    assert make_scheduler("darwin", **common).catch_up == "ログイン時・スリープ復帰後"
    assert (
        make_scheduler("win32", **common).catch_up == "ログオン時・実行し損ねた分は可能になり次第"
    )
    assert make_scheduler("linux", **common).catch_up == "起動時（@reboot）"

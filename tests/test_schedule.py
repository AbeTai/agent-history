import plistlib
import subprocess
from pathlib import Path

from agent_history.schedule import (
    LABEL,
    LaunchdSchedule,
    ScheduleConflict,
    build_plist,
    is_supported,
)


def test_plist_runs_hourly_at_login_and_low_priority(tmp_path):
    p = build_plist(
        program=["/venv/bin/python", "-m", "agent_history.cli", "ingest", "--scheduled"],
        interval_s=3600,
        workdir=tmp_path,
        log_dir=tmp_path / "logs",
        env={"AGENT_HISTORY_HOME": "/d"},
    )
    assert p["Label"] == LABEL
    assert p["ProgramArguments"][-2:] == ["ingest", "--scheduled"]
    assert p["StartInterval"] == 3600
    assert p["RunAtLoad"] is True
    assert p["ProcessType"] == "Background"
    assert p["LowPriorityIO"] is True
    assert p["WorkingDirectory"] == str(tmp_path)
    assert p["StandardErrorPath"] == str(tmp_path / "logs" / "launchd.err.log")
    assert p["EnvironmentVariables"]["AGENT_HISTORY_HOME"] == "/d"


class FakeLaunchctl:
    def __init__(self, loaded=False):
        self.calls: list[list[str]] = []
        self.loaded = loaded

    def __call__(self, args, input=None):
        self.calls.append(args)
        verb = args[1]
        code = 0
        if verb == "bootstrap":
            self.loaded = True
        elif verb == "bootout":
            code = 0 if self.loaded else 3
            self.loaded = False
        elif verb == "print":
            code = 0 if self.loaded else 113
        return subprocess.CompletedProcess(args, code, "", "")


def make(tmp_path, fake) -> LaunchdSchedule:
    return LaunchdSchedule(
        agents_dir=tmp_path / "LaunchAgents",
        workdir=tmp_path / "repo",
        log_dir=tmp_path / "repo" / "data" / "logs",
        program=["/venv/bin/python", "-m", "agent_history.cli", "ingest", "--scheduled"],
        uid=501,
        run=fake,
    )


def test_install_writes_plist_and_bootstraps(tmp_path):
    fake = FakeLaunchctl()
    sched = make(tmp_path, fake)
    location = sched.install(interval_s=1800)
    path = tmp_path / "LaunchAgents" / f"{LABEL}.plist"
    assert location == str(path) and sched.plist_path == path
    assert plistlib.loads(path.read_bytes())["StartInterval"] == 1800
    assert (tmp_path / "repo" / "data" / "logs").is_dir()
    assert fake.calls[-1] == ["launchctl", "bootstrap", "gui/501", str(path)]
    assert sched.is_loaded()


def test_reinstall_replaces_loaded_job(tmp_path):
    fake = FakeLaunchctl(loaded=True)
    make(tmp_path, fake).install()
    verbs = [c[1] for c in fake.calls]
    assert verbs.index("bootout") < verbs.index("bootstrap")


def test_uninstall_is_idempotent(tmp_path):
    fake = FakeLaunchctl()
    sched = make(tmp_path, fake)
    sched.install()
    assert sched.uninstall() is True
    assert not sched.plist_path.exists()
    assert not sched.is_loaded()
    assert sched.uninstall() is False
    assert ["launchctl", "bootout", f"gui/501/{LABEL}"] in fake.calls


def test_install_fails_loudly_when_bootstrap_fails(tmp_path):
    def run(args, input=None):
        code = 5 if args[1] == "bootstrap" else 0
        return subprocess.CompletedProcess(
            args, code, "", "Bootstrap failed: 5: Input/output error"
        )

    sched = make(tmp_path, run)
    try:
        sched.install()
    except RuntimeError as e:
        assert "Bootstrap failed" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
    assert isinstance(sched.plist_path, Path)


def test_installed_workdir_reads_existing_plist(tmp_path):
    sched = make(tmp_path, FakeLaunchctl())
    assert sched.installed_workdir() is None
    sched.install()
    assert sched.installed_workdir() == tmp_path / "repo"


def test_install_refuses_to_replace_another_checkouts_job(tmp_path):
    fake = FakeLaunchctl()
    make(tmp_path, fake).install()
    other = LaunchdSchedule(
        agents_dir=tmp_path / "LaunchAgents",
        workdir=tmp_path / "other-clone",
        log_dir=tmp_path / "other-clone" / "data" / "logs",
        program=["/x/python"],
        uid=501,
        run=fake,
    )
    try:
        other.install()
    except ScheduleConflict as e:
        assert str(tmp_path / "repo") in str(e)
    else:
        raise AssertionError("expected ScheduleConflict")
    assert other.installed_workdir() == tmp_path / "repo"
    other.install(force=True)
    assert other.installed_workdir() == tmp_path / "other-clone"


def test_is_supported_on_macos_windows_linux():
    assert is_supported("darwin") and is_supported("win32") and is_supported("linux")
    assert not is_supported("other")

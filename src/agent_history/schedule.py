"""Register the periodic ingest with the OS scheduler.

| OS      | Backend                     | Catch-up after sleep / power-off              |
|---------|-----------------------------|-----------------------------------------------|
| macOS   | launchd user agent          | StartInterval coalesces + RunAtLoad at login  |
| Windows | Task Scheduler (schtasks)   | StartWhenAvailable + logon trigger            |
| Linux   | user crontab (managed block)| @reboot entry (cron itself never catches up)  |

Every ingest picks up all changes since the previous one, so one late run is enough to catch up.
All backends share: install(interval_s, force) / uninstall() / is_loaded() / installed_workdir().
"""

import os
import plistlib
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from xml.sax.saxutils import escape

from agent_history.platforms import decode_output

LABEL = "local.agent-history.ingest"
TASK_NAME = "agent-history-ingest"
CRON_BEGIN = "# >>> agent-history (managed block, do not edit) workdir="
CRON_END = "# <<< agent-history <<<"
DEFAULT_INTERVAL_S = 3600
PASSTHROUGH_ENV = (
    "AGENT_HISTORY_HOME",
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "AGENT_HISTORY_CLAUDE_DESKTOP",
)
CREATE_NO_WINDOW = 0x08000000

Runner = Callable[..., subprocess.CompletedProcess]


class ScheduleConflict(RuntimeError):
    """The job is already registered for a different checkout."""


def is_supported(platform: str) -> bool:
    return platform in ("darwin", "win32", "linux")


def _run(args: list[str], input: bytes | None = None) -> subprocess.CompletedProcess:
    kwargs: dict = {"capture_output": True, "input": input}
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return subprocess.run(args, **kwargs)


def passthrough_env() -> dict[str, str]:
    return {k: os.environ[k] for k in PASSTHROUGH_ENV if k in os.environ}


def scheduled_program(
    platform: str,
    executable: str,
    env: Mapping[str, str] | None = None,
    exists: Callable[[str], bool] = os.path.exists,
) -> list[str]:
    """Command the scheduler runs. Uses the venv's interpreter (not its resolved target)."""
    exe = executable
    if platform == "win32":
        # pythonw.exe has no console, so the hourly run doesn't flash a window.
        pythonw = str(PureWindowsPath(executable).with_name("pythonw.exe"))
        if exists(pythonw):
            exe = pythonw
    args = [exe, "-m", "agent_history.cli", "ingest", "--scheduled"]
    if env and platform != "darwin":  # launchd sets env natively; the others get --env
        for key, value in sorted(env.items()):
            args += ["--env", f"{key}={value}"]
    return args


def _conflict(current: PurePath) -> ScheduleConflict:
    return ScheduleConflict(
        f"別のチェックアウト（{current}）の定期取り込みが登録済みです。"
        "置き換えるには --force を付けてください"
    )


# ------------------------------------------------------------------------------ macOS


def build_plist(
    program: list[str], interval_s: int, workdir: Path, log_dir: Path, env: dict[str, str]
) -> dict:
    plist = {
        "Label": LABEL,
        "ProgramArguments": program,
        "WorkingDirectory": str(workdir),
        # launchd coalesces intervals missed during sleep into one run after wake, and
        # RunAtLoad covers login/reboot; each run picks up every change since the last one.
        "StartInterval": interval_s,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 10,
        "StandardOutPath": str(log_dir / "launchd.out.log"),
        "StandardErrorPath": str(log_dir / "launchd.err.log"),
    }
    if env:
        plist["EnvironmentVariables"] = env
    return plist


class LaunchdSchedule:
    kind = "launchd"
    catch_up = "ログイン時・スリープ復帰後"

    def __init__(
        self,
        workdir: Path,
        log_dir: Path,
        program: list[str],
        agents_dir: Path | None = None,
        uid: int | None = None,
        run: Runner = _run,
    ):
        self.agents_dir = Path(agents_dir or Path.home() / "Library" / "LaunchAgents")
        self.workdir = Path(workdir)
        self.log_dir = Path(log_dir)
        self.program = program
        if uid is None:
            uid = getattr(os, "getuid", lambda: 0)()  # launchd only exists on macOS
        self.domain = f"gui/{uid}"
        self.run = run

    @property
    def plist_path(self) -> Path:
        return self.agents_dir / f"{LABEL}.plist"

    def installed_workdir(self) -> Path | None:
        """Checkout the registered job runs in (None if no job is registered)."""
        try:
            workdir = plistlib.loads(self.plist_path.read_bytes()).get("WorkingDirectory")
        except (OSError, plistlib.InvalidFileException):
            return None
        return Path(workdir) if workdir else None

    def install(self, interval_s: int = DEFAULT_INTERVAL_S, force: bool = False) -> str:
        # One job per user: replacing another clone's job would silently stop its ingest.
        current = self.installed_workdir()
        if current is not None and current != self.workdir and not force:
            raise _conflict(current)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        plist = build_plist(self.program, interval_s, self.workdir, self.log_dir, passthrough_env())
        self.run(["launchctl", "bootout", f"{self.domain}/{LABEL}"])  # replace if loaded
        self.plist_path.write_bytes(plistlib.dumps(plist))
        res = self.run(["launchctl", "bootstrap", self.domain, str(self.plist_path)])
        if res.returncode != 0:
            detail = decode_output(res.stderr).strip()
            raise RuntimeError(f"launchctl bootstrap failed ({res.returncode}): {detail}")
        return str(self.plist_path)

    def uninstall(self) -> bool:
        """Returns True if anything was removed."""
        res = self.run(["launchctl", "bootout", f"{self.domain}/{LABEL}"])
        existed = self.plist_path.exists()
        if existed:
            self.plist_path.unlink()
        return existed or res.returncode == 0

    def is_loaded(self) -> bool:
        try:
            return self.run(["launchctl", "print", f"{self.domain}/{LABEL}"]).returncode == 0
        except OSError:
            return False


# ---------------------------------------------------------------------------- Windows


def build_task_xml(
    program: list[str], workdir: PurePath, interval_s: int, user: str | None, start: datetime
) -> str:
    """Task Scheduler 1.2 definition: repeat forever, catch up missed runs, run at logon."""
    minutes = max(1, round(interval_s / 60))
    user_el = f"<UserId>{escape(user)}</UserId>" if user else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>agent-history: periodic ingest of Claude Code / Codex history</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT{minutes}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>{user_el}
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">{user_el}
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(program[0])}</Command>
      <Arguments>{escape(subprocess.list2cmdline(program[1:]))}</Arguments>
      <WorkingDirectory>{escape(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _windows_user() -> str | None:
    name = os.environ.get("USERNAME")
    domain = os.environ.get("USERDOMAIN")
    if not name:
        return None
    return f"{domain}\\{name}" if domain else name


class TaskSchedulerSchedule:
    kind = "タスクスケジューラ"
    catch_up = "ログオン時・実行し損ねた分は可能になり次第"

    def __init__(
        self,
        workdir: PurePath,
        log_dir: Path,
        program: list[str],
        user: str | None = None,
        run: Runner = _run,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.workdir = PureWindowsPath(workdir)
        self.log_dir = Path(log_dir)
        self.program = program
        self.user = user if user is not None else _windows_user()
        self.run = run
        self.now = now

    def _query_xml(self) -> str | None:
        try:
            res = self.run(["schtasks", "/Query", "/TN", TASK_NAME, "/XML", "ONE"])
        except OSError:
            return None
        return decode_output(res.stdout) if res.returncode == 0 else None

    def installed_workdir(self) -> PureWindowsPath | None:
        xml = self._query_xml()
        if not xml:
            return None
        start = xml.find("<WorkingDirectory>")
        end = xml.find("</WorkingDirectory>")
        if start == -1 or end == -1:
            return None
        from xml.sax.saxutils import unescape

        return PureWindowsPath(unescape(xml[start + len("<WorkingDirectory>") : end]))

    def install(self, interval_s: int = DEFAULT_INTERVAL_S, force: bool = False) -> str:
        current = self.installed_workdir()
        if current is not None and current != self.workdir and not force:  # case-insensitive
            raise _conflict(current)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        xml_path = self.log_dir / "agent-history-task.xml"
        xml = build_task_xml(self.program, self.workdir, interval_s, self.user, self.now())
        xml_path.write_bytes(xml.encode("utf-16"))  # BOM + UTF-16LE, matching the declaration
        try:
            res = self.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"])
        except OSError as e:
            raise RuntimeError(f"schtasks を実行できません: {e}") from e
        if res.returncode != 0:
            msg = (decode_output(res.stderr) or decode_output(res.stdout)).strip()
            raise RuntimeError(f"schtasks /Create failed ({res.returncode}): {msg}")
        return f"タスクスケジューラ「{TASK_NAME}」"

    def uninstall(self) -> bool:
        try:
            res = self.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
        except OSError:
            return False
        return res.returncode == 0

    def is_loaded(self) -> bool:
        try:
            return self.run(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0
        except OSError:
            return False


# ------------------------------------------------------------------------------ Linux


def cron_expression(interval_s: int) -> str:
    minutes = max(1, round(interval_s / 60))
    if minutes < 60 and 60 % minutes == 0:
        return f"*/{minutes} * * * *"
    if minutes % 60 == 0:
        hours = minutes // 60
        if hours == 1:
            return "0 * * * *"
        if hours == 24:
            return "0 0 * * *"
        if hours < 24 and 24 % hours == 0:
            return f"0 */{hours} * * *"
    raise ValueError(
        f"{interval_s} 秒間隔は cron で表せません"
        "（60 の約数の分、または 24 の約数の時間を指定してください）"
    )


class CronSchedule:
    kind = "cron"
    catch_up = "起動時（@reboot）"

    def __init__(
        self, workdir: PurePath, log_dir: PurePath, program: list[str], run: Runner = _run
    ):
        # cron is POSIX-only: keep POSIX paths even when exercised from another OS in tests.
        self.workdir = PurePosixPath(workdir)
        self.log_dir = PurePosixPath(log_dir)
        self.program = program
        self.run = run

    def _read(self) -> str:
        try:
            res = self.run(["crontab", "-l"])
        except OSError as e:
            raise RuntimeError(
                f"crontab コマンドが見つかりません（cron をインストールしてください）: {e}"
            ) from e
        return decode_output(res.stdout) if res.returncode == 0 else ""  # no crontab yet

    def _write(self, content: str) -> None:
        res = self.run(["crontab", "-"], input=content.encode("utf-8"))
        if res.returncode != 0:
            raise RuntimeError(f"crontab の更新に失敗しました: {decode_output(res.stderr).strip()}")

    @staticmethod
    def _split(content: str) -> tuple[list[str], list[str]]:
        """(lines outside our block, lines of our block)."""
        outside, block, inside = [], [], False
        for line in content.splitlines():
            if line.startswith(CRON_BEGIN):
                inside = True
            if inside:
                block.append(line)
            else:
                outside.append(line)
            if inside and line == CRON_END:
                inside = False
        return outside, block

    def installed_workdir(self) -> PurePosixPath | None:
        try:
            _, block = self._split(self._read())
        except RuntimeError:
            return None
        return PurePosixPath(block[0][len(CRON_BEGIN) :]) if block else None

    def install(self, interval_s: int = DEFAULT_INTERVAL_S, force: bool = False) -> str:
        expr = cron_expression(interval_s)
        outside, block = self._split(self._read())
        if block:
            current = PurePosixPath(block[0][len(CRON_BEGIN) :])
            if current != self.workdir and not force:
                raise _conflict(current)
        q = shlex.quote
        command = (
            f"mkdir -p {q(str(self.log_dir))} && cd {q(str(self.workdir))} && "
            f"{' '.join(q(a) for a in self.program)} >> {q(str(self.log_dir / 'cron.log'))} 2>&1"
        )
        new_block = [
            f"{CRON_BEGIN}{self.workdir}",
            f"{expr} {command}",
            f"@reboot sleep 120 && {command}",
            CRON_END,
        ]
        self._write("\n".join(outside + new_block) + "\n")
        return "crontab"

    def uninstall(self) -> bool:
        try:
            outside, block = self._split(self._read())
        except RuntimeError:
            return False
        if not block:
            return False
        self._write("\n".join(outside) + "\n" if outside else "")
        return True

    def is_loaded(self) -> bool:
        return self.installed_workdir() is not None


# ---------------------------------------------------------------------------- factory


def make_scheduler(
    platform: str, workdir: Path, log_dir: Path, program: list[str], run: Runner = _run
) -> LaunchdSchedule | TaskSchedulerSchedule | CronSchedule | None:
    if platform == "darwin":
        return LaunchdSchedule(workdir=workdir, log_dir=log_dir, program=program, run=run)
    if platform == "win32":
        return TaskSchedulerSchedule(workdir=workdir, log_dir=log_dir, program=program, run=run)
    if platform == "linux":
        return CronSchedule(workdir=workdir, log_dir=log_dir, program=program, run=run)
    return None

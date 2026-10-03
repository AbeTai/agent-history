"""Command line entry point: `agent-history ingest | serve | status | schedule ...`."""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from agent_history import schedule as schedule_mod
from agent_history.ingest import REPO_ROOT, Config, ingest_and_log, run_ingest
from agent_history.notify import notify
from agent_history.platforms import current_platform
from agent_history.runlog import health, read_runs
from agent_history.schedule import (
    DEFAULT_INTERVAL_S,
    ScheduleConflict,
    make_scheduler,
    passthrough_env,
    scheduled_program,
)


def _configure_console() -> None:
    """Never crash on characters the console encoding lacks (cp932 on Japanese Windows).

    Real Windows consoles already get UTF-8 via the console API; this matters when output is
    redirected or piped, where Python uses the ANSI code page. We keep that encoding (forcing
    UTF-8 there is what turns text into mojibake for cp932 readers) and only replace what
    cannot be represented.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fmt(ms: int | None) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") if ms else "-"


def _run_log(config: Config) -> Path:
    return config.log_dir / "ingest.jsonl"


def _ingest(args: argparse.Namespace) -> int:
    for item in args.env or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            print(f"--env は KEY=VALUE の形式で指定してください: {item}", file=sys.stderr)
            return 2
        os.environ[key] = value  # schedulers that cannot set env pass it this way
    config = Config.from_env()
    trigger = "scheduled" if args.scheduled else "manual"
    try:
        report = ingest_and_log(config, trigger, ingest=run_ingest)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        if args.scheduled:
            notify("agent-history: 取り込み失敗", error)
        print(f"ingest failed: {error}", file=sys.stderr)
        return 1
    if args.scheduled and report.failed:
        notify(
            "agent-history: 一部のファイルを読めませんでした",
            f"{len(report.failed)} 件。agent-history status で確認してください",
        )
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False))
    else:
        print(
            f"parsed {report.parsed}, skipped {report.skipped}, empty {report.empty}, "
            f"failed {len(report.failed)}  → {config.db_path}"
        )
        for path, err in report.failed:
            print(f"  ! {path}: {err}")
        sources = config.sources()
        for name in report.missing_sources:
            label = {"claude": "Claude Code", "codex": "Codex"}[name]
            print(f"  - {label} の履歴が見つかりません（{sources[name]}）")
            print("    （そのツールを使っていなければ問題ありません）")
    return 0


def _scheduler(config: Config):
    platform = current_platform()
    program = scheduled_program(platform, sys.executable, passthrough_env())
    # schedule_mod._run is looked up at call time so tests can stub the OS commands.
    return make_scheduler(platform, REPO_ROOT, config.log_dir, program, run=schedule_mod._run)


def _schedule_state(config: Config) -> str:
    sched = _scheduler(config)
    if sched is None:
        return (
            "未対応（この OS は自動登録できません。"
            "OS のスケジューラで `agent-history ingest --scheduled` を定期実行）"
        )
    workdir = sched.installed_workdir()
    if workdir is not None and workdir != sched.workdir:
        return f"別のチェックアウトで登録済み（{workdir}）"
    if sched.is_loaded():
        return f"有効（{sched.kind}）"
    return f"未登録（agent-history schedule install で {sched.kind} に登録）"


def _unsupported_schedule_hint() -> int:
    print("この OS では定期取り込みの自動登録に対応していません（対応: macOS / Windows / Linux）。")
    print("OS のスケジューラで 1 時間ごとに次を実行してください:")
    print(f"  cd {REPO_ROOT} && uv run agent-history ingest --scheduled")
    return 2


def _status(args: argparse.Namespace) -> int:
    config = Config.from_env()
    runs = read_runs(_run_log(config))
    verdict = health(runs, _now_ms())
    print(
        ("OK" if verdict["ok"] else "NG") + (f"  {verdict['reason']}" if verdict["reason"] else "")
    )
    print(f"最終成功: {_fmt(verdict['last_success_at'])}")
    print(f"定期実行: {_schedule_state(config)}")
    print(f"データ:   {config.data_home}")
    if runs:
        print("直近の実行:")
        for r in runs[-5:]:
            detail = r.get("error") or f"parsed {r.get('parsed', 0)}, skipped {r.get('skipped', 0)}"
            print(
                f"  {_fmt(r['started_at'])}  {r['status']:7} {r.get('trigger', ''):9} "
                f"{r['duration_ms']:>5}ms  {detail}"
            )
    return 0 if verdict["ok"] else 1


def _schedule_install(args: argparse.Namespace) -> int:
    sched = _scheduler(Config.from_env())
    if sched is None:
        return _unsupported_schedule_hint()
    try:
        location = sched.install(interval_s=args.interval, force=args.force)
    except (ScheduleConflict, RuntimeError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1
    print(f"登録しました（{sched.kind}）: {location}")
    print(f"  {args.interval} 秒ごと＋{sched.catch_up}に実行します")
    return 0


def _schedule_uninstall(args: argparse.Namespace) -> int:
    sched = _scheduler(Config.from_env())
    if sched is None:
        return _unsupported_schedule_hint()
    try:
        removed = sched.uninstall()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"登録を解除しました（{sched.kind}）" if removed else "登録されていませんでした")
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from agent_history.api import create_app

    dist = REPO_ROOT / "web" / "dist"
    if not (dist / "index.html").is_file():
        print("画面がビルドされていません（API のみ起動します）。画面を使うには:")
        print("  cd web && npm install && npm run build")
        print("  （PowerShell: cd web; npm install; npm run build）")
    app = create_app(Config.from_env(), static_dir=dist)
    print(f"http://127.0.0.1:{args.port}")
    # Localhost only: the API exposes full transcripts.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    parser = argparse.ArgumentParser(prog="agent-history")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser(
        "ingest", help="import Claude Code / Codex history (changed files only)"
    )
    p_ingest.add_argument("--json", action="store_true", help="print the report as JSON")
    p_ingest.add_argument(
        "--scheduled", action="store_true", help="run from the OS scheduler: notify on failure"
    )
    p_ingest.add_argument(
        "--env",
        action="append",
        metavar="KEY=VALUE",
        help="set an environment variable for this run (used by schedulers without env support)",
    )
    p_ingest.set_defaults(func=_ingest)

    p_serve = sub.add_parser("serve", help="start the API and web UI on localhost")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.set_defaults(func=_serve)

    p_status = sub.add_parser("status", help="show ingest health (exit 1 if unhealthy)")
    p_status.set_defaults(func=_status)

    p_sched = sub.add_parser(
        "schedule", help="manage the periodic ingest (launchd / Task Scheduler / cron)"
    )
    sched_sub = p_sched.add_subparsers(dest="action", required=True)
    p_install = sched_sub.add_parser("install", help="register with the OS scheduler")
    p_install.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_S,
        help=f"seconds between runs (default {DEFAULT_INTERVAL_S})",
    )
    p_install.add_argument(
        "--force", action="store_true", help="replace a job registered from another checkout"
    )
    p_install.set_defaults(func=_schedule_install)
    sched_sub.add_parser("uninstall", help="remove the scheduled job").set_defaults(
        func=_schedule_uninstall
    )

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

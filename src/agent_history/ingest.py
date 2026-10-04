"""Discover transcript files, parse the ones that changed, and save them to the store."""

import os
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from agent_history.platforms import current_platform, default_locations, is_pid_alive
from agent_history.sources.claude import (
    load_desktop_meta,
    parse_claude_session,
    running_claude_sessions,
)
from agent_history.sources.codex import load_thread_names, parse_codex_rollout
from agent_history.store import Store

# Bump when parsers start extracting something new: every file is re-read once on the next run.
# 2: context compactions; compaction summaries are no longer counted as prompts.
PARSER_VERSION = 2

# src/agent_history/ingest.py -> repository root (`uv sync` installs the project in editable mode)
REPO_ROOT = Path(__file__).resolve().parents[2]


def default_data_home(repo_root: Path = REPO_ROOT, fallback: str | None = None) -> Path:
    """`data/` inside the checkout; a per-user dir when not running from a checkout."""
    if (repo_root / "pyproject.toml").is_file():
        return repo_root / "data"
    if fallback is None:
        fallback = default_locations(current_platform(), os.environ, str(Path.home()))[
            "data_fallback"
        ]
    return Path(fallback)


@dataclass
class Config:
    claude_home: Path
    claude_desktop: Path
    codex_home: Path
    data_home: Path

    @property
    def db_path(self) -> Path:
        return self.data_home / "history.db"

    @property
    def archive_dir(self) -> Path:
        return self.data_home / "archive"

    @property
    def log_dir(self) -> Path:
        return self.data_home / "logs"

    def sources(self) -> dict[str, Path]:
        """Where each tool's transcripts are read from."""
        return {"claude": self.claude_home / "projects", "codex": self.codex_home / "sessions"}

    @classmethod
    def from_env(
        cls,
        platform: str | None = None,
        env: Mapping[str, str] | None = None,
        home: str | None = None,
    ) -> "Config":
        env = os.environ if env is None else env
        loc = default_locations(
            platform or current_platform(), env, home if home is not None else str(Path.home())
        )
        data_home = env.get("AGENT_HISTORY_HOME")
        return cls(
            claude_home=Path(loc["claude_home"]),
            claude_desktop=Path(loc["claude_desktop"]),
            codex_home=Path(loc["codex_home"]),
            data_home=Path(data_home)
            if data_home
            else default_data_home(fallback=loc["data_fallback"]),
        )


@dataclass
class IngestReport:
    parsed: int = 0
    skipped: int = 0
    empty: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    missing_sources: list[str] = field(default_factory=list)


def _stat_fingerprint(path: Path) -> str:
    st = path.stat()
    return f"v{PARSER_VERSION}:{st.st_size}:{st.st_mtime_ns}"


def _claude_files(config: Config) -> list[tuple[Path, Path | None]]:
    """(file to parse, archive destination or None when parsing the archive itself)."""
    projects = config.claude_home / "projects"
    archive = config.archive_dir / "claude"
    files: list[tuple[Path, Path | None]] = []
    live: set[Path] = set()
    if projects.is_dir():
        for f in sorted(projects.glob("*/*.jsonl")):
            rel = f.relative_to(projects)
            live.add(rel)
            files.append((f, archive / rel))
    if archive.is_dir():
        # Transcripts Claude Code has already cleaned up survive only in our archive.
        for f in sorted(archive.glob("*/*.jsonl")):
            if f.relative_to(archive) not in live:
                files.append((f, None))
    return files


def _codex_files(config: Config) -> list[Path]:
    files: list[Path] = []
    for sub in ("sessions", "archived_sessions"):
        root = config.codex_home / sub
        if root.is_dir():
            files.extend(sorted(root.rglob("rollout-*.jsonl")))
    return files


def run_ingest(
    config: Config, store: Store, pid_alive: Callable[[int], bool] = is_pid_alive
) -> IngestReport:
    report = IngestReport(
        missing_sources=[name for name, path in config.sources().items() if not path.is_dir()]
    )

    def ingest_one(path: Path, source: str, fingerprint: str, parse: Callable, after=None):
        if not store.needs_ingest(str(path), fingerprint):
            report.skipped += 1
            return
        try:
            parsed = parse()
        except Exception as e:  # one malformed transcript must not stop the run
            report.failed.append((str(path), f"{type(e).__name__}: {e}"))
            return
        if parsed is None:
            report.empty += 1
            store.mark_ingested(str(path), source, fingerprint, None)
            return
        store.save(parsed)
        report.parsed += 1
        if after:
            try:
                after()
            except OSError as e:  # e.g. the file is locked on Windows while being written
                report.failed.append((str(path), f"archive: {type(e).__name__}: {e}"))
                return  # not marked as ingested, so the copy is retried next run
        store.mark_ingested(str(path), source, fingerprint, parsed.session.id)

    desktop = load_desktop_meta(config.claude_desktop)
    for path, archive_to in _claude_files(config):
        meta = desktop.get(path.stem)
        fingerprint = _stat_fingerprint(path)
        if meta:
            summary_for = meta.get("postTurnSummaryFor")
            fingerprint += f":{meta.get('lastActivityAt')}:{summary_for}:{meta.get('title')}"

        def archive(src=path, dst=archive_to):
            if dst is not None:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        ingest_one(
            path,
            "claude",
            fingerprint,
            lambda p=path, m=meta: parse_claude_session(p, desktop=m),
            after=archive,
        )

    names = load_thread_names(config.codex_home / "session_index.jsonl")
    for path in _codex_files(config):
        thread_id = path.stem[-36:]
        fingerprint = f"{_stat_fingerprint(path)}:{names.get(thread_id, '')}"
        ingest_one(path, "codex", fingerprint, lambda p=path: parse_codex_rollout(p, names=names))

    running = running_claude_sessions(config.claude_home / "sessions", pid_alive=pid_alive)
    store.set_running("claude", {f"claude:{sid}" for sid in running})
    return report


def ingest_and_log(
    config: Config,
    trigger: str,
    ingest: Callable[[Config, Store], IngestReport] = run_ingest,
    now: Callable[[], int] | None = None,
) -> IngestReport:
    """Run an ingest and append the outcome to data/logs/ingest.jsonl. Re-raises failures."""
    from dataclasses import asdict

    from agent_history.runlog import record_run

    clock = now or (lambda: int(time.time() * 1000))
    log = config.log_dir / "ingest.jsonl"
    started = clock()
    try:
        with Store(config.db_path) as store:
            report = ingest(config, store)
    except Exception as e:
        record_run(
            log,
            started_at=started,
            duration_ms=clock() - started,
            status="failed",
            trigger=trigger,
            error=f"{type(e).__name__}: {e}",
        )
        raise
    record_run(
        log,
        started_at=started,
        duration_ms=clock() - started,
        status="partial" if report.failed else "ok",
        trigger=trigger,
        **asdict(report),
    )
    return report

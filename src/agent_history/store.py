"""SQLite persistence for normalized sessions.

Rows are replaced per session on every save, and never deleted when a source file disappears,
so history outlives Claude Code's 30-day transcript cleanup.
"""

import sqlite3
import time
from pathlib import Path

from agent_history.model import ParsedSession

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    native_id TEXT NOT NULL,
    parent_id TEXT,
    is_subagent INTEGER NOT NULL DEFAULT 0,
    title TEXT,
    cwd TEXT,
    project TEXT,
    branch TEXT,
    repo_url TEXT,
    entrypoint TEXT,
    started_at INTEGER NOT NULL,
    ended_at INTEGER NOT NULL,
    cost_usd REAL,
    work_state TEXT,
    work_detail TEXT,
    needs_action INTEGER NOT NULL DEFAULT 0,
    is_running INTEGER NOT NULL DEFAULT 0,
    source_path TEXT,
    ingested_at INTEGER
);
CREATE TABLE IF NOT EXISTS turns (
    session_id TEXT NOT NULL,
    key TEXT NOT NULL,
    seq INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER NOT NULL,
    state TEXT NOT NULL,
    prompt TEXT,
    prompt_kind TEXT,
    final_message TEXT,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, key)
);
CREATE TABLE IF NOT EXISTS segments (
    session_id TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS segments_range ON segments(started_at, ended_at);
CREATE INDEX IF NOT EXISTS segments_session ON segments(session_id);
CREATE TABLE IF NOT EXISTS commits (
    session_id TEXT NOT NULL,
    turn_key TEXT,
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    sha TEXT,
    branch TEXT,
    url TEXT
);
CREATE INDEX IF NOT EXISTS commits_session ON commits(session_id);
CREATE TABLE IF NOT EXISTS file_changes (
    session_id TEXT NOT NULL,
    turn_key TEXT,
    ts INTEGER NOT NULL,
    path TEXT NOT NULL,
    added INTEGER NOT NULL DEFAULT 0,
    removed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS file_changes_session ON file_changes(session_id);
CREATE TABLE IF NOT EXISTS rate_limits (
    ts INTEGER NOT NULL,
    limit_id TEXT NOT NULL,
    window_minutes INTEGER NOT NULL,
    used_percent REAL NOT NULL,
    resets_at INTEGER,
    plan_type TEXT,
    PRIMARY KEY (limit_id, window_minutes, ts)
);
CREATE TABLE IF NOT EXISTS ingested_files (
    path TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    session_id TEXT,
    ingested_at INTEGER NOT NULL
);
"""

CHILD_TABLES = ("turns", "segments", "commits", "file_changes")

SUMMARY_SQL = """
SELECT s.*,
  (SELECT count(*) FROM turns t WHERE t.session_id = s.id) AS turn_count,
  (SELECT count(*) FROM turns t WHERE t.session_id = s.id AND t.prompt_kind = 'human')
      AS prompt_count,
  (SELECT coalesce(sum(input_tokens), 0) FROM turns t WHERE t.session_id = s.id) AS tok_input,
  (SELECT coalesce(sum(output_tokens), 0) FROM turns t WHERE t.session_id = s.id) AS tok_output,
  (SELECT coalesce(sum(cache_read_tokens), 0) FROM turns t WHERE t.session_id = s.id)
      AS tok_cache_read,
  (SELECT coalesce(sum(cache_write_tokens), 0) FROM turns t WHERE t.session_id = s.id)
      AS tok_cache_write,
  (SELECT coalesce(sum(reasoning_tokens), 0) FROM turns t WHERE t.session_id = s.id)
      AS tok_reasoning,
  (SELECT state FROM turns t WHERE t.session_id = s.id ORDER BY seq DESC LIMIT 1)
      AS last_turn_state,
  (SELECT count(*) FROM commits c WHERE c.session_id = s.id AND c.kind = 'commit')
      AS commit_count,
  (SELECT count(DISTINCT path) FROM file_changes f WHERE f.session_id = s.id) AS file_count,
  (SELECT coalesce(sum(added), 0) FROM file_changes f WHERE f.session_id = s.id) AS lines_added,
  (SELECT coalesce(sum(removed), 0) FROM file_changes f WHERE f.session_id = s.id)
      AS lines_removed,
  (SELECT count(*) FROM sessions c WHERE c.parent_id = s.id) AS subagent_count
FROM sessions s
"""


class Store:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # timeout: a scheduled run and a manual/API-triggered run may overlap briefly.
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- writes -------------------------------------------------------------------------

    def save(self, parsed: ParsedSession) -> None:
        s = parsed.session
        with self.conn:
            for table in CHILD_TABLES:
                self.conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (s.id,))
            running = self.conn.execute(
                "SELECT is_running FROM sessions WHERE id = ?", (s.id,)
            ).fetchone()
            self.conn.execute(
                """INSERT OR REPLACE INTO sessions (id, source, native_id, parent_id, is_subagent,
                   title, cwd, project, branch, repo_url, entrypoint, started_at, ended_at,
                   cost_usd, work_state, work_detail, needs_action, is_running, source_path,
                   ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    s.id,
                    s.source,
                    s.native_id,
                    s.parent_id,
                    int(s.is_subagent),
                    s.title,
                    s.cwd,
                    s.project,
                    s.branch,
                    s.repo_url,
                    s.entrypoint,
                    s.started_at,
                    s.ended_at,
                    s.cost_usd,
                    s.work_state,
                    s.work_detail,
                    int(s.needs_action),
                    running[0] if running else 0,
                    s.source_path,
                    int(time.time() * 1000),
                ),
            )
            self.conn.executemany(
                """INSERT OR REPLACE INTO turns VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        s.id,
                        t.key,
                        t.seq,
                        t.started_at,
                        t.ended_at,
                        t.state,
                        t.prompt,
                        t.prompt_kind,
                        t.final_message,
                        t.model,
                        t.tokens.input,
                        t.tokens.output,
                        t.tokens.cache_read,
                        t.tokens.cache_write,
                        t.tokens.reasoning,
                    )
                    for t in parsed.turns
                ],
            )
            self.conn.executemany(
                "INSERT INTO segments VALUES (?, ?, ?)",
                [(s.id, a, b) for a, b in parsed.segments],
            )
            self.conn.executemany(
                "INSERT INTO commits VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(s.id, c.turn_key, c.ts, c.kind, c.sha, c.branch, c.url) for c in parsed.commits],
            )
            self.conn.executemany(
                "INSERT INTO file_changes VALUES (?, ?, ?, ?, ?, ?)",
                [(s.id, f.turn_key, f.ts, f.path, f.added, f.removed) for f in parsed.file_changes],
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO rate_limits VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (r.ts, r.limit_id, r.window_minutes, r.used_percent, r.resets_at, r.plan_type)
                    for r in parsed.rate_limits
                ],
            )

    def needs_ingest(self, path: str, fingerprint: str) -> bool:
        row = self.conn.execute(
            "SELECT fingerprint FROM ingested_files WHERE path = ?", (str(path),)
        ).fetchone()
        return row is None or row[0] != fingerprint

    def mark_ingested(
        self, path: str, source: str, fingerprint: str, session_id: str | None
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO ingested_files VALUES (?, ?, ?, ?, ?)",
                (str(path), source, fingerprint, session_id, int(time.time() * 1000)),
            )

    def set_running(self, source: str, session_ids: set[str]) -> None:
        with self.conn:
            self.conn.execute("UPDATE sessions SET is_running = 0 WHERE source = ?", (source,))
            self.conn.executemany(
                "UPDATE sessions SET is_running = 1 WHERE id = ?", [(i,) for i in session_ids]
            )

    # --- reads --------------------------------------------------------------------------

    def _segments_by_session(self, ids: list[str]) -> dict[str, list[list[int]]]:
        out: dict[str, list[list[int]]] = {i: [] for i in ids}
        if not ids:
            return out
        marks = ",".join("?" * len(ids))
        for row in self.conn.execute(
            f"SELECT session_id, started_at, ended_at FROM segments "
            f"WHERE session_id IN ({marks}) ORDER BY started_at",
            ids,
        ):
            out[row[0]].append([row[1], row[2]])
        return out

    def _models_by_session(self, ids: list[str]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {i: [] for i in ids}
        if not ids:
            return out
        marks = ",".join("?" * len(ids))
        for row in self.conn.execute(
            f"SELECT session_id, model, min(seq) FROM turns WHERE session_id IN ({marks}) "
            f"AND model IS NOT NULL GROUP BY session_id, model ORDER BY min(seq)",
            ids,
        ):
            out[row[0]].append(row[1])
        return out

    def session_summaries(
        self, start_ms: int, end_ms: int, include_subagents: bool = False
    ) -> list[dict]:
        """Sessions with at least one segment overlapping [start_ms, end_ms)."""
        where = [
            "EXISTS (SELECT 1 FROM segments g WHERE g.session_id = s.id "
            "AND g.started_at < ? AND g.ended_at >= ?)"
        ]
        if not include_subagents:
            where.append("s.is_subagent = 0")
        rows = self.conn.execute(
            SUMMARY_SQL + " WHERE " + " AND ".join(where) + " ORDER BY s.started_at",
            (end_ms, start_ms),
        ).fetchall()
        return self._to_summaries(rows)

    def _prompt_times_by_session(self, ids: list[str]) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {i: [] for i in ids}
        if not ids:
            return out
        marks = ",".join("?" * len(ids))
        for row in self.conn.execute(
            f"SELECT session_id, started_at FROM turns WHERE session_id IN ({marks}) "
            f"AND prompt_kind = 'human' ORDER BY started_at",
            ids,
        ):
            out[row[0]].append(row[1])
        return out

    def _to_summaries(self, rows) -> list[dict]:
        ids = [r["id"] for r in rows]
        segments = self._segments_by_session(ids)
        models = self._models_by_session(ids)
        prompt_times = self._prompt_times_by_session(ids)
        out = []
        for r in rows:
            d = dict(r)
            d["tokens"] = {
                k: d.pop(f"tok_{k}")
                for k in ("input", "output", "cache_read", "cache_write", "reasoning")
            }
            for flag in ("is_subagent", "needs_action", "is_running"):
                d[flag] = bool(d[flag])
            d["segments"] = segments[r["id"]]
            d["models"] = models[r["id"]]
            d["prompt_times"] = prompt_times[r["id"]]
            out.append(d)
        return out

    def overview(self) -> dict:
        """Totals across the whole DB (top-level sessions), for empty states."""
        row = self.conn.execute(
            "SELECT count(*), max(ended_at) FROM sessions WHERE is_subagent = 0"
        ).fetchone()
        return {"total_sessions": row[0], "latest_activity_at": row[1]}

    def session_summary(self, session_id: str) -> dict | None:
        rows = self.conn.execute(SUMMARY_SQL + " WHERE s.id = ?", (session_id,)).fetchall()
        return self._to_summaries(rows)[0] if rows else None

    def subagent_summaries(self, parent_id: str) -> list[dict]:
        rows = self.conn.execute(
            SUMMARY_SQL + " WHERE s.parent_id = ? ORDER BY s.started_at", (parent_id,)
        ).fetchall()
        return self._to_summaries(rows)

    def turns(self, session_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM turns WHERE session_id = ? ORDER BY seq", (session_id,)
            )
        ]

    def commits(self, session_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT turn_key, ts, kind, sha, branch, url FROM commits "
                "WHERE session_id = ? ORDER BY ts, rowid",
                (session_id,),
            )
        ]

    def files(self, session_id: str) -> list[dict]:
        """Changed files aggregated per path, in order of first change."""
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT path, sum(added) AS added, sum(removed) AS removed, count(*) AS edits "
                "FROM file_changes WHERE session_id = ? GROUP BY path ORDER BY min(rowid)",
                (session_id,),
            )
        ]

    def token_totals_by_bucket(
        self, source: str, since_ms: int, until_ms: int, bucket_ms: int
    ) -> dict[int, int]:
        """Tokens (input + output + cache) per bucket, attributed to each turn's end time."""
        out: dict[int, int] = {}
        for row in self.conn.execute(
            """SELECT ((t.ended_at - ?) / ?) AS b,
                      sum(t.input_tokens + t.output_tokens + t.cache_read_tokens
                          + t.cache_write_tokens)
               FROM turns t JOIN sessions s ON s.id = t.session_id
               WHERE s.source = ? AND t.ended_at >= ? AND t.ended_at < ?
               GROUP BY b""",
            (since_ms, bucket_ms, source, since_ms, until_ms),
        ):
            out[since_ms + row[0] * bucket_ms] = row[1]
        return out

    def rate_limit_series(self, since_ms: int = 0) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM rate_limits WHERE ts >= ? ORDER BY ts", (since_ms,)
            )
        ]

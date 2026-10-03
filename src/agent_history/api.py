"""HTTP API consumed by the web UI."""

import time
from collections.abc import Callable, Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from agent_history.ingest import Config, IngestReport, ingest_and_log, run_ingest
from agent_history.runlog import health, read_runs
from agent_history.store import Store

H = 3_600_000
CODEX_RUNNING_WITHIN_MS = 10 * 60_000
WINDOW_LABELS = {300: "5H", 10080: "7D"}
TOKEN_KEYS = ("input", "output", "cache_read", "cache_write", "reasoning")


def _total(tokens: dict) -> int:
    # Reasoning is already part of output (Codex) or zero (Claude); cache counts in.
    return tokens["input"] + tokens["output"] + tokens["cache_read"] + tokens["cache_write"]


def overall_status(row: dict, now_ms: int) -> str:
    """running | aborted | completed | incomplete — the pills shown above the calendar."""
    last = row.get("last_turn_state")
    codex_live = (
        row["source"] == "codex"
        and last == "open"
        and now_ms - row["ended_at"] < CODEX_RUNNING_WITHIN_MS
    )
    if row.get("is_running") or codex_live:
        return "running"
    if last == "aborted":
        return "aborted"
    if (
        last in ("completed", None)
        and row.get("work_state") in (None, "completed")
        and not row.get("needs_action")
    ):
        return "completed"
    return "incomplete"


def checks(row: dict, status: str) -> list[dict]:
    """Completion checklist for the detail pane; ok=None means 'cannot tell'."""
    work = row.get("work_state")
    return [
        {
            "key": "turn_ended",
            "label": "ターン終了",
            "ok": status != "running" and row.get("last_turn_state") != "open",
        },
        {"key": "no_pending_reply", "label": "返事待ちなし", "ok": not row.get("needs_action")},
        {"key": "committed", "label": "コミット済み", "ok": row.get("commit_count", 0) > 0},
        {
            "key": "work_completed",
            "label": "作業内容 完了",
            "ok": None if work is None else work == "completed",
        },
    ]


def _present(row: dict, now_ms: int) -> dict:
    row = dict(row)
    row["tokens"]["total"] = _total(row["tokens"])
    row["status"] = overall_status(row, now_ms)
    row.pop("source_path", None)
    return row


def create_app(
    config: Config,
    now: Callable[[], int] = lambda: int(time.time() * 1000),
    ingest: Callable[[Config, Store], IngestReport] = run_ingest,
    static_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="agent-history")

    def get_store() -> Iterator[Store]:
        # One connection per request: endpoints run in a thread pool.
        with Store(config.db_path) as store:
            yield store

    StoreDep = Annotated[Store, Depends(get_store)]

    @app.get("/api/sessions")
    def list_sessions(
        store: StoreDep,
        start: Annotated[int, Query(description="range start, epoch ms")],
        end: Annotated[int, Query(description="range end (exclusive), epoch ms")],
        include_subagents: bool = False,
    ):
        if start >= end:
            raise HTTPException(400, "start must be before end")
        t = now()
        rows = store.session_summaries(start, end, include_subagents=include_subagents)
        return {
            "range": [start, end],
            "now": t,
            "sessions": [_present(r, t) for r in rows],
            **store.overview(),
        }

    @app.get("/api/sessions/{session_id:path}")
    def session_detail(session_id: str, store: StoreDep):
        row = store.session_summary(session_id)
        if row is None:
            raise HTTPException(404, "session not found")
        t = now()
        detail = _present(row, t)
        turns = []
        for turn in store.turns(session_id):
            tokens = {k: turn.pop(f"{k}_tokens") for k in TOKEN_KEYS}
            tokens["total"] = _total(tokens)
            turn.pop("session_id")
            turns.append({**turn, "tokens": tokens})
        detail.update(
            checks=checks(detail, detail["status"]),
            turns=turns,
            commits=store.commits(session_id),
            files=store.files(session_id),
            subagents=[_present(r, t) for r in store.subagent_summaries(session_id)],
        )
        return detail

    @app.get("/api/usage")
    def usage(store: StoreDep):
        t = now()
        week_ago = t - 168 * H
        windows: dict[int, dict] = {}
        for sample in store.rate_limit_series(since_ms=week_ago):
            w = windows.setdefault(
                sample["window_minutes"],
                {
                    "window_minutes": sample["window_minutes"],
                    "label": WINDOW_LABELS.get(
                        sample["window_minutes"], f"{sample['window_minutes']}m"
                    ),
                    "series": [],
                },
            )
            w["series"].append([sample["ts"], sample["used_percent"]])
            w.update(
                as_of=sample["ts"],
                resets_at=sample["resets_at"],
                raw_percent=sample["used_percent"],
                plan_type=sample["plan_type"],
            )
        for w in windows.values():
            # A window that has rolled over since the last sample is back to zero.
            w["reset"] = bool(w["resets_at"] and w["resets_at"] <= t)
            w["used_percent"] = 0.0 if w["reset"] else w["raw_percent"]

        tokens = {}
        hour_start = t - t % H
        first_bucket = hour_start - 167 * H
        for source in ("claude", "codex"):
            buckets = store.token_totals_by_bucket(source, first_bucket, t + 1, H)
            tokens[source] = {
                "last_5h": sum(v for b, v in buckets.items() if b + H > t - 5 * H),
                "last_7d": sum(buckets.values()),
                "hourly": [
                    [first_bucket + i * H, buckets.get(first_bucket + i * H, 0)] for i in range(168)
                ],
            }
        return {
            "now": t,
            "rate_limits": sorted(windows.values(), key=lambda w: w["window_minutes"]),
            "tokens": tokens,
        }

    @app.post("/api/ingest")
    def trigger_ingest():
        try:
            report = ingest_and_log(config, "api", ingest=ingest, now=now)
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {e}") from e
        return {"report": asdict(report)}

    @app.get("/api/health")
    def get_health():
        result = health(read_runs(config.log_dir / "ingest.jsonl"), now())
        result["sources"] = [
            {"name": name, "path": str(path), "exists": path.is_dir()}
            for name, path in config.sources().items()
        ]
        return result

    if static_dir and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app

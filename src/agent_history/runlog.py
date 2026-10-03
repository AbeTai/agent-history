"""Append-only JSON-lines log of ingest runs, and a health verdict derived from it."""

import json
from pathlib import Path

STALE_AFTER_MS = 24 * 3_600_000
MAX_LOG_BYTES = 1_000_000


def record_run(
    log_path: Path,
    *,
    started_at: int,
    duration_ms: int,
    status: str,  # ok | partial | failed
    max_bytes: int = MAX_LOG_BYTES,
    **fields,
) -> None:
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists() and log_path.stat().st_size > max_bytes:
        log_path.replace(log_path.with_name(log_path.name + ".1"))
    entry = {"started_at": started_at, "duration_ms": duration_ms, "status": status, **fields}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_runs(log_path: Path) -> list[dict]:
    log_path = Path(log_path)
    if not log_path.exists():
        return []
    runs = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return runs


def health(runs: list[dict], now_ms: int, stale_after_ms: int = STALE_AFTER_MS) -> dict:
    """ok only if the latest run fully succeeded and a success happened recently."""
    last_success = max((r["started_at"] for r in runs if r.get("status") == "ok"), default=None)
    result = {"ok": False, "reason": None, "last_success_at": last_success}
    if not runs:
        result["reason"] = "取り込みがまだ一度も実行されていません"
        return result
    last = runs[-1]
    if last.get("status") == "failed":
        result["reason"] = f"直近の取り込みが失敗しました: {last.get('error')}"
    elif last.get("status") == "partial":
        result["reason"] = (
            f"直近の取り込みで {len(last.get('failed') or [])} 件のファイルが読めませんでした"
        )
    elif last_success is None or now_ms - last_success > stale_after_ms:
        hours = (now_ms - (last_success or 0)) // 3_600_000
        result["reason"] = f"最後の成功から {hours} 時間経過しています"
    else:
        result["ok"] = True
    return result

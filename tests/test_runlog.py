import json

from agent_history.runlog import health, read_runs, record_run

H = 3_600_000


def test_record_and_read(tmp_path):
    log = tmp_path / "logs" / "ingest.jsonl"
    record_run(log, started_at=1000, duration_ms=120, status="ok", parsed=2, skipped=5)
    record_run(log, started_at=2000, duration_ms=50, status="failed", error="boom")
    runs = read_runs(log)
    assert [r["status"] for r in runs] == ["ok", "failed"]
    assert runs[0]["parsed"] == 2 and runs[1]["error"] == "boom"
    assert all(json.loads(line) for line in log.read_text(encoding="utf-8").splitlines())


def test_read_missing_log(tmp_path):
    assert read_runs(tmp_path / "nope.jsonl") == []


def test_rotation_keeps_one_previous_file(tmp_path):
    log = tmp_path / "ingest.jsonl"
    for i in range(50):
        record_run(log, started_at=i, duration_ms=1, status="ok", max_bytes=500)
    assert log.stat().st_size <= 600
    assert (tmp_path / "ingest.jsonl.1").exists()
    assert read_runs(log)[-1]["started_at"] == 49


def test_health_states():
    now = 100 * H
    assert health([], now)["ok"] is False
    ok = {"started_at": now - H, "status": "ok"}
    assert health([ok], now) == {"ok": True, "reason": None, "last_success_at": now - H}
    stale = {"started_at": now - 30 * H, "status": "ok"}
    assert health([stale], now)["ok"] is False
    assert "30" in health([stale], now)["reason"]
    failed = {"started_at": now - 1000, "status": "failed", "error": "x"}
    result = health([ok, failed], now)
    assert result["ok"] is False and result["last_success_at"] == now - H
    partial = {"started_at": now - 1000, "status": "partial", "failed": [["f", "e"]]}
    assert health([partial], now)["ok"] is False

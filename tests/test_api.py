from pathlib import Path

import pytest
from factories import H, make_parsed
from fastapi.testclient import TestClient

from agent_history.api import create_app
from agent_history.ingest import Config, IngestReport
from agent_history.model import RateLimitSample
from agent_history.runlog import read_runs
from agent_history.store import Store

NOW = 200 * H
MIN = 60_000


def variant(sid, start, last_state="completed", needs_action=False, ended=None, **kw):
    p = make_parsed(sid, start=start, **kw)
    p.rate_limits = []  # usage samples are seeded explicitly below
    p.turns[-1].state = last_state
    p.session.needs_action = needs_action
    if ended is not None:
        p.session.ended_at = ended
        p.turns[-1].ended_at = ended
        p.segments = [(start, ended)]
    return p


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        claude_home=tmp_path / "c",
        claude_desktop=tmp_path / "d",
        codex_home=tmp_path / "x",
        data_home=tmp_path / "data",
    )


@pytest.fixture
def seeded(config):
    with Store(config.db_path) as s:
        s.save(variant("claude:aborted", start=NOW - 30 * H, last_state="aborted"))
        s.save(variant("claude:done", start=NOW - 28 * H))
        s.save(variant("claude:waiting", start=NOW - 26 * H, needs_action=True))
        s.save(variant("claude:recent", start=NOW - 3 * H))
        s.save(variant("codex:live", start=NOW - H, last_state="open", ended=NOW - 5 * MIN))
        s.save(variant("codex:stale", start=NOW - 20 * H, last_state="open", ended=NOW - 19 * H))
        s.save(variant("codex:child", start=NOW - H, subagent=True, parent="codex:live"))
        usage = make_parsed("codex:limits", start=NOW - 400 * H)
        usage.rate_limits = [
            RateLimitSample(
                ts=NOW - 2 * H,
                limit_id="codex",
                window_minutes=300,
                used_percent=30.0,
                resets_at=NOW + H,
                plan_type="plus",
            ),
            RateLimitSample(
                ts=NOW - H,
                limit_id="codex",
                window_minutes=300,
                used_percent=40.0,
                resets_at=NOW + H,
                plan_type="plus",
            ),
            RateLimitSample(
                ts=NOW - H,
                limit_id="codex",
                window_minutes=10080,
                used_percent=60.0,
                resets_at=NOW + 72 * H,
                plan_type="plus",
            ),
        ]
        s.save(usage)
    return config


def client(config, **kw) -> TestClient:
    return TestClient(create_app(config, now=lambda: NOW, **kw))


def get_sessions(c, start=NOW - 48 * H, end=NOW + H, **params):
    r = c.get("/api/sessions", params={"start": start, "end": end, **params})
    assert r.status_code == 200, r.text
    return {s["id"]: s for s in r.json()["sessions"]}


def test_list_derives_overall_status(seeded):
    sessions = get_sessions(client(seeded))
    assert {k: v["status"] for k, v in sessions.items()} == {
        "claude:aborted": "aborted",
        "claude:done": "completed",
        "claude:waiting": "incomplete",
        "claude:recent": "completed",
        "codex:live": "running",
        "codex:stale": "incomplete",
    }


def test_list_rows_carry_calendar_fields(seeded):
    row = get_sessions(client(seeded))["claude:done"]
    assert row["segments"] == [[NOW - 28 * H, NOW - 27 * H], [NOW - 26 * H, NOW - 26 * H]]
    assert row["prompt_times"] == [NOW - 28 * H]
    assert row["tokens"]["total"] == 11 + 22 + 30 + 40
    assert row["project"] == "demo" and row["models"] == ["claude-opus-5", "claude-sonnet-5"]


def test_list_subagents_opt_in(seeded):
    assert "codex:child" not in get_sessions(client(seeded))
    assert "codex:child" in get_sessions(client(seeded), include_subagents="true")
    assert get_sessions(client(seeded))["codex:live"]["subagent_count"] == 1


def test_list_validates_range(seeded):
    c = client(seeded)
    assert c.get("/api/sessions").status_code == 422
    assert c.get("/api/sessions", params={"start": 10, "end": 5}).status_code == 400


def test_detail(seeded):
    r = client(seeded).get("/api/sessions/claude:done")
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == "claude:done" and d["status"] == "completed"
    assert [(t["prompt"], t["prompt_kind"], t["state"]) for t in d["turns"]] == [
        ("やって", "human", "completed"),
        ("/model", "command", "completed"),
    ]
    assert d["turns"][0]["tokens"] == {
        "input": 10,
        "output": 20,
        "cache_read": 30,
        "cache_write": 40,
        "reasoning": 0,
        "total": 100,
    }
    assert [(c["kind"], c["sha"]) for c in d["commits"]] == [("commit", "abc1234"), ("push", None)]
    assert d["files"] == [
        {"path": "/w/demo/a.py", "added": 4, "removed": 1, "edits": 2},
        {"path": "/w/demo/b.py", "added": 2, "removed": 0, "edits": 1},
    ]
    checks = {c["key"]: c["ok"] for c in d["checks"]}
    assert checks == {
        "turn_ended": True,
        "no_pending_reply": True,
        "committed": True,
        "work_completed": None,
    }


def test_detail_checks_reflect_waiting_and_open(seeded):
    c = client(seeded)
    waiting = {x["key"]: x["ok"] for x in c.get("/api/sessions/claude:waiting").json()["checks"]}
    assert waiting["no_pending_reply"] is False
    live = {x["key"]: x["ok"] for x in c.get("/api/sessions/codex:live").json()["checks"]}
    assert live["turn_ended"] is False


def test_detail_lists_subagents_and_404(seeded):
    c = client(seeded)
    subs = c.get("/api/sessions/codex:live").json()["subagents"]
    assert [s["id"] for s in subs] == ["codex:child"]
    assert c.get("/api/sessions/claude:nope").status_code == 404


def test_usage(seeded):
    u = client(seeded).get("/api/usage").json()
    windows = {w["window_minutes"]: w for w in u["rate_limits"]}
    assert windows[300]["used_percent"] == 40.0
    assert windows[300]["label"] == "5H"
    assert windows[300]["series"] == [[NOW - 2 * H, 30.0], [NOW - H, 40.0]]
    assert windows[10080]["label"] == "7D" and windows[10080]["used_percent"] == 60.0
    claude = u["tokens"]["claude"]
    # Turn ends: claude:recent ends within 5h; every claude session ends within 7d.
    assert claude["last_5h"] == 103
    assert claude["last_7d"] == 4 * 103
    assert len(claude["hourly"]) == 168 and claude["hourly"][-1][0] <= NOW


def test_usage_window_already_reset_reads_zero(config):
    with Store(config.db_path) as s:
        p = make_parsed("codex:x", start=NOW - 10 * H)
        p.rate_limits = [
            RateLimitSample(
                ts=NOW - 6 * H,
                limit_id="codex",
                window_minutes=300,
                used_percent=90.0,
                resets_at=NOW - H,
            )
        ]
        s.save(p)
    [w] = client(config).get("/api/usage").json()["rate_limits"]
    assert w["used_percent"] == 0 and w["reset"] is True


def test_ingest_endpoint_logs_run(seeded):
    called = []

    def fake_ingest(cfg, store):
        called.append(cfg)
        return IngestReport(parsed=3, skipped=4)

    r = client(seeded, ingest=fake_ingest).post("/api/ingest")
    assert r.status_code == 200
    assert r.json()["report"]["parsed"] == 3
    assert called
    [run] = read_runs(seeded.log_dir / "ingest.jsonl")
    assert run["trigger"] == "api" and run["status"] == "ok"


def test_ingest_endpoint_failure(seeded):
    def boom(cfg, store):
        raise OSError("disk full")

    r = client(seeded, ingest=boom).post("/api/ingest")
    assert r.status_code == 500
    assert "disk full" in r.json()["detail"]
    assert read_runs(seeded.log_dir / "ingest.jsonl")[-1]["status"] == "failed"


def test_health(seeded):
    h = client(seeded).get("/api/health").json()
    assert h["ok"] is False  # nothing logged yet
    client(seeded, ingest=lambda c, s: IngestReport()).post("/api/ingest")
    assert client(seeded).get("/api/health").json()["ok"] is True


def test_list_reports_overall_totals_for_empty_states(seeded, config):
    body = client(seeded).get("/api/sessions", params={"start": 0, "end": 1}).json()
    assert body["sessions"] == []
    assert body["total_sessions"] == 7  # subagents excluded
    assert body["latest_activity_at"] == NOW - 5 * MIN


def test_health_lists_history_sources(config, tmp_path):
    (config.codex_home / "sessions").mkdir(parents=True)
    sources = {s["name"]: s for s in client(config).get("/api/health").json()["sources"]}
    assert sources["codex"]["exists"] is True
    assert sources["claude"]["exists"] is False
    assert sources["claude"]["path"].endswith("projects")


def test_compactions_in_list_and_detail(seeded):
    c = client(seeded)
    row = get_sessions(c)["claude:done"]
    assert row["compaction_count"] == 1
    assert row["compaction_marks"] == [[NOW - 28 * H + H // 2, "auto"]]
    detail = c.get("/api/sessions/claude:done").json()
    assert detail["compactions"][0]["trigger"] == "auto"
    assert detail["compactions"][0]["pre_tokens"] == 900_000

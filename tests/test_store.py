from pathlib import Path

import pytest
from factories import H, make_parsed

from agent_history.store import Store


@pytest.fixture
def store(tmp_path: Path):
    s = Store(tmp_path / "h.db")
    yield s
    s.close()


def test_summary_aggregates(store):
    store.save(make_parsed())
    [row] = store.session_summaries(0, 100 * H)
    assert row["id"] == "claude:a"
    assert row["prompt_count"] == 1  # commands are not requests
    assert row["turn_count"] == 2
    assert row["commit_count"] == 1
    assert row["file_count"] == 2
    assert row["lines_added"] == 6 and row["lines_removed"] == 1
    assert row["tokens"] == {
        "input": 11,
        "output": 22,
        "cache_read": 30,
        "cache_write": 40,
        "reasoning": 3,
    }
    assert row["models"] == ["claude-opus-5", "claude-sonnet-5"]
    assert row["last_turn_state"] == "aborted"
    assert row["segments"] == [[10 * H, 11 * H], [12 * H, 12 * H]]
    assert row["cost_usd"] == 1.5
    assert row["is_subagent"] is False


def test_save_is_idempotent(store):
    store.save(make_parsed())
    store.save(make_parsed())
    [row] = store.session_summaries(0, 100 * H)
    assert row["turn_count"] == 2
    assert row["commit_count"] == 1
    assert len(store.rate_limit_series()) == 1


def test_range_filter_uses_segments(store):
    store.save(make_parsed("claude:a", start=10 * H))
    store.save(make_parsed("claude:b", start=50 * H))
    assert [r["id"] for r in store.session_summaries(9 * H, 11 * H)] == ["claude:a"]
    # Gap between a's two segments (11h-12h) overlaps nothing.
    assert store.session_summaries(int(11.2 * H), int(11.8 * H)) == []


def test_subagents_hidden_unless_requested(store):
    store.save(make_parsed("codex:p"))
    store.save(make_parsed("codex:c", subagent=True, parent="codex:p"))
    assert [r["id"] for r in store.session_summaries(0, 100 * H)] == ["codex:p"]
    ids = {r["id"] for r in store.session_summaries(0, 100 * H, include_subagents=True)}
    assert ids == {"codex:p", "codex:c"}
    [parent] = store.session_summaries(0, 100 * H)
    assert parent["subagent_count"] == 1


def test_fingerprint_tracking(store):
    assert store.needs_ingest("/src/x.jsonl", "10:1")
    store.mark_ingested("/src/x.jsonl", "claude", "10:1", "claude:x")
    assert not store.needs_ingest("/src/x.jsonl", "10:1")
    assert store.needs_ingest("/src/x.jsonl", "11:2")


def test_running_flag(store):
    store.save(make_parsed("claude:a"))
    store.save(make_parsed("claude:b"))
    store.set_running("claude", {"claude:b"})
    flags = {r["id"]: r["is_running"] for r in store.session_summaries(0, 100 * H)}
    assert flags == {"claude:a": False, "claude:b": True}
    store.set_running("claude", set())
    assert not any(r["is_running"] for r in store.session_summaries(0, 100 * H))


def test_reopen_keeps_data(tmp_path):
    s = Store(tmp_path / "h.db")
    s.save(make_parsed())
    s.close()
    s2 = Store(tmp_path / "h.db")
    assert len(s2.session_summaries(0, 100 * H)) == 1
    s2.close()

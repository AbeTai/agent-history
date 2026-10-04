import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_history.sources.codex import load_thread_names, parse_codex_rollout

FIXTURES = Path(__file__).parent / "fixtures" / "codex"
DAY = FIXTURES / "sessions" / "2026" / "09" / "28"
T1 = "019faaaa-0000-7000-8000-000000000001"
T2 = "019faaaa-0000-7000-8000-000000000002"
TOP = DAY / f"rollout-2026-09-28T10-00-00-{T1}.jsonl"
SUB = DAY / f"rollout-2026-09-28T10-30-00-{T2}.jsonl"


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=UTC).timestamp() * 1000)


@pytest.fixture(scope="module")
def top():
    return parse_codex_rollout(TOP, names=load_thread_names(FIXTURES / "session_index.jsonl"))


@pytest.fixture(scope="module")
def sub():
    return parse_codex_rollout(SUB)


def test_session_metadata(top):
    s = top.session
    assert s.id == f"codex:{T1}"
    assert s.source == "codex"
    assert s.parent_id is None
    assert s.cwd == "/Users/me/dev/demo"
    assert s.project == "demo"
    assert s.branch == "main"
    assert s.repo_url == "git@github.com:me/demo.git"
    assert s.entrypoint == "Codex Desktop"
    assert s.started_at == ms("2026-09-28T01:00:00")
    assert s.ended_at == ms("2026-09-28T03:01:00")


def test_latest_thread_name_is_title(top):
    assert top.session.title == "README 更新"


def test_turns_and_states(top):
    assert [(t.prompt, t.state) for t in top.turns] == [
        ("README を更新して", "completed"),
        ("[設計メモ](chatgpt-conversation://abc) これやって", "aborted"),
    ]
    first = top.turns[0]
    assert first.model == "gpt-6-sol"
    assert first.final_message == "更新しました"
    assert (first.started_at, first.ended_at) == (
        ms("2026-09-28T01:00:00"),
        ms("2026-09-28T01:00:45"),
    )


def test_tokens_sum_last_usage_skipping_repeated_totals(top):
    t = top.turns[0].tokens
    # (100 in / 80 cached / 10 out / 4 reasoning) + (200 / 120 / 20 / 6); duplicate event ignored.
    # Codex input_tokens include cached ones: input is reported net of cache reads.
    assert (t.input, t.cache_read, t.output, t.reasoning) == (100, 200, 30, 10)


def test_successful_commits_only(top):
    assert [(c.kind, c.sha) for c in top.commits] == [("commit", "abc9999")]
    assert top.commits[0].turn_key == top.turns[0].key


def test_file_changes(top):
    assert [(f.path, f.added, f.removed) for f in top.file_changes] == [
        ("/Users/me/dev/demo/README.md", 2, 1)
    ]


def test_segments(top):
    assert top.segments == [
        (ms("2026-09-28T01:00:00"), ms("2026-09-28T01:00:45")),
        (ms("2026-09-28T03:00:00"), ms("2026-09-28T03:01:00")),
    ]


def test_rate_limit_samples(top):
    samples = {(r.window_minutes, r.used_percent) for r in top.rate_limits}
    assert samples == {(300, 20.0), (300, 22.0), (10080, 50.0)}
    assert all(r.plan_type == "plus" for r in top.rate_limits)


def test_subagent_links_to_parent_and_uses_nickname(sub):
    assert sub.session.parent_id == f"codex:{T1}"
    assert sub.session.title == "Euler: 原因を調べて"


def test_subagent_drops_inherited_turns(sub):
    # The copied parent turn started before the subagent existed.
    assert [t.prompt for t in sub.turns] == ["原因を調べて"]
    assert sub.session.started_at == ms("2026-09-28T01:30:01")


def test_subagent_tokens_ignore_inherited_running_total(sub):
    t = sub.turns[0].tokens
    assert (t.input, t.cache_read, t.output) == (40, 0, 10)


def test_rollout_without_turn_events_gets_implicit_turn(tmp_path):
    rec = [
        {
            "timestamp": "2026-08-01T00:00:00.000Z",
            "type": "session_meta",
            "payload": {"id": "x", "timestamp": "2026-08-01T00:00:00.000Z", "cwd": "/tmp/x"},
        },
        {
            "timestamp": "2026-08-01T00:00:05.000Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": []},
        },
    ]
    f = tmp_path / "rollout-x.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rec), encoding="utf-8")
    parsed = parse_codex_rollout(f)
    assert len(parsed.turns) == 1
    assert parsed.turns[0].prompt is None
    assert parsed.segments == [(ms("2026-08-01T00:00:05"), ms("2026-08-01T00:00:05"))]


def test_file_without_session_meta_returns_none(tmp_path):
    f = tmp_path / "rollout-y.jsonl"
    f.write_text("", encoding="utf-8")
    assert parse_codex_rollout(f) is None


def test_subagent_flag(top, sub):
    assert top.session.is_subagent is False
    assert sub.session.is_subagent is True


def test_compaction_inferred_auto_with_context_size_and_duration(top):
    [c] = top.compactions
    assert c.ts == ms("2026-09-28T01:00:41")
    assert c.trigger == "auto"  # Codex records no trigger; no /compact request in this turn
    assert c.pre_tokens == 200  # input tokens of the last response before compacting
    assert c.post_tokens is None
    assert c.duration_ms == 30_000
    assert c.turn_key == top.turns[0].key


def test_compaction_after_a_compact_request_is_manual(tmp_path):
    rec = [
        {
            "timestamp": "2026-08-01T00:00:00.000Z",
            "type": "session_meta",
            "payload": {"id": "m", "timestamp": "2026-08-01T00:00:00.000Z", "cwd": "/tmp/m"},
        },
        {
            "timestamp": "2026-08-01T00:00:01.000Z",
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "t1", "started_at": 1785542401},
        },
        {
            "timestamp": "2026-08-01T00:00:01.000Z",
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": "m",
                "turn_id": "t1",
                "item": {"type": "UserMessage", "content": [{"type": "text", "text": "/compact"}]},
            },
        },
        {"timestamp": "2026-08-01T00:00:09.000Z", "type": "compacted", "payload": {"message": ""}},
    ]
    f = tmp_path / "rollout-m.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rec), encoding="utf-8")
    [c] = parse_codex_rollout(f).compactions
    assert c.trigger == "manual"


def test_inherited_compactions_are_dropped(sub):
    assert sub.compactions == []

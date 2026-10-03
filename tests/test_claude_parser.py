from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_history.sources.claude import (
    load_desktop_meta,
    parse_claude_session,
    running_claude_sessions,
)

FIXTURES = Path(__file__).parent / "fixtures" / "claude"
SID = "11111111-1111-4111-8111-111111111111"
SESSION_FILE = FIXTURES / "projects" / "-Users-me-dev-demo" / f"{SID}.jsonl"


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=UTC).timestamp() * 1000)


@pytest.fixture(scope="module")
def parsed():
    return parse_claude_session(SESSION_FILE)


def test_session_metadata(parsed):
    s = parsed.session
    assert s.id == f"claude:{SID}"
    assert s.source == "claude"
    assert s.native_id == SID
    assert s.cwd == "/Users/me/dev/demo"
    assert s.project == "demo"
    assert s.branch == "main"
    assert s.entrypoint == "claude-desktop"
    assert s.started_at == ms("2026-09-28T01:00:00")
    assert s.ended_at == ms("2026-09-28T02:11:00")
    assert s.cost_usd == pytest.approx(1.23)
    assert s.source_path == str(SESSION_FILE)


def test_custom_title_wins_over_ai_title(parsed):
    assert parsed.session.title == "README 改修"


def test_turns_start_at_human_prompts_only(parsed):
    prompts = [(t.prompt, t.prompt_kind) for t in parsed.turns]
    assert prompts == [
        ("README を直して", "human"),
        ("/model", "command"),
        ("次はテストを追加", "human"),
    ]
    assert [t.seq for t in parsed.turns] == [0, 1, 2]


def test_turn_states(parsed):
    assert [t.state for t in parsed.turns] == ["completed", "completed", "aborted"]


def test_task_notification_continues_previous_turn(parsed):
    first = parsed.turns[0]
    assert first.ended_at == ms("2026-09-28T01:05:05")
    assert first.final_message == "バックグラウンド処理も完了しました。"


def test_tokens_dedupe_by_message_id(parsed):
    first = parsed.turns[0]
    # m1 counted once (10/5/100/20) + m2 (1/2/3/4) + m3 (1/1/0/0) + m4 (1/1/0/0)
    assert first.tokens.input == 13
    assert first.tokens.output == 9
    assert first.tokens.cache_read == 103
    assert first.tokens.cache_write == 24
    assert first.model == "claude-opus-5"
    assert parsed.turns[2].model == "claude-sonnet-5"


def test_commits_from_git_operation_and_pr_link(parsed):
    commits = [(c.kind, c.sha, c.branch, c.turn_key) for c in parsed.commits]
    first_key = parsed.turns[0].key
    assert ("commit", "abc1234", "main", first_key) in commits
    assert any(
        c.kind == "pr" and c.url == "https://github.com/me/demo/pull/7" for c in parsed.commits
    )


def test_file_changes(parsed):
    assert [(f.path, f.added, f.removed) for f in parsed.file_changes] == [
        ("/Users/me/dev/demo/README.md", 1, 1)
    ]


def test_segments_split_on_idle_gap(parsed):
    assert parsed.segments == [
        (ms("2026-09-28T01:00:00"), ms("2026-09-28T01:05:05")),
        (ms("2026-09-28T02:00:00"), ms("2026-09-28T02:11:00")),
    ]


def test_waiting_for_answer_is_flagged(parsed):
    # Last tool call was AskUserQuestion, so the user still owes a reply.
    assert parsed.session.needs_action is True


def test_desktop_meta_supplies_work_state():
    meta = load_desktop_meta(FIXTURES / "desktop")
    assert SID in meta
    parsed = parse_claude_session(SESSION_FILE, desktop=meta[SID])
    assert parsed.session.work_state == "completed"
    assert parsed.session.work_detail == "README 修正とコミット完了"


def test_running_sessions_require_live_pid():
    assert running_claude_sessions(FIXTURES / "sessions", pid_alive=lambda pid: pid == 4242) == {
        SID
    }
    assert running_claude_sessions(FIXTURES / "sessions", pid_alive=lambda pid: False) == set()


def test_missing_dirs_are_tolerated(tmp_path):
    assert load_desktop_meta(tmp_path / "nope") == {}
    assert running_claude_sessions(tmp_path / "nope") == set()


def test_empty_session_file_returns_none(tmp_path):
    f = tmp_path / "x.jsonl"
    f.write_text('{"type":"ai-title","aiTitle":"t","sessionId":"x"}\n', encoding="utf-8")
    assert parse_claude_session(f) is None


def test_commit_detected_from_command_when_git_operation_missing(tmp_path):
    lines = [
        {
            "type": "user",
            "timestamp": "2026-09-28T01:00:00Z",
            "uuid": "p1",
            "cwd": "/x",
            "message": {"role": "user", "content": "commit して"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-09-28T01:00:01Z",
            "uuid": "a1",
            "message": {
                "id": "m1",
                "model": "claude-opus-5",
                "stop_reason": "tool_use",
                "usage": {},
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Bash",
                        "input": {"command": "git commit -q -m x && git log --oneline -1"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "timestamp": "2026-09-28T01:00:02Z",
            "uuid": "r1",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "bac57c2 x"}],
            },
            "toolUseResult": {"stdout": "bac57c2 x", "stderr": "", "interrupted": False},
        },
        {
            "type": "assistant",
            "timestamp": "2026-09-28T01:00:03Z",
            "uuid": "a2",
            "message": {
                "id": "m2",
                "model": "claude-opus-5",
                "stop_reason": "tool_use",
                "usage": {},
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "Bash",
                        "input": {"command": "git commit -m y"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "timestamp": "2026-09-28T01:00:04Z",
            "uuid": "r2",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t2",
                        "is_error": True,
                        "content": "nothing to commit",
                    }
                ],
            },
            "toolUseResult": "Error: nothing to commit",
        },
    ]
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(__import__("json").dumps(x) for x in lines), encoding="utf-8")
    parsed = parse_claude_session(f)
    assert [(c.kind, c.sha) for c in parsed.commits] == [("commit", "bac57c2")]


def test_duplicate_commit_sha_counted_once(tmp_path):
    import json

    def bash(i, cmd, out):
        return [
            {
                "type": "assistant",
                "timestamp": f"2026-09-28T01:00:{i:02d}Z",
                "uuid": f"a{i}",
                "message": {
                    "id": f"m{i}",
                    "stop_reason": "tool_use",
                    "usage": {},
                    "content": [
                        {
                            "type": "tool_use",
                            "id": f"t{i}",
                            "name": "Bash",
                            "input": {"command": cmd},
                        }
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": f"2026-09-28T01:00:{i:02d}Z",
                "uuid": f"r{i}",
                "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}"}]},
                "toolUseResult": {"stdout": out},
            },
        ]

    lines = [
        {
            "type": "user",
            "timestamp": "2026-09-28T01:00:00Z",
            "uuid": "p",
            "message": {"content": "go"},
        }
    ]
    lines += bash(1, "git commit -m a", "[main aaa1111] a")
    lines += bash(2, "git commit -m b; git log --oneline -1", "aaa1111 a")
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    assert [c.sha for c in parse_claude_session(f).commits] == ["aaa1111"]

"""Builders for ParsedSession test data."""

from agent_history.model import (
    Commit,
    FileChange,
    ParsedSession,
    RateLimitSample,
    Session,
    Tokens,
    Turn,
)

H = 3_600_000


def make_parsed(sid="claude:a", start=10 * H, subagent=False, parent=None) -> ParsedSession:
    session = Session(
        id=sid,
        source=sid.split(":")[0],
        native_id=sid.split(":")[1],
        cwd="/w/demo",
        project="demo",
        started_at=start,
        ended_at=start + 2 * H,
        source_path=f"/src/{sid}.jsonl",
        title="T",
        branch="main",
        is_subagent=subagent,
        parent_id=parent,
        cost_usd=1.5,
    )
    turns = [
        Turn(
            key="t1",
            seq=0,
            started_at=start,
            ended_at=start + H,
            state="completed",
            prompt="やって",
            prompt_kind="human",
            model="claude-opus-5",
            tokens=Tokens(input=10, output=20, cache_read=30, cache_write=40),
        ),
        Turn(
            key="t2",
            seq=1,
            started_at=start + 2 * H,
            ended_at=start + 2 * H,
            state="aborted",
            prompt="/model",
            prompt_kind="command",
            model="claude-sonnet-5",
            tokens=Tokens(input=1, output=2, reasoning=3),
        ),
    ]
    return ParsedSession(
        session=session,
        turns=turns,
        segments=[(start, start + H), (start + 2 * H, start + 2 * H)],
        commits=[
            Commit(kind="commit", ts=start, turn_key="t1", sha="abc1234"),
            Commit(kind="push", ts=start, turn_key="t1"),
        ],
        file_changes=[
            FileChange(path="/w/demo/a.py", ts=start, turn_key="t1", added=3, removed=1),
            FileChange(path="/w/demo/a.py", ts=start, turn_key="t1", added=1),
            FileChange(path="/w/demo/b.py", ts=start, turn_key="t1", added=2),
        ],
        rate_limits=[
            RateLimitSample(ts=start, limit_id="codex", window_minutes=300, used_percent=12.0)
        ],
    )

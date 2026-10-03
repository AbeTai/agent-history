"""Parse Codex rollout transcripts (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl)."""

import json
from collections.abc import Iterator
from pathlib import Path

from agent_history.diffstat import count_unified_diff
from agent_history.gitdetect import extract_commit_sha, is_commit_command
from agent_history.model import (
    Commit,
    FileChange,
    ParsedSession,
    RateLimitSample,
    Session,
    Tokens,
    Turn,
)
from agent_history.project import project_name
from agent_history.segments import DEFAULT_GAP_MS, split_segments
from agent_history.timeutil import iso_to_ms

MY_REQUEST = "## My request:"
# A copied (inherited) turn keeps its original start time, which precedes the fork.
INHERITED_SLACK_MS = 1000


def _read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_thread_names(path: Path) -> dict[str, str]:
    """Latest thread_name per thread id from ~/.codex/session_index.jsonl."""
    path = Path(path)
    names: dict[str, str] = {}
    if not path.is_file():
        return names
    for rec in _read_jsonl(path):
        if rec.get("id") and rec.get("thread_name"):
            names[rec["id"]] = rec["thread_name"]
    return names


def _clean_prompt(content: list | None) -> str | None:
    text = "\n".join(b.get("text", "") for b in content or [] if b.get("type") == "text").strip()
    if MY_REQUEST in text:  # ChatGPT-conversation hand-offs prepend a large preview
        text = text.split(MY_REQUEST, 1)[1].strip()
    return text or None


def _agent_text(content: list | None) -> str | None:
    text = "\n".join(
        b.get("text", "") for b in content or [] if b.get("type") in ("Text", "text", "output_text")
    ).strip()
    return text or None


def _usage(u: dict) -> Tokens:
    cached = u.get("cached_input_tokens") or 0
    return Tokens(
        input=max((u.get("input_tokens") or 0) - cached, 0),
        output=u.get("output_tokens") or 0,
        cache_read=cached,
        cache_write=u.get("cache_write_input_tokens") or 0,
        reasoning=u.get("reasoning_output_tokens") or 0,
    )


def _parent_of(meta: dict) -> str | None:
    if meta.get("parent_thread_id"):
        return meta["parent_thread_id"]
    source = meta.get("source")
    if isinstance(source, dict):
        spawn = (source.get("subagent") or {}).get("thread_spawn") or {}
        return spawn.get("parent_thread_id")
    return None


def parse_codex_rollout(
    path: Path, names: dict[str, str] | None = None, gap_ms: int = DEFAULT_GAP_MS
) -> ParsedSession | None:
    path = Path(path)
    meta: dict | None = None
    created_ms = 0
    turns: list[Turn] = []
    commits: list[Commit] = []
    files: list[FileChange] = []
    rate_limits: list[RateLimitSample] = []
    last_rate: dict[tuple[str, int], float] = {}
    points: list[int] = []
    current: Turn | None = None
    inherited = False
    last_total: int | None = None

    def own_turn(ts: int) -> Turn:
        nonlocal current
        if current is None:
            current = Turn(
                key=f"{path.stem}:implicit{len(turns)}", seq=len(turns), started_at=ts, ended_at=ts
            )
            turns.append(current)
        return current

    for rec in _read_jsonl(path):
        rtype = rec.get("type")
        payload = rec.get("payload") or {}
        if rtype == "session_meta":
            if meta is None:
                meta = payload
                created_ms = (
                    iso_to_ms(payload.get("timestamp")) or iso_to_ms(rec.get("timestamp")) or 0
                )
            continue
        if meta is None:
            continue
        ts = iso_to_ms(rec.get("timestamp"))
        if ts is None:
            continue
        ptype = payload.get("type")

        if rtype == "event_msg" and ptype == "task_started":
            started = payload.get("started_at")
            started_ms = started * 1000 if isinstance(started, (int, float)) else ts
            inherited = started_ms < created_ms - INHERITED_SLACK_MS
            current = None
            if inherited:
                continue
            current = Turn(
                key=payload.get("turn_id") or f"{path.stem}:{len(turns)}",
                seq=len(turns),
                started_at=ts,
                ended_at=ts,
            )
            turns.append(current)
            points.append(ts)
            continue
        if inherited:
            continue

        if rtype == "turn_context":
            if payload.get("model"):
                own_turn(ts).model = payload["model"]
            continue
        if rtype not in ("event_msg", "response_item"):
            continue

        turn = own_turn(ts)
        turn.ended_at = max(turn.ended_at, ts)
        points.append(ts)

        if rtype != "event_msg":
            continue
        if ptype == "item_completed":
            item = payload.get("item") or {}
            itype = item.get("type")
            if itype == "UserMessage" and turn.prompt is None:
                turn.prompt = _clean_prompt(item.get("content"))
                turn.prompt_kind = "human" if turn.prompt else None
            elif itype == "AgentMessage":
                turn.final_message = _agent_text(item.get("content")) or turn.final_message
            elif itype == "CommandExecution":
                cmd = item.get("command")
                cmd = " ".join(cmd) if isinstance(cmd, list) else (cmd or "")
                if is_commit_command(cmd) and str(item.get("exit_code")) == "0":
                    sha = extract_commit_sha(item.get("aggregated_output") or item.get("stdout"))
                    commits.append(Commit(kind="commit", ts=ts, turn_key=turn.key, sha=sha))
            elif itype == "FileChange":
                for fpath, change in (item.get("changes") or {}).items():
                    added, removed = count_unified_diff((change or {}).get("unified_diff"))
                    files.append(
                        FileChange(
                            path=fpath, ts=ts, turn_key=turn.key, added=added, removed=removed
                        )
                    )
        elif ptype == "token_count":
            info = payload.get("info") or {}
            total = (info.get("total_token_usage") or {}).get("total_tokens")
            if total is not None and total != last_total:
                turn.tokens.add(_usage(info.get("last_token_usage") or {}))
                last_total = total
            limits = payload.get("rate_limits") or {}
            for window in ("primary", "secondary"):
                w = limits.get(window) or {}
                if w.get("used_percent") is None or w.get("window_minutes") is None:
                    continue
                key = (limits.get("limit_id") or "codex", int(w["window_minutes"]))
                if last_rate.get(key) == w["used_percent"]:
                    continue
                last_rate[key] = w["used_percent"]
                resets = w.get("resets_at")
                rate_limits.append(
                    RateLimitSample(
                        ts=ts,
                        limit_id=key[0],
                        window_minutes=key[1],
                        used_percent=float(w["used_percent"]),
                        resets_at=int(resets * 1000) if isinstance(resets, (int, float)) else None,
                        plan_type=limits.get("plan_type"),
                    )
                )
        elif ptype == "task_complete":
            turn.state = "completed"
            turn.final_message = payload.get("last_agent_message") or turn.final_message
        elif ptype == "turn_aborted":
            turn.state = "aborted"

    if meta is None or not points:
        return None

    native_id = meta.get("id") or path.stem
    parent = _parent_of(meta)
    is_subagent = meta.get("thread_source") == "subagent" or parent is not None
    git = meta.get("git") or {}
    source = meta.get("source")
    first_prompt = next((t.prompt for t in turns if t.prompt), None)
    title = (names or {}).get(native_id)
    if not title and first_prompt:
        title = first_prompt[:80]
        if is_subagent and meta.get("agent_nickname"):
            title = f"{meta['agent_nickname']}: {title}"
    session = Session(
        id=f"codex:{native_id}",
        source="codex",
        native_id=native_id,
        cwd=meta.get("cwd"),
        project=project_name(meta.get("cwd")),
        started_at=min(points),
        ended_at=max(points),
        source_path=str(path),
        title=title,
        parent_id=f"codex:{parent}" if parent else None,
        is_subagent=is_subagent,
        branch=git.get("branch"),
        repo_url=git.get("repository_url"),
        entrypoint=meta.get("originator") or (source if isinstance(source, str) else None),
    )
    return ParsedSession(
        session=session,
        turns=turns,
        segments=split_segments(points, gap_ms),
        commits=commits,
        file_changes=files,
        rate_limits=rate_limits,
    )

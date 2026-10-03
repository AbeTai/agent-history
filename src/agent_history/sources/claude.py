"""Parse Claude Code session transcripts (~/.claude/projects/<cwd>/<sessionId>.jsonl)."""

import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path

from agent_history.diffstat import count_structured_patch
from agent_history.gitdetect import extract_commit_sha, is_commit_command
from agent_history.model import Commit, FileChange, ParsedSession, Session, Tokens, Turn
from agent_history.platforms import is_pid_alive
from agent_history.project import project_name
from agent_history.segments import DEFAULT_GAP_MS, split_segments
from agent_history.timeutil import iso_to_ms

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
ASK_TOOLS = {"AskUserQuestion", "ExitPlanMode"}
INTERRUPT_PREFIX = "[Request interrupted by user"
NOISE_TAGS = re.compile(
    r"<(ide_opened_file|ide_selection|system-reminder|local-command-caveat)>.*?</\1>", re.S
)
COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.S)
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)


def _read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # a partially written trailing line


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
    return ""


def _classify_user(rec: dict) -> tuple[str, str | None] | None:
    """Return (kind, text) for a user record that is not a tool result.

    kind: "human" | "command" | "interrupt" | "other" (system-originated, continues the turn).
    """
    if rec.get("toolUseResult") is not None or rec.get("isMeta"):
        return None
    content = rec.get("message", {}).get("content")
    if isinstance(content, list) and content and content[0].get("type") == "tool_result":
        return None
    raw = _text_of(content)
    if raw.lstrip().startswith(INTERRUPT_PREFIX):
        return "interrupt", None
    origin = rec.get("origin") or {}
    if origin.get("kind") not in (None, "human"):
        return "other", None
    if m := COMMAND_NAME.search(raw):
        args = COMMAND_ARGS.search(raw)
        cmd = m.group(1).strip()
        if args and args.group(1).strip():
            cmd = f"{cmd} {args.group(1).strip()}"
        return "command", cmd
    text = NOISE_TAGS.sub("", raw).strip()
    if not text:
        return "other", None
    return "human", text


def _usage_tokens(usage: dict) -> Tokens:
    return Tokens(
        input=usage.get("input_tokens") or 0,
        output=usage.get("output_tokens") or 0,
        cache_read=usage.get("cache_read_input_tokens") or 0,
        cache_write=usage.get("cache_creation_input_tokens") or 0,
    )


def parse_claude_session(
    path: Path, desktop: dict | None = None, gap_ms: int = DEFAULT_GAP_MS
) -> ParsedSession | None:
    path = Path(path)
    native_id = path.stem
    turns: list[Turn] = []
    commits: list[Commit] = []
    files: list[FileChange] = []
    points: list[int] = []
    seen_message_ids: set[str] = set()
    bash_commands: dict[str, str] = {}
    meta: dict = {}
    custom_title = ai_title = None
    cost = None
    last_stop: str | None = None
    last_tool: str | None = None

    def current_turn(ts: int, key: str) -> Turn:
        if not turns:  # activity before any human prompt (e.g. a resumed session)
            turns.append(Turn(key=key, seq=0, started_at=ts, ended_at=ts))
        return turns[-1]

    for rec in _read_jsonl(path):
        rtype = rec.get("type")
        if rtype == "custom-title":
            custom_title = rec.get("customTitle") or custom_title
        elif rtype == "ai-title":
            ai_title = rec.get("aiTitle") or ai_title
        elif rtype == "cost-state":
            cost = rec.get("totalCostUSD", cost)
        elif rtype == "pr-link":
            pr_ts = iso_to_ms(rec.get("timestamp")) or 0
            commits.append(
                Commit(
                    kind="pr",
                    ts=pr_ts,
                    turn_key=turns[-1].key if turns else None,
                    url=rec.get("prUrl"),
                )
            )
        if rtype not in ("user", "assistant"):
            continue

        ts = iso_to_ms(rec.get("timestamp"))
        if ts is None or rec.get("isMeta"):
            continue
        for k in ("cwd", "gitBranch", "entrypoint"):
            if rec.get(k) and k not in meta:
                meta[k] = rec[k]
        points.append(ts)

        if rtype == "user":
            classified = _classify_user(rec)
            if classified is not None:
                kind, text = classified
                if kind in ("human", "command"):
                    turns.append(
                        Turn(
                            key=rec.get("uuid") or f"{native_id}:{len(turns)}",
                            seq=len(turns),
                            started_at=ts,
                            ended_at=ts,
                            prompt=text,
                            prompt_kind=kind,
                            state="completed" if kind == "command" else "open",
                        )
                    )
                    last_stop = last_tool = None
                    continue
                turn = current_turn(ts, rec.get("uuid") or native_id)
                turn.ended_at = ts
                if kind == "interrupt":
                    turn.state = "aborted"
                continue

            # Tool result: harvest commits and file edits.
            turn = current_turn(ts, rec.get("uuid") or native_id)
            turn.ended_at = ts
            result = rec.get("toolUseResult")
            block = (rec.get("message") or {}).get("content", [{}])[0]
            if not isinstance(result, dict) or block.get("is_error") or result.get("interrupted"):
                continue
            git_op = result.get("gitOperation") or {}
            if commit := git_op.get("commit"):
                commits.append(
                    Commit(
                        kind="commit",
                        ts=ts,
                        turn_key=turn.key,
                        sha=commit.get("sha"),
                        branch=commit.get("branch"),
                    )
                )
            elif is_commit_command(bash_commands.get(block.get("tool_use_id"))):
                # Older versions / quiet commits do not record gitOperation.
                sha = extract_commit_sha(result.get("stdout"))
                commits.append(Commit(kind="commit", ts=ts, turn_key=turn.key, sha=sha))
            if push := git_op.get("push"):
                commits.append(
                    Commit(kind="push", ts=ts, turn_key=turn.key, branch=push.get("branch"))
                )
            if result.get("filePath") and "structuredPatch" in result:
                added, removed = count_structured_patch(result.get("structuredPatch"))
                files.append(
                    FileChange(
                        path=result["filePath"],
                        ts=ts,
                        turn_key=turn.key,
                        added=added,
                        removed=removed,
                    )
                )
            continue

        # Assistant record (one per content block; usage repeats per message id).
        msg = rec.get("message") or {}
        turn = current_turn(ts, rec.get("uuid") or native_id)
        turn.ended_at = ts
        model = msg.get("model")
        if model and not model.startswith("<"):
            turn.model = model
        mid = msg.get("id")
        if mid is None or mid not in seen_message_ids:  # rows without an id are distinct
            if mid is not None:
                seen_message_ids.add(mid)
            turn.tokens.add(_usage_tokens(msg.get("usage") or {}))
        for block in msg.get("content") or []:
            if block.get("type") == "text" and block.get("text", "").strip():
                turn.final_message = block["text"].strip()
            elif block.get("type") == "tool_use":
                if block.get("name") == "Bash":
                    bash_commands[block.get("id")] = (block.get("input") or {}).get("command", "")
                last_tool = block.get("name")
        last_stop = msg.get("stop_reason") or last_stop
        if turn.state != "aborted":
            turn.state = "completed" if last_stop == "end_turn" else "open"

    if not points:
        return None

    needs_action = last_tool in ASK_TOOLS and last_stop == "tool_use"
    session = Session(
        id=f"claude:{native_id}",
        source="claude",
        native_id=native_id,
        cwd=meta.get("cwd"),
        project=project_name(meta.get("cwd")),
        branch=meta.get("gitBranch"),
        entrypoint=meta.get("entrypoint"),
        started_at=min(points),
        ended_at=max(points),
        source_path=str(path),
        cost_usd=cost,
        needs_action=needs_action,
    )
    if desktop:
        summary = desktop.get("postTurnSummary") or {}
        session.work_state = summary.get("status_category")
        session.work_detail = summary.get("status_detail")
        session.needs_action = needs_action or bool(summary.get("needs_action"))
    seen_shas: set[str] = set()
    unique_commits = []
    for c in commits:
        if c.kind == "commit" and c.sha:
            if c.sha in seen_shas:
                continue
            seen_shas.add(c.sha)
        unique_commits.append(c)
    first_prompt = next((t.prompt for t in turns if t.prompt_kind == "human"), None)
    session.title = (
        custom_title
        or ai_title
        or (desktop or {}).get("title")
        or (first_prompt[:80] if first_prompt else None)
    )
    return ParsedSession(
        session=session,
        turns=turns,
        segments=split_segments(points, gap_ms),
        commits=unique_commits,
        file_changes=files,
    )


def load_desktop_meta(root: Path) -> dict[str, dict]:
    """Map CLI session id -> desktop app session metadata (title, post-turn summary)."""
    root = Path(root)
    out: dict[str, dict] = {}
    if not root.is_dir():
        return out
    for f in root.rglob("local_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if cli_id := data.get("cliSessionId"):
            out[cli_id] = data
    return out


def running_claude_sessions(
    root: Path, pid_alive: Callable[[int], bool] = is_pid_alive
) -> set[str]:
    """Session ids listed in ~/.claude/sessions/<pid>.json whose process is still alive."""
    root = Path(root)
    out: set[str] = set()
    if not root.is_dir():
        return out
    for f in root.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pid, sid = data.get("pid"), data.get("sessionId")
        if isinstance(pid, int) and sid and pid_alive(pid):
            out.add(sid)
    return out

"""Source-agnostic records produced by the parsers and persisted by the store."""

from dataclasses import dataclass, field


@dataclass
class Tokens:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0

    def add(self, other: "Tokens") -> None:
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write
        self.reasoning += other.reasoning


@dataclass
class Session:
    id: str
    source: str  # "claude" | "codex"
    native_id: str
    cwd: str | None
    project: str | None
    started_at: int
    ended_at: int
    source_path: str
    title: str | None = None
    parent_id: str | None = None
    is_subagent: bool = False
    branch: str | None = None
    repo_url: str | None = None
    entrypoint: str | None = None
    cost_usd: float | None = None
    work_state: str | None = None  # e.g. "completed" from the desktop post-turn summary
    work_detail: str | None = None
    needs_action: bool = False


@dataclass
class Turn:
    key: str
    seq: int
    started_at: int
    ended_at: int
    state: str = "open"  # completed | aborted | failed | open
    prompt: str | None = None
    prompt_kind: str | None = None  # human | command | None (implicit turn)
    final_message: str | None = None
    model: str | None = None
    tokens: Tokens = field(default_factory=Tokens)


@dataclass
class Commit:
    kind: str  # commit | push | pr
    ts: int
    turn_key: str | None = None
    sha: str | None = None
    branch: str | None = None
    url: str | None = None


@dataclass
class FileChange:
    path: str
    ts: int
    turn_key: str | None = None
    added: int = 0
    removed: int = 0


@dataclass
class Compaction:
    """The context was summarised to free up the window (Claude Code / Codex "compact")."""

    ts: int
    turn_key: str | None = None
    trigger: str | None = None  # auto | manual
    pre_tokens: int | None = None
    post_tokens: int | None = None
    duration_ms: int | None = None


@dataclass
class RateLimitSample:
    ts: int
    limit_id: str
    window_minutes: int
    used_percent: float
    resets_at: int | None = None
    plan_type: str | None = None


@dataclass
class ParsedSession:
    session: Session
    turns: list[Turn] = field(default_factory=list)
    segments: list[tuple[int, int]] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=list)
    file_changes: list[FileChange] = field(default_factory=list)
    rate_limits: list[RateLimitSample] = field(default_factory=list)
    compactions: list[Compaction] = field(default_factory=list)

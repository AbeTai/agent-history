export type Source = 'claude' | 'codex'
export type Status = 'running' | 'completed' | 'incomplete' | 'aborted'
export type TurnState = 'completed' | 'aborted' | 'failed' | 'open'

export interface Tokens {
  input: number
  output: number
  cache_read: number
  cache_write: number
  reasoning: number
  total: number
}

export interface SessionSummary {
  id: string
  source: Source
  native_id: string
  parent_id: string | null
  is_subagent: boolean
  title: string | null
  cwd: string | null
  project: string | null
  branch: string | null
  repo_url: string | null
  entrypoint: string | null
  started_at: number
  ended_at: number
  cost_usd: number | null
  work_state: string | null
  work_detail: string | null
  needs_action: boolean
  is_running: boolean
  turn_count: number
  prompt_count: number
  last_turn_state: TurnState | null
  commit_count: number
  file_count: number
  lines_added: number
  lines_removed: number
  subagent_count: number
  tokens: Tokens
  models: string[]
  segments: [number, number][]
  prompt_times: number[]
  /** [timestamp, trigger] of each context compaction (markers on the calendar) */
  compaction_marks: [number, string | null][]
  compaction_count: number
  status: Status
}

export interface Turn {
  key: string
  seq: number
  started_at: number
  ended_at: number
  state: TurnState
  prompt: string | null
  prompt_kind: 'human' | 'command' | null
  final_message: string | null
  model: string | null
  tokens: Tokens
}

export interface Commit {
  turn_key: string | null
  ts: number
  kind: 'commit' | 'push' | 'pr'
  sha: string | null
  branch: string | null
  url: string | null
}

export interface FileStat {
  path: string
  added: number
  removed: number
  edits: number
}

export interface Compaction {
  ts: number
  turn_key: string | null
  trigger: string | null
  pre_tokens: number | null
  post_tokens: number | null
  duration_ms: number | null
}

export interface Check {
  key: string
  label: string
  ok: boolean | null
}

export interface SessionDetail extends SessionSummary {
  checks: Check[]
  turns: Turn[]
  commits: Commit[]
  files: FileStat[]
  compactions: Compaction[]
  subagents: SessionSummary[]
}

export interface RateWindow {
  window_minutes: number
  label: string
  used_percent: number
  raw_percent: number
  reset: boolean
  resets_at: number | null
  as_of: number
  plan_type: string | null
  series: [number, number][]
}

export interface TokenUsage {
  last_5h: number
  last_7d: number
  hourly: [number, number][]
}

export interface Usage {
  now: number
  rate_limits: RateWindow[]
  tokens: Record<Source, TokenUsage>
}

export interface Health {
  ok: boolean
  reason: string | null
  last_success_at: number | null
  sources: { name: Source; path: string; exists: boolean }[]
}

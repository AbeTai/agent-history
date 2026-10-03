import type { SessionSummary } from './types'

export type SortKey = 'newest' | 'oldest' | 'tokens' | 'prompts'

export const SORTS: { key: SortKey; label: string }[] = [
  { key: 'newest', label: '新しい順' },
  { key: 'oldest', label: '古い順' },
  { key: 'tokens', label: 'トークンが多い順' },
  { key: 'prompts', label: '依頼が多い順' },
]

export function sortSessions(sessions: SessionSummary[], key: SortKey): SessionSummary[] {
  const by: Record<SortKey, (a: SessionSummary, b: SessionSummary) => number> = {
    newest: (a, b) => b.ended_at - a.ended_at,
    oldest: (a, b) => a.started_at - b.started_at,
    tokens: (a, b) => b.tokens.total - a.tokens.total,
    prompts: (a, b) => b.prompt_count - a.prompt_count,
  }
  return [...sessions].sort(by[key])
}

import type { SessionSummary, Status } from './types'

export type ColorAxis = 'project' | 'source' | 'model' | 'status'

export const AXES: { key: ColorAxis; label: string }[] = [
  { key: 'project', label: 'プロジェクト' },
  { key: 'source', label: 'ツール' },
  { key: 'model', label: 'モデル' },
  { key: 'status', label: '完了か' },
]

export const STATUS_LABEL: Record<Status, string> = {
  running: '実行中',
  completed: '完了',
  incomplete: 'やり残し',
  aborted: '途中で終了',
}

const STATUS_COLOR: Record<Status, string> = {
  running: 'var(--status-running)',
  completed: 'var(--status-good)',
  incomplete: 'var(--status-warning)',
  aborted: 'var(--status-critical)',
}

const SOURCE: Record<string, { label: string; color: string }> = {
  codex: { label: 'Codex', color: 'var(--series-1)' },
  claude: { label: 'Claude Code', color: 'var(--series-2)' },
}

const SLOTS = 8
const NONE = '(なし)'
export const OTHER = '__other__'

export interface LegendItem {
  key: string
  label: string
  count: number
  color: string
}

export function categoryOf(s: SessionSummary, axis: ColorAxis): string {
  switch (axis) {
    case 'project':
      return s.project ?? NONE
    case 'source':
      return s.source
    case 'model':
      return s.models[0] ?? NONE
    case 'status':
      return s.status
  }
}

/**
 * Legend entries with colors. Categorical slots are handed out in a fixed order by
 * descending count (ties by name); a 9th+ category folds into "その他" instead of a new hue.
 * Build it from the unfiltered week so filtering never repaints the survivors.
 */
export function buildLegend(sessions: SessionSummary[], axis: ColorAxis): LegendItem[] {
  const counts = new Map<string, number>()
  for (const s of sessions) {
    const k = categoryOf(s, axis)
    counts.set(k, (counts.get(k) ?? 0) + 1)
  }
  if (axis === 'status') {
    return (Object.keys(STATUS_LABEL) as Status[])
      .filter((k) => counts.has(k))
      .map((k) => ({ key: k, label: STATUS_LABEL[k], count: counts.get(k)!, color: STATUS_COLOR[k] }))
  }
  if (axis === 'source') {
    return Object.keys(SOURCE)
      .filter((k) => counts.has(k))
      .map((k) => ({ key: k, ...SOURCE[k], count: counts.get(k)! }))
  }
  const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  const items: LegendItem[] = ranked.slice(0, SLOTS).map(([key, count], i) => ({
    key,
    label: key,
    count,
    color: `var(--series-${i + 1})`,
  }))
  const rest = ranked.slice(SLOTS)
  if (rest.length) {
    items.push({
      key: OTHER,
      label: 'その他',
      count: rest.reduce((a, [, c]) => a + c, 0),
      color: 'var(--series-other)',
    })
  }
  return items
}

export function colorLookup(legend: LegendItem[], axis: ColorAxis): (s: SessionSummary) => string {
  const byKey = new Map(legend.map((l) => [l.key, l.color]))
  const other = byKey.get(OTHER) ?? 'var(--series-other)'
  return (s) => byKey.get(categoryOf(s, axis)) ?? other
}

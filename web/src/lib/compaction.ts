import { compact } from './format'
import { fmtDuration } from './time'
import type { Compaction, Turn } from './types'

export function marksInRange(
  marks: [number, string | null][],
  start: number,
  end: number,
): [number, string | null][] {
  return marks.filter(([ts]) => ts >= start && ts <= end)
}

export function compactionLabel(trigger: string | null): string {
  if (trigger === 'auto') return '自動圧縮'
  if (trigger === 'manual') return '手動圧縮'
  return '圧縮'
}

/** "969.5K → 18.7K tok · 4分" with whatever the tool recorded. */
export function compactionDetail(c: Compaction): string {
  const parts: string[] = []
  if (c.pre_tokens != null && c.post_tokens != null) {
    parts.push(`${compact(c.pre_tokens)} → ${compact(c.post_tokens)} tok`)
  } else if (c.pre_tokens != null) {
    parts.push(`圧縮前 ${compact(c.pre_tokens)} tok`)
  }
  if (c.duration_ms != null) parts.push(fmtDuration(c.duration_ms))
  return parts.join(' · ')
}

export type TimelineEntry = { kind: 'turn'; turn: Turn } | { kind: 'compaction'; compaction: Compaction }

/** Turns and compactions in chronological order for the detail pane's log. */
export function mergeTimeline(turns: Turn[], compactions: Compaction[]): TimelineEntry[] {
  const entries: [number, TimelineEntry][] = [
    ...turns.map((turn): [number, TimelineEntry] => [turn.started_at, { kind: 'turn', turn }]),
    ...compactions.map((compaction): [number, TimelineEntry] => [compaction.ts, { kind: 'compaction', compaction }]),
  ]
  return entries.sort((a, b) => a[0] - b[0]).map(([, e]) => e)
}

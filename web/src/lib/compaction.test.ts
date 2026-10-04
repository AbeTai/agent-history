import { describe, expect, it } from 'vitest'
import { compactionDetail, compactionLabel, marksInRange, mergeTimeline } from './compaction'
import type { Compaction, Turn } from './types'

const H = 3_600_000

describe('marksInRange', () => {
  it('keeps compactions inside a band (inclusive edges)', () => {
    const marks: [number, string | null][] = [[1 * H, 'auto'], [2 * H, 'manual'], [5 * H, 'auto']]
    expect(marksInRange(marks, 1 * H, 2 * H)).toEqual([[1 * H, 'auto'], [2 * H, 'manual']])
    expect(marksInRange(marks, 3 * H, 4 * H)).toEqual([])
  })
})

describe('labels', () => {
  it('names the trigger', () => {
    expect(compactionLabel('auto')).toBe('自動圧縮')
    expect(compactionLabel('manual')).toBe('手動圧縮')
    expect(compactionLabel(null)).toBe('圧縮')
  })
  it('summarises tokens and duration when known', () => {
    const c = { ts: 0, turn_key: null, trigger: 'auto', pre_tokens: 969_542, post_tokens: 18_662, duration_ms: 285_493 }
    expect(compactionDetail(c as Compaction)).toBe('969.5K → 18.7K tok · 4分')
    const codex = { ...c, post_tokens: null, pre_tokens: 244_422, duration_ms: null }
    expect(compactionDetail(codex as Compaction)).toBe('圧縮前 244.4K tok')
    expect(compactionDetail({ ...c, pre_tokens: null, post_tokens: null, duration_ms: null } as Compaction)).toBe('')
  })
})

describe('mergeTimeline', () => {
  it('interleaves compactions with turns by time', () => {
    const turns = [{ key: 'a', started_at: 1 * H }, { key: 'b', started_at: 3 * H }] as Turn[]
    const comps = [{ ts: 2 * H }, { ts: 4 * H }] as Compaction[]
    expect(mergeTimeline(turns, comps).map((e) => (e.kind === 'turn' ? e.turn.key : `c@${e.compaction.ts / H}`))).toEqual([
      'a',
      'c@2',
      'b',
      'c@4',
    ])
  })
})

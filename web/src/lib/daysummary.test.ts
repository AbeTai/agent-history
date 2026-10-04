import { describe, expect, it } from 'vitest'
import { summarizeDays } from './daysummary'
import type { SessionSummary } from './types'

const H = 3_600_000
const d0 = new Date(2026, 9, 1).getTime()
const days = [new Date(2026, 9, 1), new Date(2026, 9, 2)]
const s = (id: string, segments: [number, number][]) =>
  ({ id, segments, started_at: segments[0]?.[0] ?? 0 }) as unknown as SessionSummary

describe('summarizeDays', () => {
  it('lists sessions active each day ordered by first activity, with active time', () => {
    const a = s('a', [[d0 + 10 * H, d0 + 11 * H], [d0 + 14 * H, d0 + 14.5 * H]])
    const b = s('b', [[d0 + 9 * H, d0 + 9.25 * H]])
    const c = s('c', [[d0 + 23 * H, d0 + 26 * H]]) // crosses midnight
    const [day1, day2] = summarizeDays([a, b, c], days)
    expect(day1.items.map((i) => [i.session.id, i.start, i.activeMs])).toEqual([
      ['b', d0 + 9 * H, 0.25 * H],
      ['a', d0 + 10 * H, 1.5 * H],
      ['c', d0 + 23 * H, 1 * H],
    ])
    expect(day1.activeMs).toBe(2.75 * H)
    expect(day2.items.map((i) => [i.session.id, i.activeMs])).toEqual([['c', 2 * H]])
  })
  it('marks sessions carried over from the previous day', () => {
    const c = s('c', [[d0 + 23 * H, d0 + 26 * H]])
    const [day1, day2] = summarizeDays([c], days)
    expect(day1.items[0].continued).toBe(false)
    expect(day2.items[0].continued).toBe(true)
  })
  it('days without sessions are empty', () => {
    expect(summarizeDays([], days).map((d) => d.items.length)).toEqual([0, 0])
  })
})

import { describe, expect, it } from 'vitest'
import { bucketCounts, level } from './heatmap'

const MIN = 60_000

describe('heatmap', () => {
  it('counts prompts per 10-minute bucket of a day', () => {
    const day = new Date(2026, 8, 28).getTime()
    const counts = bucketCounts([day + 1 * MIN, day + 9 * MIN, day + 10 * MIN, day - MIN, day + 24 * 60 * MIN], day)
    expect(counts).toHaveLength(144)
    expect(counts[0]).toBe(2)
    expect(counts[1]).toBe(1)
    expect(counts.reduce((a, c) => a + c, 0)).toBe(3)
  })
  it('maps counts to 0..4 intensity levels', () => {
    expect([0, 1, 2, 3, 5, 20].map(level)).toEqual([0, 1, 2, 3, 4, 4])
  })
})

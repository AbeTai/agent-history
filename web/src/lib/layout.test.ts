import { describe, expect, it } from 'vitest'
import { layoutDay, splitIntoDays } from './layout'

const H = 3_600_000
const monday = new Date(2026, 8, 28).getTime()

describe('splitIntoDays', () => {
  it('places a segment in its weekday column', () => {
    const pieces = splitIntoDays([[monday + 10 * H, monday + 11 * H]], monday)
    expect(pieces).toEqual([{ day: 0, start: monday + 10 * H, end: monday + 11 * H }])
  })
  it('splits a segment crossing midnight', () => {
    const pieces = splitIntoDays([[monday + 23 * H, monday + 25 * H]], monday)
    expect(pieces).toEqual([
      { day: 0, start: monday + 23 * H, end: monday + 24 * H },
      { day: 1, start: monday + 24 * H, end: monday + 25 * H },
    ])
  })
  it('clips to the week and drops segments outside it', () => {
    const pieces = splitIntoDays(
      [
        [monday - 2 * H, monday + H],
        [monday + 8 * 24 * H, monday + 8 * 24 * H + H],
      ],
      monday,
    )
    expect(pieces).toEqual([{ day: 0, start: monday, end: monday + H }])
  })
})

describe('layoutDay', () => {
  const b = (id: string, s: number, e: number) => ({ id, start: s * H, end: e * H })

  it('non-overlapping blocks each take the full width', () => {
    const out = layoutDay([b('a', 1, 2), b('b', 3, 4)], 0)
    expect(out.map((x) => [x.id, x.lane, x.lanes])).toEqual([
      ['a', 0, 1],
      ['b', 0, 1],
    ])
  })
  it('overlapping blocks share the cluster width', () => {
    const out = layoutDay([b('a', 1, 4), b('b', 2, 3), b('c', 3.5, 5), b('d', 6, 7)], 0)
    const m = Object.fromEntries(out.map((x) => [x.id, [x.lane, x.lanes]]))
    expect(m).toEqual({ a: [0, 2], b: [1, 2], c: [1, 2], d: [0, 1] })
  })
  it('very short blocks are widened for overlap so they never hide under each other', () => {
    const out = layoutDay([b('a', 1, 1), b('b', 1.1, 1.1)], 0.25 * H)
    expect(out.map((x) => x.lanes)).toEqual([2, 2])
  })
})

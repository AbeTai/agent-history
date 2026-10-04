import { addDays } from './time'

export interface DayPiece {
  day: number // index into the drawn days
  start: number
  end: number
}

/** Clip segments to `dayCount` consecutive local days starting at `startMs` (local midnight). */
export function splitIntoDays(
  segments: [number, number][],
  startMs: number,
  dayCount = 7,
): DayPiece[] {
  const first = new Date(startMs)
  const bounds = Array.from({ length: dayCount + 1 }, (_, i) => addDays(first, i).getTime())
  const pieces: DayPiece[] = []
  for (const [s, e] of segments) {
    for (let day = 0; day < dayCount; day++) {
      const ds = bounds[day]
      const de = bounds[day + 1]
      const overlaps = s < de && (e > ds || (s === e && s >= ds))
      if (overlaps) pieces.push({ day, start: Math.max(s, ds), end: Math.min(e, de) })
    }
  }
  return pieces
}

export interface Placed {
  lane: number
  lanes: number
}

/**
 * Google-Calendar style packing: overlapping blocks form a cluster and share its width.
 * `minDurationMs` is the block's minimum drawn height in time, so tiny blocks still
 * count as overlapping when they would visually collide.
 */
export function layoutDay<T extends { start: number; end: number }>(
  blocks: T[],
  minDurationMs: number,
): (T & Placed)[] {
  const sorted = [...blocks].sort((a, b) => a.start - b.start || b.end - a.end)
  const out: (T & Placed)[] = []
  let cluster: (T & Placed)[] = []
  let laneEnds: number[] = []
  let clusterEnd = -Infinity

  const flush = () => {
    for (const b of cluster) b.lanes = laneEnds.length
    out.push(...cluster)
    cluster = []
    laneEnds = []
  }

  for (const block of sorted) {
    const end = Math.max(block.end, block.start + minDurationMs)
    if (block.start >= clusterEnd && cluster.length) flush()
    let lane = laneEnds.findIndex((e) => e <= block.start)
    if (lane === -1) {
      lane = laneEnds.length
      laneEnds.push(end)
    } else {
      laneEnds[lane] = end
    }
    clusterEnd = cluster.length ? Math.max(clusterEnd, end) : end
    cluster.push({ ...block, lane, lanes: 1 })
  }
  flush()
  return out
}

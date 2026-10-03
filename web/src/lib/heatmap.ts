const BUCKET = 10 * 60_000
const BUCKETS_PER_DAY = 144

/** Number of prompts in each 10-minute bucket of the day starting at `dayStartMs`. */
export function bucketCounts(times: number[], dayStartMs: number): number[] {
  const counts = new Array<number>(BUCKETS_PER_DAY).fill(0)
  for (const t of times) {
    const i = Math.floor((t - dayStartMs) / BUCKET)
    if (i >= 0 && i < BUCKETS_PER_DAY) counts[i]++
  }
  return counts
}

/** Intensity step for the heatmap stripe (0 = empty). */
export function level(count: number): number {
  return Math.min(count, 4)
}

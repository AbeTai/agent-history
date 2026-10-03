export type EmptyState = { kind: 'no-data' } | { kind: 'empty-week'; latest: number } | { kind: 'filtered' }

/** Which empty-state message (if any) the main pane should show. */
export function emptyState(o: {
  visible: number
  total: number
  latest: number | null
  weekHasSessions?: boolean
}): EmptyState | null {
  if (o.visible > 0) return null
  if (o.total === 0 || o.latest == null) return { kind: 'no-data' }
  if (o.weekHasSessions) return { kind: 'filtered' }
  return { kind: 'empty-week', latest: o.latest }
}

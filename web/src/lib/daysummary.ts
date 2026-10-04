import { splitIntoDays } from './layout'
import { addDays } from './time'
import type { SessionSummary } from './types'

export interface DayItem {
  session: SessionSummary
  /** First activity of the session on this day. */
  start: number
  activeMs: number
  /** Running across midnight: the first activity today is a continuation from yesterday. */
  continued: boolean
  compactions: number
}

export interface DaySummary {
  day: Date
  items: DayItem[]
  activeMs: number
  compactions: number
}

/** Per drawn day: the sessions active that day (by first activity) and their active time. */
export function summarizeDays(sessions: SessionSummary[], days: Date[]): DaySummary[] {
  const out: DaySummary[] = days.map((day) => ({ day, items: [], activeMs: 0, compactions: 0 }))
  if (!days.length) return out
  for (const session of sessions) {
    const perDay = new Map<number, DayItem>()
    for (const piece of splitIntoDays(session.segments, days[0].getTime(), days.length)) {
      const item = perDay.get(piece.day) ?? {
        session,
        start: piece.start,
        activeMs: 0,
        continued: false,
        compactions: 0,
      }
      item.start = Math.min(item.start, piece.start)
      item.activeMs += piece.end - piece.start
      perDay.set(piece.day, item)
    }
    for (const [ts] of session.compaction_marks ?? []) {
      const day = days.findIndex((d) => ts >= d.getTime() && ts < addDays(d, 1).getTime())
      const item = perDay.get(day)
      if (item) item.compactions++
    }
    for (const [day, item] of perDay) {
      out[day].items.push(item)
      out[day].activeMs += item.activeMs
      out[day].compactions += item.compactions
    }
  }
  for (const d of out) {
    const dayStart = d.day.getTime()
    for (const item of d.items) item.continued = item.start === dayStart && item.session.started_at < dayStart
    d.items.sort((a, b) => a.start - b.start)
  }
  return out
}

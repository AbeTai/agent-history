import { WEEKDAYS, addDays, startOfWeek, weekLabel } from './time'

export type Span = 'day' | 'week' | 'month'

export const SPANS: { key: Span; label: string; current: string; unit: string }[] = [
  { key: 'day', label: '日', current: '今日', unit: '日' },
  { key: 'week', label: '週', current: '今週', unit: '週' },
  { key: 'month', label: '月', current: '今月', unit: '月' },
]

export interface Period {
  start: Date
  end: Date
  /** Every day drawn: 1 (day), 7 (week), or whole weeks covering the month. */
  days: Date[]
  monthStart?: Date
  monthEnd?: Date
}

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate())

export function periodRange(span: Span, anchor: Date): Period {
  if (span === 'day') {
    const start = startOfDay(anchor)
    return { start, end: addDays(start, 1), days: [start] }
  }
  if (span === 'week') {
    const start = startOfWeek(anchor)
    return { start, end: addDays(start, 7), days: Array.from({ length: 7 }, (_, i) => addDays(start, i)) }
  }
  const monthStart = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
  const monthEnd = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1)
  const start = startOfWeek(monthStart)
  const end = addDays(startOfWeek(addDays(monthEnd, -1)), 7)
  const count = Math.round((end.getTime() - start.getTime()) / 86_400_000)
  return { start, end, days: Array.from({ length: count }, (_, i) => addDays(start, i)), monthStart, monthEnd }
}

export function shiftAnchor(span: Span, anchor: Date, n: number): Date {
  if (span === 'day') return addDays(startOfDay(anchor), n)
  if (span === 'week') return addDays(startOfDay(anchor), 7 * n)
  return new Date(anchor.getFullYear(), anchor.getMonth() + n, 1)
}

export function periodLabel(span: Span, anchor: Date): string {
  if (span === 'day') {
    const dow = WEEKDAYS[(anchor.getDay() + 6) % 7]
    return `${anchor.getFullYear()}年${anchor.getMonth() + 1}/${anchor.getDate()}（${dow}）`
  }
  if (span === 'week') return weekLabel(startOfWeek(anchor))
  return `${anchor.getFullYear()}年${anchor.getMonth() + 1}月`
}

export function isCurrentPeriod(span: Span, anchor: Date, nowMs: number): boolean {
  const key = (d: Date) =>
    span === 'month' ? `${d.getFullYear()}-${d.getMonth()}` : periodRange(span, d).start.getTime()
  return key(anchor) === key(new Date(nowMs))
}

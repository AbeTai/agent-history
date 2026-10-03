const MIN = 60_000
const HOUR = 60 * MIN

/** Monday 00:00 (local time) of the week containing `d`. */
export function startOfWeek(d: Date): Date {
  const out = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const offset = (out.getDay() + 6) % 7 // Mon=0 … Sun=6
  out.setDate(out.getDate() - offset)
  return out
}

export function addDays(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, d.getHours(), d.getMinutes())
}

export function weekLabel(weekStart: Date): string {
  const end = addDays(weekStart, 6)
  return `${weekStart.getFullYear()}年${weekStart.getMonth() + 1}/${weekStart.getDate()}〜${end.getMonth() + 1}/${end.getDate()}`
}

export const WEEKDAYS = ['月', '火', '水', '木', '金', '土', '日']

export function fmtClock(ms: number): string {
  const d = new Date(ms)
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function fmtDateTime(ms: number): string {
  const d = new Date(ms)
  return `${d.getMonth() + 1}/${d.getDate()} ${fmtClock(ms)}`
}

export function fmtDuration(ms: number): string {
  if (ms < MIN) return '1分未満'
  const h = Math.floor(ms / HOUR)
  const m = Math.floor((ms % HOUR) / MIN)
  return h > 0 ? `${h}時間${m}分` : `${m}分`
}

export function fmtRelative(ms: number, now: number): string {
  const diff = now - ms
  if (diff < MIN) return 'たった今'
  if (diff < HOUR) return `${Math.floor(diff / MIN)}分前`
  if (diff < 24 * HOUR) return `${Math.floor(diff / HOUR)}時間前`
  return `${Math.floor(diff / (24 * HOUR))}日前`
}

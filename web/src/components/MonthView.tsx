import { useMemo } from 'react'
import { STATUS_LABEL } from '../lib/color'
import { summarizeDays } from '../lib/daysummary'
import { fmtHours } from '../lib/format'
import type { Period } from '../lib/period'
import { WEEKDAYS, addDays, fmtClock, fmtDuration } from '../lib/time'
import type { SessionSummary } from '../lib/types'

const MAX_CHIPS = 4

interface Props {
  sessions: SessionSummary[]
  period: Period
  now: number
  colorOf: (s: SessionSummary) => string
  showCompactions: boolean
  selectedId: string | null
  onSelect: (id: string) => void
  /** Open the day view for a date (date number or "+N件"). */
  onOpenDay: (day: Date) => void
}

export function MonthView({ sessions, period, now, colorOf, showCompactions, selectedId, onSelect, onOpenDay }: Props) {
  const days = useMemo(() => summarizeDays(sessions, period.days), [sessions, period.days])
  const inMonth = (d: Date) =>
    !period.monthStart || (d >= period.monthStart && period.monthEnd !== undefined && d < period.monthEnd)
  const isToday = (d: Date) => now >= d.getTime() && now < addDays(d, 1).getTime()

  return (
    <div className="month">
      <div className="month-head">
        {WEEKDAYS.map((w) => (
          <div key={w} className="month-dow">
            {w}
          </div>
        ))}
      </div>
      <div className="month-grid" style={{ gridTemplateRows: `repeat(${days.length / 7}, minmax(0, 1fr))` }}>
        {days.map(({ day, items, activeMs }) => {
          const hidden = items.length - MAX_CHIPS
          return (
            <div
              key={day.getTime()}
              className={`month-cell${inMonth(day) ? '' : ' outside'}${isToday(day) ? ' today' : ''}`}
            >
              <div className="month-cell-head">
                <button
                  className="month-date"
                  onClick={() => onOpenDay(day)}
                  aria-label={`${day.getMonth() + 1}月${day.getDate()}日を日表示で開く`}
                >
                  {day.getDate() === 1 ? `${day.getMonth() + 1}/1` : day.getDate()}
                </button>
                {activeMs > 0 && (
                  <span className="month-active" title={`稼働 ${fmtDuration(activeMs)}・${items.length}セッション`}>
                    {fmtHours(activeMs)}
                  </span>
                )}
              </div>
              <ul className="month-items">
                {items.slice(0, hidden > 0 ? MAX_CHIPS - 1 : MAX_CHIPS).map(({ session: s, start, activeMs: ms, continued, compactions }) => (
                  <li key={s.id}>
                    <button
                      className={`month-chip${s.id === selectedId ? ' selected' : ''}`}
                      style={{ ['--c' as string]: colorOf(s) }}
                      onClick={() => onSelect(s.id)}
                      title={`${s.title ?? s.id}\n${continued ? '前日から継続' : `${fmtClock(start)}〜`}（この日の稼働 ${fmtDuration(ms)}）\n${s.project ?? ''} · ${STATUS_LABEL[s.status]}`}
                    >
                      <span className="month-chip-time">{continued ? '↳' : fmtClock(start)}</span>
                      <span className="month-chip-title">{s.title ?? s.native_id.slice(0, 8)}</span>
                      {showCompactions && compactions > 0 && (
                        <span className="month-chip-compact" aria-label={`圧縮 ${compactions}回`}>
                          ⟲{compactions}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
              {hidden > 0 && (
                <button className="link month-more" onClick={() => onOpenDay(day)}>
                  他 {hidden + 1} 件
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

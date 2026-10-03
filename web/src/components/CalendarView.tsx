import { useEffect, useMemo, useRef, useState } from 'react'
import { STATUS_LABEL } from '../lib/color'
import { bucketCounts, level } from '../lib/heatmap'
import { layoutDay, splitIntoDays } from '../lib/layout'
import { WEEKDAYS, addDays, fmtClock, fmtDuration } from '../lib/time'
import type { SessionSummary } from '../lib/types'

const H = 3_600_000
const MIN_BLOCK_PX = 14
const STRIPE_PX = 6

interface Props {
  sessions: SessionSummary[]
  weekStart: Date
  /** Week the `sessions` were fetched for; scrolling waits until it matches. */
  loadedWeek: number
  now: number
  hourHeight: number
  colorOf: (s: SessionSummary) => string
  selectedId: string | null
  onSelect: (id: string) => void
}

interface Hover {
  session: SessionSummary
  start: number
  end: number
  x: number
  y: number
}

export function CalendarView({ sessions, weekStart, loadedWeek, now, hourHeight, colorOf, selectedId, onSelect }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<Hover | null>(null)
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart])
  const weekStartMs = weekStart.getTime()

  const byDay = useMemo(() => {
    const minDur = (MIN_BLOCK_PX / hourHeight) * H
    const perDay: { session: SessionSummary; start: number; end: number }[][] = days.map(() => [])
    for (const s of sessions) {
      for (const piece of splitIntoDays(s.segments, weekStartMs)) {
        perDay[piece.day].push({ session: s, start: piece.start, end: piece.end })
      }
    }
    return perDay.map((blocks) => layoutDay(blocks, minDur))
  }, [sessions, days, weekStartMs, hourHeight])

  const heat = useMemo(() => {
    const times = sessions.flatMap((s) => s.prompt_times)
    return days.map((d) => bucketCounts(times, d.getTime()))
  }, [sessions, days])

  // Once per week, when its data has arrived: scroll to the first activity (or 8:00).
  const scrolledFor = useRef<number | null>(null)
  useEffect(() => {
    const el = scrollRef.current
    if (!el || loadedWeek !== weekStartMs || scrolledFor.current === weekStartMs) return
    scrolledFor.current = weekStartMs
    const starts = byDay.flatMap((blocks, i) => blocks.map((b) => b.start - days[i].getTime()))
    const first = starts.length ? Math.min(...starts) : 8 * H
    el.scrollTop = Math.max(0, (first / H - 1) * hourHeight)
  }, [loadedWeek, weekStartMs, byDay, days, hourHeight])

  const todayIndex = days.findIndex((d) => now >= d.getTime() && now < addDays(d, 1).getTime())

  return (
    <div className="calendar">
      <div className="cal-head">
        <div className="cal-gutter" />
        {days.map((d, i) => (
          <div key={i} className={`cal-day-head${i === todayIndex ? ' today' : ''}`}>
            <span className="dow">{WEEKDAYS[i]}</span>
            <span className="date">
              {d.getMonth() + 1}/{d.getDate()}
            </span>
          </div>
        ))}
      </div>
      <div className="cal-scroll" ref={scrollRef}>
        <div className="cal-body" style={{ height: 24 * hourHeight }}>
          <div className="cal-gutter">
            {Array.from({ length: 24 }, (_, h) => (
              <div key={h} className="hour-label" style={{ top: h * hourHeight }}>
                {h > 0 ? `${h}:00` : ''}
              </div>
            ))}
          </div>
          {days.map((d, i) => {
            const dayStart = d.getTime()
            return (
              <div key={i} className={`cal-col${i === todayIndex ? ' today' : ''}`}>
                {Array.from({ length: 24 }, (_, h) => (
                  <div key={h} className="hour-line" style={{ top: h * hourHeight }} />
                ))}
                <div className="heat" aria-hidden>
                  {heat[i].map((c, k) =>
                    c ? (
                      <div
                        key={k}
                        className={`heat-cell l${level(c)}`}
                        style={{ top: (k * hourHeight) / 6, height: hourHeight / 6 }}
                        title={`${fmtClock(dayStart + k * 600_000)} 依頼 ${c}件`}
                      />
                    ) : null,
                  )}
                </div>
                {byDay[i].map((b) => {
                  const s = b.session
                  const top = ((b.start - dayStart) / H) * hourHeight
                  const height = Math.max(MIN_BLOCK_PX, ((b.end - b.start) / H) * hourHeight)
                  const color = colorOf(s)
                  const widthPct = 100 / b.lanes
                  return (
                    <button
                      key={`${s.id}-${b.start}`}
                      className={`block${s.id === selectedId ? ' selected' : ''}${s.status === 'running' ? ' running' : ''}`}
                      style={{
                        top,
                        height,
                        left: `calc(${STRIPE_PX + 2}px + (100% - ${STRIPE_PX + 4}px) * ${(b.lane * widthPct) / 100})`,
                        width: `calc((100% - ${STRIPE_PX + 4}px) * ${widthPct / 100} - 2px)`,
                        ['--c' as string]: color,
                      }}
                      onClick={() => onSelect(s.id)}
                      onMouseMove={(e) => setHover({ session: s, start: b.start, end: b.end, x: e.clientX, y: e.clientY })}
                      onMouseLeave={() => setHover(null)}
                      aria-label={`${s.title ?? s.id} ${fmtClock(b.start)}〜${fmtClock(b.end)}`}
                    >
                      <span className="block-title">{s.title ?? s.native_id.slice(0, 8)}</span>
                      {height >= 34 && (
                        <span className="block-meta">
                          {fmtClock(b.start)}–{fmtClock(b.end)} · {s.project}
                        </span>
                      )}
                    </button>
                  )
                })}
                {i === todayIndex && (
                  <div className="now-line" style={{ top: ((now - dayStart) / H) * hourHeight }} />
                )}
              </div>
            )
          })}
        </div>
      </div>
      {hover && (
        <div className="tooltip block-tip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          <div className="tip-title">{hover.session.title ?? hover.session.id}</div>
          <div>
            {fmtClock(hover.start)}–{fmtClock(hover.end)}（{fmtDuration(hover.end - hover.start)}）
          </div>
          <div className="muted">
            {hover.session.project} · {hover.session.source === 'claude' ? 'Claude Code' : 'Codex'} ·{' '}
            {STATUS_LABEL[hover.session.status]}
          </div>
        </div>
      )}
    </div>
  )
}

import { useState } from 'react'
import { compact } from '../lib/format'
import { fmtClock, fmtDateTime } from '../lib/time'
import type { RateWindow, Usage } from '../lib/types'

function severity(pct: number): string {
  if (pct >= 90) return 'var(--status-critical)'
  if (pct >= 70) return 'var(--status-warning)'
  return 'var(--accent)'
}

interface SparkProps {
  points: [number, number][]
  label: string
  format: (v: number) => string
  max?: number
}

/** 2px line, de-emphasis ink, latest point in the accent; hover shows the nearest value. */
function Sparkline({ points, label, format, max }: SparkProps) {
  const [hover, setHover] = useState<number | null>(null)
  const W = 88
  const Hh = 24
  if (points.length < 2) return <svg className="spark" width={W} height={Hh} aria-hidden />
  const t0 = points[0][0]
  const t1 = points[points.length - 1][0]
  const vmax = max ?? Math.max(1, ...points.map((p) => p[1]))
  const x = (t: number) => ((t - t0) / Math.max(1, t1 - t0)) * (W - 4) + 2
  const y = (v: number) => Hh - 2 - (v / vmax) * (Hh - 4)
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('')
  const last = points[points.length - 1]
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const t = t0 + ((e.clientX - rect.left - 2) / (W - 4)) * (t1 - t0)
    let best = 0
    points.forEach((p, i) => {
      if (Math.abs(p[0] - t) < Math.abs(points[best][0] - t)) best = i
    })
    setHover(best)
  }
  const h = hover != null ? points[hover] : null
  return (
    <span className="spark-wrap">
      <svg
        className="spark"
        width={W}
        height={Hh}
        role="img"
        aria-label={`${label}の推移`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <path d={d} fill="none" stroke="var(--ink-muted)" strokeWidth={2} strokeLinejoin="round" />
        <circle cx={x(last[0])} cy={y(last[1])} r={3} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2} />
        {h && (
          <>
            <line x1={x(h[0])} x2={x(h[0])} y1={0} y2={Hh} stroke="var(--grid-strong)" />
            <circle cx={x(h[0])} cy={y(h[1])} r={4} fill="var(--ink)" stroke="var(--surface)" strokeWidth={2} />
          </>
        )}
      </svg>
      {h && (
        <span className="tooltip spark-tip">
          {fmtDateTime(h[0])}　<b>{format(h[1])}</b>
        </span>
      )}
    </span>
  )
}

const H = 3_600_000

/** The 5H window resets every few hours, so a 24h trace is the readable span; 7D gets the week. */
function recent(w: RateWindow, now: number): [number, number][] {
  const span = w.window_minutes <= 300 ? 24 * H : 7 * 24 * H
  return w.series.filter(([t]) => t >= now - span)
}

function RateMeter({ w, now }: { w: RateWindow; now: number }) {
  const pct = Math.round(w.used_percent)
  const resets = w.resets_at && w.resets_at > now ? `リセット ${fmtDateTime(w.resets_at)}` : 'リセット済み'
  return (
    <div className="meter" title={`${w.label}枠 ${pct}% 使用（${fmtClock(w.as_of)} 時点）・${resets}`}>
      <span className="meter-label">{w.label}</span>
      <span className="meter-track" style={{ background: 'var(--accent-track)' }}>
        <span className="meter-fill" style={{ width: `${Math.min(100, pct)}%`, background: severity(pct) }} />
      </span>
      <span className="meter-value">{pct}%</span>
      <Sparkline points={recent(w, now)} label={`Codex ${w.label}`} format={(v) => `${Math.round(v)}%`} max={100} />
    </div>
  )
}

export function UsageMeters({ usage }: { usage: Usage | null }) {
  if (!usage) return <div className="meters" />
  const claude = usage.tokens.claude
  return (
    <div className="meters">
      <div className="meter-group">
        <span className="meter-group-name">Claude</span>
        <div className="meter meter-stat" title="ターン終了時刻で集計（入力＋出力＋キャッシュ）">
          <span className="meter-label">5H</span>
          <span className="meter-value">{compact(claude.last_5h)}</span>
          <span className="meter-label">7D</span>
          <span className="meter-value">{compact(claude.last_7d)}</span>
          <Sparkline points={claude.hourly} label="Claude トークン（1時間ごと）" format={(v) => `${compact(v)} tok`} />
        </div>
      </div>
      <div className="meter-group">
        <span className="meter-group-name">Codex</span>
        {usage.rate_limits.length === 0 && <span className="muted">レート制限の記録なし</span>}
        {usage.rate_limits.map((w) => (
          <RateMeter key={w.window_minutes} w={w} now={usage.now} />
        ))}
      </div>
    </div>
  )
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import { CalendarView } from './components/CalendarView'
import { DetailPane } from './components/DetailPane'
import { EmptyState } from './components/EmptyState'
import { ListView } from './components/ListView'
import { SORTS, type SortKey, sortSessions } from './lib/sort'
import { UsageMeters } from './components/UsageMeters'
import { fetchDetail, fetchHealth, fetchSessions, fetchUsage, triggerIngest } from './lib/api'
import { AXES, type ColorAxis, STATUS_LABEL, buildLegend, colorLookup } from './lib/color'
import { emptyState } from './lib/empty'
import { addDays, fmtDateTime, startOfWeek, weekLabel } from './lib/time'
import type { Health, SessionDetail, SessionSummary, Status, Usage } from './lib/types'

const DEFAULT_HOUR_PX = 44
const ZOOM_STEPS = [24, 32, 44, 60, 80, 110]
const PILL_ORDER: Status[] = ['completed', 'incomplete', 'aborted', 'running']

function loadPref<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(`agent-history:${key}`)
    return v == null ? fallback : (JSON.parse(v) as T)
  } catch {
    return fallback
  }
}

function savePref(key: string, value: unknown) {
  try {
    localStorage.setItem(`agent-history:${key}`, JSON.stringify(value))
  } catch {
    /* storage unavailable: preferences just won't persist */
  }
}

function usePref<T>(key: string, fallback: T) {
  const [v, setV] = useState<T>(() => loadPref(key, fallback))
  useEffect(() => savePref(key, v), [key, v])
  return [v, setV] as const
}

export default function App() {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()))
  const [view, setView] = usePref<'calendar' | 'list'>('view', 'calendar')
  const [axis, setAxis] = usePref<ColorAxis>('axis', 'project')
  const [hourPx, setHourPx] = usePref('hourPx', DEFAULT_HOUR_PX)
  const [sort, setSort] = usePref<SortKey>('sort', 'newest')
  const [showSubagents, setShowSubagents] = usePref('subagents', false)
  const [statusFilter, setStatusFilter] = useState<Set<Status>>(new Set())
  const [project, setProject] = useState('')

  const [loaded, setLoaded] = useState<{
    week: number
    sessions: SessionSummary[]
    total: number
    latest: number | null
  }>({ week: -1, sessions: [], total: -1, latest: null })
  const [loadError, setLoadError] = useState<string | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [reloadKey, setReloadKey] = useState(0)
  const [ingesting, setIngesting] = useState(false)
  const [ingestMsg, setIngestMsg] = useState<string | null>(null)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  // Detail result tagged with the id it belongs to; anything else counts as loading.
  const [detailState, setDetailState] = useState<{ id: string; data?: SessionDetail; error?: string } | null>(null)

  const weekEnd = useMemo(() => addDays(weekStart, 7), [weekStart])

  useEffect(() => {
    let cancelled = false
    fetchSessions(weekStart.getTime(), weekEnd.getTime(), showSubagents)
      .then((r) => {
        if (cancelled) return
        setLoaded({
          week: weekStart.getTime(),
          sessions: r.sessions,
          total: r.total_sessions,
          latest: r.latest_activity_at,
        })
        setNow(r.now)
        setLoadError(null)
      })
      .catch((e: Error) => !cancelled && setLoadError(e.message))
    return () => {
      cancelled = true
    }
  }, [weekStart, weekEnd, showSubagents, reloadKey])

  useEffect(() => {
    fetchUsage().then(setUsage).catch(() => setUsage(null))
    fetchHealth().then(setHealth).catch(() => setHealth(null))
  }, [reloadKey])

  // The background job ingests hourly; re-read the DB every minute so the view stays fresh.
  useEffect(() => {
    const id = setInterval(() => setReloadKey((k) => k + 1), 60_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (!selectedId) return
    let cancelled = false
    fetchDetail(selectedId)
      .then((data) => !cancelled && setDetailState({ id: selectedId, data }))
      .catch((e: Error) => !cancelled && setDetailState({ id: selectedId, error: e.message }))
    return () => {
      cancelled = true
    }
  }, [selectedId, reloadKey])
  const current = detailState && detailState.id === selectedId ? detailState : null

  const shiftWeek = useCallback((n: number) => setWeekStart((w) => addDays(w, 7 * n)), [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return
      if (e.key === 'ArrowLeft') shiftWeek(-1)
      else if (e.key === 'ArrowRight') shiftWeek(1)
      else if (e.key === 'Escape') setSelectedId(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [shiftWeek])

  const reingest = async () => {
    setIngesting(true)
    setIngestMsg(null)
    try {
      const { report } = await triggerIngest()
      setIngestMsg(
        report.failed.length
          ? `${report.parsed}件更新・${report.failed.length}件失敗`
          : `${report.parsed}件更新`,
      )
    } catch (e) {
      setIngestMsg(`失敗: ${(e as Error).message}`)
    } finally {
      setIngesting(false)
      setReloadKey((k) => k + 1)
    }
  }

  const sessions = loaded.sessions
  // Legend and colors come from the unfiltered week so filters never repaint survivors.
  const legend = useMemo(() => buildLegend(sessions, axis), [sessions, axis])
  const colorOf = useMemo(() => colorLookup(legend, axis), [legend, axis])
  const projects = useMemo(
    () => [...new Set(sessions.map((s) => s.project).filter(Boolean) as string[])].sort(),
    [sessions],
  )
  const statusCounts = useMemo(() => {
    const c: Partial<Record<Status, number>> = {}
    for (const s of sessions) c[s.status] = (c[s.status] ?? 0) + 1
    return c
  }, [sessions])
  const visible = useMemo(
    () =>
      sessions.filter(
        (s) => (!statusFilter.size || statusFilter.has(s.status)) && (!project || s.project === project),
      ),
    [sessions, statusFilter, project],
  )

  const toggleStatus = (st: Status) =>
    setStatusFilter((prev) => {
      const next = new Set(prev)
      if (next.has(st)) next.delete(st)
      else next.add(st)
      return next
    })

  const zoom = (dir: number) => {
    const i = ZOOM_STEPS.findIndex((z) => z >= hourPx)
    const next = ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, (i === -1 ? 2 : i) + dir))]
    setHourPx(next)
  }

  const empty =
    loaded.week === weekStart.getTime()
      ? emptyState({
          visible: visible.length,
          total: loaded.total,
          latest: loaded.latest,
          weekHasSessions: sessions.length > 0,
        })
      : null

  const isThisWeek = startOfWeek(new Date(now)).getTime() === weekStart.getTime()

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">agent-history</div>
        <UsageMeters usage={usage} />
      </header>

      <div className="toolbar">
        <div className="segmented" role="tablist" aria-label="表示">
          <button className={view === 'list' ? 'on' : ''} onClick={() => setView('list')} role="tab">
            一覧
          </button>
          <button className={view === 'calendar' ? 'on' : ''} onClick={() => setView('calendar')} role="tab">
            カレンダー
          </button>
        </div>
        <span className="count">
          セッション履歴 <b>{visible.length}</b> 件
        </span>
        <div className="pills">
          {PILL_ORDER.filter((st) => statusCounts[st]).map((st) => (
            <button
              key={st}
              className={`pill status-${st}${statusFilter.has(st) ? ' on' : ''}`}
              onClick={() => toggleStatus(st)}
              aria-pressed={statusFilter.has(st)}
            >
              {STATUS_LABEL[st]} {statusCounts[st]}
            </button>
          ))}
        </div>
        <select value={project} onChange={(e) => setProject(e.target.value)} aria-label="プロジェクト">
          <option value="">すべてのプロジェクト</option>
          {projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <label className="check-label">
          <input type="checkbox" checked={showSubagents} onChange={(e) => setShowSubagents(e.target.checked)} />
          サブエージェントも出す
        </label>
        {view === 'list' && (
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="並び順">
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        )}
        <span className="spacer" />
        {health && !health.ok && (
          <span className="warn" title={health.reason ?? ''}>
            ⚠ 取り込み: {health.reason}
          </span>
        )}
        {health?.last_success_at && (
          <span className="muted small">最終取り込み {fmtDateTime(health.last_success_at)}</span>
        )}
        {ingestMsg && <span className="muted small">{ingestMsg}</span>}
        <button className="btn" onClick={reingest} disabled={ingesting}>
          {ingesting ? '読み直し中…' : '読み直す'}
        </button>
      </div>

      <div className="weeknav">
        <button className="btn" onClick={() => setWeekStart(startOfWeek(new Date()))} disabled={isThisWeek}>
          今週
        </button>
        <button className="icon-btn" onClick={() => shiftWeek(-1)} aria-label="前の週">
          ◀
        </button>
        <button className="icon-btn" onClick={() => shiftWeek(1)} aria-label="次の週">
          ▶
        </button>
        <span className="week-label">{weekLabel(weekStart)}</span>
        <span className="muted">{visible.length}セッション</span>
        {view === 'calendar' && (
          <span className="zoom">
            <button className="icon-btn" onClick={() => zoom(-1)} aria-label="縮小">
              −
            </button>
            <button className="icon-btn" onClick={() => zoom(1)} aria-label="拡大">
              +
            </button>
            <button className="btn" onClick={() => setHourPx(DEFAULT_HOUR_PX)}>
              標準
            </button>
          </span>
        )}
      </div>

      <div className="axisbar">
        <div className="tabs" role="tablist" aria-label="色分け">
          {AXES.map((a) => (
            <button key={a.key} className={axis === a.key ? 'on' : ''} onClick={() => setAxis(a.key)} role="tab">
              {a.label}
            </button>
          ))}
        </div>
        <div className="legend">
          {legend.map((l) => (
            <span key={l.key} className="legend-item">
              <span className="swatch" style={{ background: l.color }} aria-hidden />
              {l.label} <span className="muted">{l.count}</span>
            </span>
          ))}
        </div>
      </div>

      <main className={`body${selectedId ? ' with-detail' : ''}`}>
        <section className="main-pane">
          {empty && (
            <EmptyState
              state={empty}
              health={health}
              onJump={(ms) => setWeekStart(startOfWeek(new Date(ms)))}
              onClearFilters={() => {
                setStatusFilter(new Set())
                setProject('')
              }}
            />
          )}
          {loadError ? (
            <div className="empty">API に接続できません（agent-history serve は起動していますか）: {loadError}</div>
          ) : view === 'calendar' ? (
            <CalendarView
              sessions={visible}
              weekStart={weekStart}
              loadedWeek={loaded.week}
              now={now}
              hourHeight={hourPx}
              colorOf={colorOf}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          ) : (
            <ListView
              sessions={sortSessions(visible, sort)}
              colorOf={colorOf}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
        </section>
        {selectedId && (
          <DetailPane
            detail={current?.data ?? null}
            loading={!current}
            error={current?.error ?? null}
            now={now}
            onClose={() => setSelectedId(null)}
            onSelect={setSelectedId}
          />
        )}
      </main>
    </div>
  )
}

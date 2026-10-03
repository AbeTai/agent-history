import type { Health, SessionDetail, SessionSummary, Usage } from './types'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export async function fetchSessions(start: number, end: number, includeSubagents: boolean) {
  const q = new URLSearchParams({ start: String(start), end: String(end), include_subagents: String(includeSubagents) })
  return json<{ now: number; sessions: SessionSummary[]; total_sessions: number; latest_activity_at: number | null }>(
    await fetch(`/api/sessions?${q}`),
  )
}

export async function fetchDetail(id: string) {
  return json<SessionDetail>(await fetch(`/api/sessions/${encodeURIComponent(id)}`))
}

export async function fetchUsage() {
  return json<Usage>(await fetch('/api/usage'))
}

export async function fetchHealth() {
  return json<Health>(await fetch('/api/health'))
}

export async function triggerIngest() {
  return json<{ report: { parsed: number; skipped: number; failed: [string, string][] } }>(
    await fetch('/api/ingest', { method: 'POST' }),
  )
}

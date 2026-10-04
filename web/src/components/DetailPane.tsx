import { useState } from 'react'
import { compactionDetail, compactionLabel, mergeTimeline } from '../lib/compaction'
import { compact, shortPath, usd } from '../lib/format'
import { fmtClock, fmtDateTime, fmtDuration, fmtRelative } from '../lib/time'
import type { Check, Commit, Compaction, SessionDetail, Turn } from '../lib/types'
import { StatusBadge } from './StatusBadge'

interface Props {
  detail: SessionDetail | null
  loading: boolean
  error: string | null
  now: number
  onClose: () => void
  onSelect: (id: string) => void
}

function CheckBadge({ c }: { c: Check }) {
  const state = c.ok === null ? 'unknown' : c.ok ? 'ok' : 'ng'
  const icon = { ok: '✓', ng: '✕', unknown: '?' }[state]
  const hint = c.ok === null ? '（判定できる情報がありません）' : ''
  return (
    <span className={`check check-${state}`} title={`${c.label}${hint}`}>
      <span aria-hidden>{icon}</span> {c.label}
    </span>
  )
}

function Collapsible({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="collapsible">
      <button className="collapsible-head" onClick={() => setOpen(!open)} disabled={!count} aria-expanded={open}>
        <span aria-hidden>{count ? (open ? '▾' : '▸') : '·'}</span> {title} <b>{count}件</b>
      </button>
      {open && count > 0 && <div className="collapsible-body">{children}</div>}
    </div>
  )
}

function Clamp({ text, lines = 3 }: { text: string; lines?: number }) {
  const [open, setOpen] = useState(false)
  const long = text.length > 160 || text.split('\n').length > lines
  return (
    <div className="clamp-wrap">
      <div className={`clamp${open ? ' open' : ''}`} style={{ WebkitLineClamp: open ? 'unset' : lines }}>
        {text}
      </div>
      {long && (
        <button className="link" onClick={() => setOpen(!open)}>
          {open ? '閉じる' : 'もっと見る'}
        </button>
      )}
    </div>
  )
}

const KIND_LABEL = { human: '依頼', command: 'コマンド' } as const

function TurnRow({ turn, commits }: { turn: Turn; commits: Commit[] }) {
  return (
    <li className="turn">
      <div className="turn-head">
        <span className="turn-time">{fmtClock(turn.started_at)}</span>
        <span className={`kind kind-${turn.prompt_kind ?? 'auto'}`}>
          {turn.prompt_kind ? KIND_LABEL[turn.prompt_kind] : '自動'}
        </span>
        {turn.state === 'aborted' && <span className="kind kind-aborted">中断</span>}
        {turn.state === 'open' && <span className="kind kind-open">応答待ち/途中</span>}
        <span className="turn-tokens">{compact(turn.tokens.total)} tok</span>
      </div>
      {turn.prompt ? <Clamp text={turn.prompt} /> : <div className="muted">（ユーザ発言なし）</div>}
      {commits.length > 0 && (
        <div className="chips">
          {commits.map((c, i) => (
            <span key={i} className="chip mono" title={c.branch ?? ''}>
              {c.sha ?? 'commit'}
            </span>
          ))}
        </div>
      )}
    </li>
  )
}

function CompactionRow({ c }: { c: Compaction }) {
  const detail = compactionDetail(c)
  return (
    <li className="turn compaction-row">
      <span className="turn-time">{fmtClock(c.ts)}</span>
      <span className="compaction-icon" aria-hidden>
        ⟲
      </span>
      <span className="compaction-text">
        {compactionLabel(c.trigger)}（コンテキストを要約して継続）
        {detail && <span className="muted"> · {detail}</span>}
      </span>
    </li>
  )
}

export function DetailPane({ detail, loading, error, now, onClose, onSelect }: Props) {
  if (error) {
    return (
      <aside className="detail">
        <div className="detail-error">読み込めませんでした: {error}</div>
      </aside>
    )
  }
  if (!detail) {
    return <aside className="detail">{loading && <div className="muted pad">読み込み中…</div>}</aside>
  }
  const d = detail
  const commits = d.commits.filter((c) => c.kind === 'commit')
  const prs = d.commits.filter((c) => c.kind === 'pr')
  const lastReply = [...d.turns].reverse().find((t) => t.final_message)?.final_message
  const activeMs = d.segments.reduce((a, [s, e]) => a + (e - s), 0)

  return (
    <aside className={`detail${loading ? ' loading' : ''}`}>
      <header className="detail-head">
        <div className="detail-ids">
          <span className="mono muted">{d.native_id.slice(0, 8)}</span>
          <StatusBadge status={d.status} />
          {d.is_subagent && <span className="badge">サブエージェント</span>}
          <span className={`src src-${d.source}`}>{d.source === 'claude' ? 'Claude Code' : 'Codex'}</span>
          <button className="icon-btn" onClick={onClose} aria-label="閉じる">
            ×
          </button>
        </div>
        <h2>{d.title ?? '(無題)'}</h2>
        <div className="muted">
          {d.project}
          {d.branch && d.branch !== 'HEAD' && ` · ${d.branch}`}
          {d.entrypoint && ` · ${d.entrypoint}`}
        </div>
        <div className="detail-meta">
          {fmtDateTime(d.started_at)}に開始・最後の動き {fmtRelative(d.ended_at, now)}（稼働 {fmtDuration(activeMs)}）・依頼
          {d.prompt_count}件
        </div>
        <div className="stats">
          <div className="stat" title={`入力 ${compact(d.tokens.input)} / 出力 ${compact(d.tokens.output)} / キャッシュ読込 ${compact(d.tokens.cache_read)} / キャッシュ作成 ${compact(d.tokens.cache_write)}`}>
            <span className="stat-label">トークン</span>
            <span className="stat-value">{compact(d.tokens.total)}</span>
          </div>
          <div className="stat" title={d.cost_usd == null ? 'コスト記録なし（v1 は記録がある場合のみ表示）' : ''}>
            <span className="stat-label">コスト</span>
            <span className="stat-value">{usd(d.cost_usd)}</span>
          </div>
          <div
            className="stat"
            title={d.compactions.length ? '発言ログの ⟲ の位置で圧縮されました' : 'コンテキストの圧縮はありません'}
          >
            <span className="stat-label">圧縮</span>
            <span className="stat-value">{d.compactions.length ? `${d.compactions.length}回` : '—'}</span>
          </div>
          <div className="stat">
            <span className="stat-label">モデル</span>
            <span className="stat-text">{d.models.join(', ') || '—'}</span>
          </div>
        </div>
      </header>

      <section className="card">
        <h3>セッションの状態</h3>
        <div className="checks">
          {d.checks.map((c) => (
            <CheckBadge key={c.key} c={c} />
          ))}
        </div>
        {d.work_detail && <p className="work-detail">{d.work_detail}</p>}
      </section>

      <section className="card">
        <h3>セッションの成果</h3>
        <Collapsible title="コミット" count={commits.length}>
          <ul className="plain">
            {commits.map((c, i) => (
              <li key={i}>
                <span className="mono">{c.sha ?? '(SHA不明)'}</span> <span className="muted">{c.branch ?? ''}</span>{' '}
                <span className="muted">{fmtDateTime(c.ts)}</span>
              </li>
            ))}
          </ul>
        </Collapsible>
        <Collapsible title="変更したファイル" count={d.files.length}>
          <ul className="plain">
            {d.files.map((f) => (
              <li key={f.path} className="file-row">
                <span className="mono file-path" title={f.path}>
                  {shortPath(f.path, d.cwd)}
                </span>
                <span className="diff-add">+{f.added}</span>
                <span className="diff-del">−{f.removed}</span>
              </li>
            ))}
          </ul>
        </Collapsible>
        {prs.length > 0 && (
          <div className="chips">
            {prs.map((p) => (
              <a key={p.url} className="chip" href={p.url ?? '#'} target="_blank" rel="noreferrer">
                PR {p.url?.split('/').pop()}
              </a>
            ))}
          </div>
        )}
      </section>

      {lastReply && (
        <section className="card">
          <h3>最後の応答</h3>
          <Clamp text={lastReply} lines={6} />
          <p className="hint">セッション概要の自動要約は v2 で追加予定</p>
        </section>
      )}

      {d.subagents.length > 0 && (
        <section className="card">
          <h3>サブエージェント {d.subagents.length}件</h3>
          <ul className="plain sub-list">
            {d.subagents.map((s) => (
              <li key={s.id}>
                <button className="link" onClick={() => onSelect(s.id)}>
                  {s.title ?? s.native_id.slice(0, 8)}
                </button>{' '}
                <span className="muted">
                  {fmtDateTime(s.started_at)} · {compact(s.tokens.total)} tok
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h3>作業状況（発言ログ）</h3>
        <ol className="turns">
          {mergeTimeline(d.turns, d.compactions).map((e) =>
            e.kind === 'turn' ? (
              <TurnRow key={e.turn.key} turn={e.turn} commits={commits.filter((c) => c.turn_key === e.turn.key)} />
            ) : (
              <CompactionRow key={`c-${e.compaction.ts}`} c={e.compaction} />
            ),
          )}
        </ol>
      </section>
    </aside>
  )
}

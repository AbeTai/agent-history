import { compact } from '../lib/format'
import { fmtDateTime, fmtDuration } from '../lib/time'
import type { SessionSummary } from '../lib/types'
import { StatusBadge } from './StatusBadge'

interface Props {
  sessions: SessionSummary[]
  colorOf: (s: SessionSummary) => string
  selectedId: string | null
  onSelect: (id: string) => void
}

export function ListView({ sessions, colorOf, selectedId, onSelect }: Props) {
  if (!sessions.length) return null // the shared empty-state overlay explains why
  return (
    <div className="list-scroll">
      <table className="list">
        <thead>
          <tr>
            <th>開始</th>
            <th>タイトル</th>
            <th>プロジェクト</th>
            <th>状態</th>
            <th className="num">依頼</th>
            <th className="num">コミット</th>
            <th className="num">ファイル</th>
            <th className="num" title="コンテキストの圧縮回数">圧縮</th>
            <th className="num">トークン</th>
            <th className="num">長さ</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.id} className={s.id === selectedId ? 'selected' : ''} onClick={() => onSelect(s.id)}>
              <td className="nowrap">{fmtDateTime(s.started_at)}</td>
              <td className="title-cell">
                <span className="swatch" style={{ background: colorOf(s) }} aria-hidden />
                <span className={`src src-${s.source}`}>{s.source === 'claude' ? 'Claude' : 'Codex'}</span>
                {s.title ?? s.native_id.slice(0, 8)}
              </td>
              <td>{s.project}</td>
              <td>
                <StatusBadge status={s.status} />
              </td>
              <td className="num">{s.prompt_count}</td>
              <td className="num">{s.commit_count}</td>
              <td className="num">{s.file_count}</td>
              <td className="num">{s.compaction_count || ''}</td>
              <td className="num">{compact(s.tokens.total)}</td>
              <td className="num nowrap">
                {fmtDuration(s.segments.reduce((a, [x, y]) => a + (y - x), 0))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

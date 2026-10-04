import type { EmptyState as State } from '../lib/empty'
import { fmtDateTime } from '../lib/time'
import type { Health } from '../lib/types'

const SOURCE_LABEL = { claude: 'Claude Code', codex: 'Codex' } as const

interface Props {
  state: State
  health: Health | null
  /** 日 / 週 / 月 */
  periodUnit: string
  onJump: (ms: number) => void
  onClearFilters: () => void
}

export function EmptyState({ state, health, periodUnit, onJump, onClearFilters }: Props) {
  if (state.kind === 'filtered') {
    return (
      <div className="empty-state">
        <p>絞り込み条件に合うセッションがありません。</p>
        <button className="btn" onClick={onClearFilters}>
          絞り込みを解除
        </button>
      </div>
    )
  }
  if (state.kind === 'empty-week') {
    return (
      <div className="empty-state">
        <p>この{periodUnit}のセッションはありません。</p>
        <button className="btn" onClick={() => onJump(state.latest)}>
          最新の活動（{fmtDateTime(state.latest)}）の{periodUnit}へ
        </button>
      </div>
    )
  }
  const sources = health?.sources ?? []
  return (
    <div className="empty-state">
      <h3>まだ履歴がありません</h3>
      <p>Claude Code / Codex のセッション履歴を取り込むと、ここにカレンダーとして表示されます。</p>
      {sources.length > 0 && (
        <ul className="plain sources">
          {sources.map((s) => (
            <li key={s.name}>
              <span aria-hidden>{s.exists ? '✓' : '✕'}</span> {SOURCE_LABEL[s.name]}:{' '}
              <span className="mono">{s.path}</span> {s.exists ? '' : '（見つかりません）'}
            </li>
          ))}
        </ul>
      )}
      <p className="muted">
        履歴の場所が見つかっているのに表示されない場合は「読み直す」を押すか、
        <span className="mono">uv run agent-history ingest</span> を実行してください。
      </p>
    </div>
  )
}

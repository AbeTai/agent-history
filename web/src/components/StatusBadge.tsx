import { STATUS_LABEL } from '../lib/color'
import type { Status } from '../lib/types'

const ICON: Record<Status, string> = { running: '●', completed: '✓', incomplete: '…', aborted: '■' }

/** Status is never color-alone: icon + label + tinted chip. */
export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`badge status-${status}`}>
      <span aria-hidden>{ICON[status]}</span> {STATUS_LABEL[status]}
    </span>
  )
}

import { describe, expect, it } from 'vitest'
import { buildLegend, categoryOf } from './color'
import type { SessionSummary } from './types'

const s = (over: Partial<SessionSummary>): SessionSummary =>
  ({ id: Math.random().toString(), source: 'claude', project: 'p', models: [], status: 'completed', ...over }) as SessionSummary

describe('categoryOf', () => {
  it('per axis', () => {
    const x = s({ source: 'codex', project: 'demo', models: ['gpt-6-sol', 'gpt-5.6-luna'], status: 'aborted' })
    expect(categoryOf(x, 'source')).toBe('codex')
    expect(categoryOf(x, 'project')).toBe('demo')
    expect(categoryOf(x, 'model')).toBe('gpt-6-sol')
    expect(categoryOf(x, 'status')).toBe('aborted')
    expect(categoryOf(s({ project: null, models: [] }), 'project')).toBe('(なし)')
    expect(categoryOf(s({ models: [] }), 'model')).toBe('(なし)')
  })
})

describe('buildLegend', () => {
  it('orders categories by count and assigns slots in fixed order', () => {
    const sessions = [s({ project: 'b' }), s({ project: 'a' }), s({ project: 'a' })]
    const legend = buildLegend(sessions, 'project')
    expect(legend.map((l) => [l.key, l.count, l.color])).toEqual([
      ['a', 2, 'var(--series-1)'],
      ['b', 1, 'var(--series-2)'],
    ])
  })
  it('folds a 9th+ category into その他', () => {
    const sessions = Array.from({ length: 10 }, (_, i) => s({ project: `p${i}` }))
    const legend = buildLegend(sessions, 'project')
    expect(legend).toHaveLength(9)
    expect(legend[8]).toMatchObject({ key: '__other__', label: 'その他', count: 2, color: 'var(--series-other)' })
  })
  it('status and source use fixed colors regardless of counts', () => {
    const legend = buildLegend([s({ status: 'running' }), s({ status: 'completed' }), s({ status: 'completed' })], 'status')
    expect(legend.find((l) => l.key === 'completed')?.color).toBe('var(--status-good)')
    expect(legend.find((l) => l.key === 'running')?.label).toBe('実行中')
    const src = buildLegend([s({ source: 'codex' })], 'source')
    expect(src[0]).toMatchObject({ key: 'codex', label: 'Codex', color: 'var(--series-1)' })
  })
})

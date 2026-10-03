import { describe, expect, it } from 'vitest'
import { sortSessions } from './sort'
import type { SessionSummary } from './types'

const s = (id: string, started: number, ended: number, total: number, prompts: number) =>
  ({ id, started_at: started, ended_at: ended, tokens: { total }, prompt_count: prompts }) as unknown as SessionSummary

describe('sortSessions', () => {
  const rows = [s('a', 1, 10, 5, 1), s('b', 2, 30, 1, 9), s('c', 3, 20, 9, 4)]
  it.each([
    ['newest', ['b', 'c', 'a']],
    ['oldest', ['a', 'b', 'c']],
    ['tokens', ['c', 'a', 'b']],
    ['prompts', ['b', 'c', 'a']],
  ] as const)('%s', (key, expected) => {
    expect(sortSessions(rows, key).map((r) => r.id)).toEqual(expected)
  })
  it('does not mutate the input', () => {
    sortSessions(rows, 'tokens')
    expect(rows.map((r) => r.id)).toEqual(['a', 'b', 'c'])
  })
})

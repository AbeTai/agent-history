import { describe, expect, it } from 'vitest'
import { emptyState } from './empty'

describe('emptyState', () => {
  it('nothing to say when the week has sessions', () => {
    expect(emptyState({ visible: 3, total: 10, latest: 5 })).toBeNull()
  })
  it('no data at all', () => {
    expect(emptyState({ visible: 0, total: 0, latest: null })).toEqual({ kind: 'no-data' })
  })
  it('data exists but not in this week: offer a jump to the latest activity', () => {
    expect(emptyState({ visible: 0, total: 4, latest: 1234 })).toEqual({ kind: 'empty-week', latest: 1234 })
  })
  it('filters hid everything', () => {
    expect(emptyState({ visible: 0, total: 4, latest: 1234, weekHasSessions: true })).toEqual({ kind: 'filtered' })
  })
})

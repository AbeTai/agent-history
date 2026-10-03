import { describe, expect, it } from 'vitest'
import { addDays, fmtDuration, fmtRelative, startOfWeek, weekLabel } from './time'

describe('week math (local time, weeks start Monday)', () => {
  it('startOfWeek returns Monday 00:00', () => {
    const sat = new Date(2026, 9, 3, 15, 30) // Sat Oct 3
    const mon = startOfWeek(sat)
    expect([mon.getFullYear(), mon.getMonth(), mon.getDate(), mon.getHours()]).toEqual([2026, 8, 28, 0])
  })
  it('Sunday belongs to the week that started the previous Monday', () => {
    expect(startOfWeek(new Date(2026, 9, 4, 23)).getDate()).toBe(28)
    expect(startOfWeek(new Date(2026, 9, 5, 0)).getDate()).toBe(5)
  })
  it('addDays keeps local midnight', () => {
    const d = addDays(new Date(2026, 8, 28), 7)
    expect([d.getMonth(), d.getDate(), d.getHours()]).toEqual([9, 5, 0])
  })
  it('weekLabel spans month boundaries', () => {
    expect(weekLabel(new Date(2026, 8, 28))).toBe('2026年9/28〜10/4')
  })
})

describe('formatting', () => {
  const MIN = 60_000
  it('fmtDuration', () => {
    expect(fmtDuration(79 * MIN)).toBe('1時間19分')
    expect(fmtDuration(5 * MIN)).toBe('5分')
    expect(fmtDuration(20_000)).toBe('1分未満')
    expect(fmtDuration(26 * 60 * MIN)).toBe('26時間0分')
  })
  it('fmtRelative', () => {
    const now = 1_000_000_000_000
    expect(fmtRelative(now - 30_000, now)).toBe('たった今')
    expect(fmtRelative(now - 5 * MIN, now)).toBe('5分前')
    expect(fmtRelative(now - 3 * 60 * MIN, now)).toBe('3時間前')
    expect(fmtRelative(now - 49 * 60 * MIN, now)).toBe('2日前')
  })
})

import { describe, expect, it } from 'vitest'
import { isCurrentPeriod, periodLabel, periodRange, shiftAnchor } from './period'

const ymd = (d: Date) => [d.getFullYear(), d.getMonth() + 1, d.getDate()]
const sat = new Date(2026, 9, 3, 15, 30) // Sat Oct 3 2026

describe('periodRange', () => {
  it('day: one local day', () => {
    const r = periodRange('day', sat)
    expect(ymd(r.start)).toEqual([2026, 10, 3])
    expect(r.start.getHours()).toBe(0)
    expect(ymd(r.end)).toEqual([2026, 10, 4])
    expect(r.days.map(ymd)).toEqual([[2026, 10, 3]])
  })
  it('week: Monday to Monday', () => {
    const r = periodRange('week', sat)
    expect(ymd(r.start)).toEqual([2026, 9, 28])
    expect(ymd(r.end)).toEqual([2026, 10, 5])
    expect(r.days).toHaveLength(7)
  })
  it('month: whole weeks covering the month (Mon start)', () => {
    const r = periodRange('month', sat)
    // Oct 1 2026 is a Thursday, Oct 31 a Saturday
    expect(ymd(r.start)).toEqual([2026, 9, 28])
    expect(ymd(r.end)).toEqual([2026, 11, 2])
    expect(r.days).toHaveLength(35)
    expect(ymd(r.monthStart!)).toEqual([2026, 10, 1])
    expect(ymd(r.monthEnd!)).toEqual([2026, 11, 1])
  })
  it('month that needs six rows', () => {
    // Aug 2026: Aug 1 is a Saturday, Aug 31 a Monday
    expect(periodRange('month', new Date(2026, 7, 15)).days).toHaveLength(42)
  })
})

describe('shiftAnchor', () => {
  it('moves by a day, a week, or a month', () => {
    expect(ymd(shiftAnchor('day', sat, -1))).toEqual([2026, 10, 2])
    expect(ymd(shiftAnchor('week', sat, 1))).toEqual([2026, 10, 10])
    expect(ymd(shiftAnchor('month', sat, 1))).toEqual([2026, 11, 1])
    expect(ymd(shiftAnchor('month', new Date(2026, 0, 31), 1))).toEqual([2026, 2, 1]) // no overflow
  })
})

describe('periodLabel', () => {
  it('per span', () => {
    expect(periodLabel('day', sat)).toBe('2026年10/3（土）')
    expect(periodLabel('week', sat)).toBe('2026年9/28〜10/4')
    expect(periodLabel('month', sat)).toBe('2026年10月')
  })
})

describe('isCurrentPeriod', () => {
  it('compares the period containing now', () => {
    const now = new Date(2026, 9, 4, 9).getTime() // Sun Oct 4
    expect(isCurrentPeriod('day', sat, now)).toBe(false)
    expect(isCurrentPeriod('week', sat, now)).toBe(true)
    expect(isCurrentPeriod('month', sat, now)).toBe(true)
    expect(isCurrentPeriod('month', new Date(2026, 8, 30), now)).toBe(false)
  })
})

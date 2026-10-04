import { describe, expect, it } from 'vitest'
import { compact, fmtHours, shortPath, usd } from './format'

describe('format', () => {
  it('compact', () => {
    expect([0, 950, 1284, 12_900, 26_300_000, 2_429_804_812].map(compact)).toEqual([
      '0', '950', '1.3K', '12.9K', '26.3M', '2.4B',
    ])
  })
  it('fmtHours: short active-time label for month cells', () => {
    const M = 60_000
    expect([0, 20 * M, 90 * M, 150 * M, 10 * 60 * M].map(fmtHours)).toEqual(['', '20分', '1.5h', '2.5h', '10h'])
  })
  it('usd', () => {
    expect(usd(7.567)).toBe('$7.57')
    expect(usd(null)).toBe('—')
  })
  it('shortPath relative to cwd', () => {
    expect(shortPath('/Users/me/dev/demo/src/a.py', '/Users/me/dev/demo')).toBe('src/a.py')
    expect(shortPath('/etc/hosts', '/Users/me/dev/demo')).toBe('/etc/hosts')
  })
  it('shortPath handles Windows paths (backslashes, drive-letter case)', () => {
    expect(shortPath('C:\\Users\\me\\demo\\src\\a.py', 'C:\\Users\\me\\demo')).toBe('src\\a.py')
    expect(shortPath('c:\\users\\me\\demo\\b.py', 'C:\\Users\\me\\demo')).toBe('b.py')
    expect(shortPath('C:/Users/me/demo/c.py', 'C:\\Users\\me\\demo')).toBe('c.py')
    expect(shortPath('C:\\Users\\me\\demo2\\x.py', 'C:\\Users\\me\\demo')).toBe('C:\\Users\\me\\demo2\\x.py')
  })
})

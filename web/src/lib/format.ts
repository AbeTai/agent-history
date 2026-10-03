export function compact(n: number): string {
  const units: [number, string][] = [
    [1e9, 'B'],
    [1e6, 'M'],
    [1e3, 'K'],
  ]
  for (const [size, suffix] of units) {
    if (Math.abs(n) >= size) return `${(n / size).toFixed(1)}${suffix}`
  }
  return String(n)
}

export function usd(v: number | null): string {
  return v == null ? '—' : `$${v.toFixed(2)}`
}

const isWindowsPath = (p: string) => /^[a-zA-Z]:[\\/]/.test(p) || p.startsWith('\\\\')

/** Path relative to the session's cwd when it lies inside it (POSIX or Windows paths). */
export function shortPath(path: string, cwd: string | null): string {
  if (!cwd) return path
  if (isWindowsPath(cwd)) {
    // Windows: either separator, case-insensitive; keep the original spelling in the result.
    const norm = (p: string) => p.replace(/\//g, '\\').toLowerCase()
    const base = norm(cwd).replace(/\\+$/, '') + '\\'
    return norm(path).startsWith(base) ? path.slice(base.length) : path
  }
  return path.startsWith(cwd + '/') ? path.slice(cwd.length + 1) : path
}

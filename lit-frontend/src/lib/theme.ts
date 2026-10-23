export type ThemeMode = 'light' | 'dark' | 'system'

const KEY = 'lit-theme'

function safeGet(): ThemeMode {
  try {
    const stored = localStorage.getItem(KEY)
    return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
  } catch {
    return 'system'
  }
}

export function getThemeMode(): ThemeMode {
  return safeGet()
}

export function resolveTheme(mode: ThemeMode): 'light' | 'dark' {
  if (mode !== 'system') return mode
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(mode: ThemeMode): void {
  document.documentElement.classList.toggle('dark', resolveTheme(mode) === 'dark')
}

export function setThemeMode(mode: ThemeMode): void {
  try {
    localStorage.setItem(KEY, mode)
  } catch {
    /* storage can be blocked (private mode); the theme still applies for this session */
  }
  applyTheme(mode)
}

/** Call once before first paint. Also follows the OS when the mode is 'system'. */
export function initTheme(): void {
  applyTheme(safeGet())
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (safeGet() === 'system') applyTheme('system')
  })
}

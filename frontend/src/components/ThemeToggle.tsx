import { useTheme, Theme } from '../theme/ThemeContext'

/**
 * Light / dark / system control. Cycles through the three modes; the icon
 * reflects the *resolved* theme (sun/moon), with a small "auto" dot when in
 * system mode so the user can tell it's following the OS.
 */
const ORDER: Theme[] = ['light', 'dark', 'system']

export function ThemeToggle() {
  const { theme, resolvedTheme, setTheme } = useTheme()

  const next = () => {
    const i = ORDER.indexOf(theme)
    setTheme(ORDER[(i + 1) % ORDER.length])
  }

  const label =
    theme === 'system' ? `System (${resolvedTheme})` : theme === 'dark' ? 'Dark' : 'Light'

  return (
    <button
      type="button"
      onClick={next}
      title={`Theme: ${label} — click to change`}
      aria-label={`Theme: ${label}. Click to change.`}
      className="relative inline-flex h-8 w-8 items-center justify-center rounded-lg border border-line bg-surface text-muted transition hover:bg-inset hover:text-content"
    >
      {resolvedTheme === 'dark' ? <MoonIcon /> : <SunIcon />}
      {theme === 'system' && (
        <span className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full bg-brand-500 ring-2 ring-surface" />
      )}
    </button>
  )
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none">
      <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none">
      <path
        d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  )
}

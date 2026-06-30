import { useEffect, useRef, useState } from 'react'
import { useTheme, type Theme } from '../theme/ThemeContext'

/**
 * Account menu (F3). Replaces the inline 'Sign out' chip with a small
 * dropdown that shows the user's email, a theme switcher, and sign out.
 * Also surfaces the persisted-history disclosure note required for
 * regulated customers (per backend_plan.md data retention open question).
 *
 * Clicks outside / Esc close the menu. Keyboard accessible.
 */
export function AccountMenu({
  email,
  onLogout,
}: {
  email: string
  onLogout: () => void | Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const { theme, setTheme } = useTheme()

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const cycleTheme = () => {
    const order: Theme[] = ['light', 'dark', 'system']
    setTheme(order[(order.indexOf(theme) + 1) % order.length])
  }

  const initials = (email[0] || '?').toUpperCase()

  return (
    <div className="relative" ref={wrapRef}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-label="Account menu"
        aria-expanded={open}
        aria-haspopup="menu"
        className="inline-flex h-8 items-center gap-1.5 rounded-full border border-line bg-surface pl-1 pr-2 text-xs text-content transition hover:bg-inset"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-600 text-[11px] font-semibold text-white">
          {initials}
        </span>
        <span className="hidden max-w-[12ch] truncate sm:inline" title={email}>
          {email}
        </span>
        <CaretIcon open={open} />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-10 z-30 w-72 overflow-hidden rounded-xl border border-line bg-surface shadow-lift"
        >
          <div className="border-b border-line px-3 py-2.5">
            <div className="truncate text-sm font-medium text-content" title={email}>
              {email}
            </div>
            <div className="text-[11px] text-muted">Signed in</div>
          </div>

          <button
            type="button"
            role="menuitem"
            onClick={cycleTheme}
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm text-content transition hover:bg-inset"
          >
            <span className="flex items-center gap-2">
              <PaletteIcon />
              Theme
            </span>
            <span className="text-xs capitalize text-muted">{theme}</span>
          </button>

          <button
            type="button"
            role="menuitem"
            onClick={async () => {
              setOpen(false)
              await onLogout()
            }}
            className="flex w-full items-center gap-2 border-t border-line px-3 py-2 text-left text-sm text-content transition hover:bg-inset"
          >
            <LogoutIcon />
            Sign out
          </button>

          <div className="border-t border-line bg-inset/60 px-3 py-2 text-[11px] leading-snug text-muted">
            <strong className="font-medium text-content">Privacy:</strong> your
            questions and answers are saved to this account's history. Only
            you can see them; they're stored on this server only.
          </div>
        </div>
      )}
    </div>
  )
}

function CaretIcon({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={`h-3 w-3 text-muted transition ${open ? 'rotate-180' : ''}`}
      fill="none"
    >
      <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function PaletteIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-muted" fill="none">
      <path
        d="M12 3a9 9 0 1 0 0 18 3 3 0 0 0 0-6h-1a2 2 0 0 1 0-4h2a4 4 0 0 0 4-4v-1a3 3 0 0 0-3-3"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <circle cx="7.5" cy="11" r="1" fill="currentColor" />
      <circle cx="9.5" cy="6.5" r="1" fill="currentColor" />
      <circle cx="14.5" cy="6.5" r="1" fill="currentColor" />
    </svg>
  )
}

function LogoutIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-muted" fill="none">
      <path
        d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M10 8l-4 4 4 4M6 12h12"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

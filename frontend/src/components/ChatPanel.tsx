import { useEffect, useRef, useState } from 'react'
import { MessageBubble } from './MessageBubble'
import { useClickOutside } from '../hooks/useClickOutside'
import { useSession } from '../session/SessionContext'
import type { Message } from '../pages/ChatPage'

interface ChatPanelProps {
  messages: Message[]
  isLoading: boolean
  health: 'checking' | 'online' | 'offline'
  onSendMessage: (message: string) => Promise<void>
  onCancel?: () => void
  onRetry?: (text: string) => void
  user?: { email: string } | null
  onLogout?: () => void | Promise<void>
  onOpenSidebar?: () => void
  /**
   * Last user question that failed (e.g. backend unreachable). When set,
   * the composer shows a "Retry" button so the user can resend without
   * retyping. Cleared on the next successful send.
   */
  failedText?: string | null
}

const EXAMPLES = [
  'How many delivered orders in São Paulo last month?',
  'What was our total revenue last year?',
  'Show revenue by state this year',
  'Top 5 products by revenue',
  'How many low reviews did we get last month?',
]

export function ChatPanel({
  messages,
  isLoading,
  health,
  onSendMessage,
  onCancel,
  onRetry,
  user,
  onLogout,
  onOpenSidebar,
  failedText,
}: ChatPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [value, setValue] = useState('')
  const { drawerOpen, openDrawer, closeDrawer } = useSession()

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  const send = (text: string) => {
    const t = text.trim()
    if (!t || isLoading) return
    setValue('')
    void onSendMessage(t)
  }

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      {/* Header: dense, no card chrome, no big subtitle. The rail
          already has the brand mark; here we just need a status pill
          and a "menu" affordance on small screens. */}
      <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-line bg-surface px-3 sm:px-4">
        <div className="flex items-center gap-2 min-w-0">
          {onOpenSidebar && (
            <button
              type="button"
              onClick={onOpenSidebar}
              aria-label="Open conversations"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-line bg-surface text-muted transition hover:bg-inset hover:text-content sm:hidden"
            >
              <MenuIcon />
            </button>
          )}
          <h1 className="truncate text-sm font-semibold leading-none text-content">
            {currentTitle(messages)}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          {user && onLogout && <AccountMenuInline email={user.email} onLogout={onLogout} />}
          <HealthPill health={health} />
        </div>
      </header>

      {/* Transcript — fills the rest of the screen; content max-w-4xl
          centered INSIDE so it reads well on wide displays without
          leaving huge empty margins. */}
      <div className="scroll-slim min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-4xl px-3 py-4 sm:px-6 sm:py-6">
          {messages.length === 0 ? (
            <EmptyState onPick={send} disabled={isLoading} />
          ) : (
            <div className="space-y-3">
              {messages.map(msg => (
                <MessageBubble
                  key={msg.id}
                  role={msg.role}
                  content={msg.content}
                  response={msg.response}
                  at={msg.at}
                  disabled={isLoading}
                  onQuickReply={send}
                />
              ))}
              {isLoading && <TypingIndicator />}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>
      </div>

      {/* Composer */}
      <div className="shrink-0 border-t border-line bg-surface px-3 pb-4 pt-3 sm:px-6">
        <div className="mx-auto w-full max-w-4xl">
          {failedText && !isLoading && onRetry && (
            <div
              role="status"
              className="mb-2 flex items-center justify-between gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700"
            >
              <span className="truncate">Couldn't reach the backend. Retry?</span>
              <button
                type="button"
                onClick={() => onRetry(failedText)}
                className="shrink-0 rounded-md border border-rose-300 bg-surface px-2 py-0.5 text-[11px] font-medium text-rose-700 transition hover:bg-rose-100"
              >
                Retry
              </button>
            </div>
          )}
          <form
            onSubmit={e => {
              e.preventDefault()
              send(value)
            }}
            className="flex items-center gap-2 rounded-xl border border-line bg-inset px-2 py-1.5 transition focus-within:border-brand-400 focus-within:bg-surface focus-within:ring-2 focus-within:ring-brand-100"
          >
            {isLoading && (
              <div className="ml-1 flex items-center gap-1.5 text-[11px] text-muted">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-500" />
                <span>Thinking…</span>
              </div>
            )}
            <input
              value={value}
              onChange={e => setValue(e.target.value)}
              type="text"
              autoFocus
              placeholder="Ask about orders, revenue, reviews…"
              aria-label="Ask a question"
              disabled={isLoading}
              className="flex-1 bg-transparent px-2 py-1.5 text-sm text-content placeholder:text-muted focus:outline-none disabled:opacity-50"
            />
            {isLoading && onCancel ? (
              <button
                type="button"
                onClick={() => onCancel()}
                aria-label="Cancel"
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-surface text-content transition hover:bg-inset"
              >
                <SquareIcon />
              </button>
            ) : (
              <button
                type="submit"
                disabled={isLoading || !value.trim()}
                aria-label="Send question"
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-inset disabled:text-muted"
              >
                {isLoading ? <Spinner /> : <SendIcon />}
              </button>
            )}
          </form>
          <p className="mt-2 px-1 text-[11px] text-muted">
            Every answer is computed in SQL and cited to its source tables.
            <kbd className="ml-2 hidden rounded border border-line bg-inset px-1 text-[10px] text-muted sm:inline">
              ⌘K new chat
            </kbd>
          </p>
        </div>
      </div>
    </div>
  )
}

function currentTitle(messages: Message[]): string {
  // Show the active session's first user question as the title (more
  // useful than "Olist Query Assistant" once a conversation is
  // underway). Fall back to the brand line for the empty state.
  const firstUser = messages.find(m => m.role === 'user')
  if (!firstUser) return 'Olist Query Assistant'
  const t = firstUser.content
  return t.length > 60 ? t.slice(0, 59).trimEnd() + '…' : t
}

function EmptyState({ onPick, disabled }: { onPick: (q: string) => void; disabled: boolean }) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 ring-1 ring-brand-100 dark:bg-brand-500/10 dark:text-brand-300 dark:ring-brand-500/20">
        <SparkIcon />
      </div>
      <h2 className="text-lg font-semibold text-content">Ask a question in plain English</h2>
      <p className="mt-1.5 max-w-md text-sm text-muted">
        I translate it into a verified database query and return the exact
        number — with the source so you can trust it.
      </p>
      <div className="mt-6 flex max-w-2xl flex-wrap justify-center gap-2">
        {EXAMPLES.map(ex => (
          <button
            key={ex}
            onClick={() => onPick(ex)}
            disabled={disabled}
            className="rounded-full border border-line bg-inset px-3.5 py-1.5 text-left text-xs font-medium text-muted shadow-sm transition hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700 disabled:opacity-50 dark:hover:border-brand-500/40 dark:hover:bg-brand-500/10 dark:hover:text-brand-200"
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex items-end gap-2 py-2 animate-fade-in-up">
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-brand-600 text-white">
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none">
          <ellipse cx="12" cy="6" rx="7" ry="3" stroke="currentColor" strokeWidth="1.8" />
          <path d="M5 6v6c0 1.66 3.13 3 7 3s7-1.34 7-3V6" stroke="currentColor" strokeWidth="1.8" />
        </svg>
      </div>
      <div className="flex items-center gap-1 rounded-2xl rounded-bl-md bg-inset px-3 py-2">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="typing-dot h-1.5 w-1.5 rounded-full bg-muted"
            style={{ animationDelay: `${i * 0.16}s` }}
          />
        ))}
      </div>
    </div>
  )
}

function HealthPill({ health }: { health: 'checking' | 'online' | 'offline' }) {
  const map = {
    checking: { dot: 'bg-amber-400', text: 'Connecting', cls: 'text-amber-700 bg-amber-50 ring-amber-100' },
    online: { dot: 'bg-emerald-500', text: 'Connected', cls: 'text-emerald-700 bg-emerald-50 ring-emerald-100' },
    offline: { dot: 'bg-rose-500', text: 'Offline', cls: 'text-rose-700 bg-rose-50 ring-rose-100' },
  }[health]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ${map.cls}`}
      title="Live backend (database + model) status"
    >
      <span className={`h-1.5 w-1.5 rounded-full ${map.dot} ${health !== 'offline' ? 'animate-pulse' : ''}`} />
      {map.text}
    </span>
  )
}

// --- Compact account menu for the panel header ---------------------------
// The rail has the avatar (AccountMenu compact). The panel header
// only needs a "Sign out" affordance. We re-use AccountMenu but
// keep the trigger text-minimal so the header stays at h-12.

function AccountMenuInline({
  email,
  onLogout,
}: {
  email: string
  onLogout: () => void | Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  useClickOutside(wrapRef, () => setOpen(false), open)

  return (
    <div className="relative" ref={wrapRef}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-label="Account menu"
        aria-expanded={open}
        className="inline-flex h-7 items-center gap-1 rounded-md border border-line bg-surface px-2 text-[11px] text-muted transition hover:bg-inset hover:text-content"
      >
        {email.split('@')[0]}
        <CaretIcon open={open} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-9 z-30 w-56 overflow-hidden rounded-xl border border-line bg-surface shadow-lift"
        >
          <div className="border-b border-line px-3 py-2">
            <div className="truncate text-xs text-content" title={email}>{email}</div>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={async () => {
              setOpen(false)
              await onLogout()
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-content transition hover:bg-inset"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none">
      <path
        d="M4 7h16M4 12h16M4 17h16"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}

function CaretIcon({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={`h-3 w-3 transition ${open ? 'rotate-180' : ''}`}
      fill="none"
    >
      <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

/** The brand mark — used here by MessageBubble. Kept exported for that. */
export function BrandMark({ small = false }: { small?: boolean }) {
  const size = small ? 'h-7 w-7' : 'h-9 w-9'
  return (
    <div
      className={`${size} flex shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-sm`}
    >
      <svg viewBox="0 0 24 24" className={small ? 'h-4 w-4' : 'h-5 w-5'} fill="none">
        <ellipse cx="12" cy="6" rx="7" ry="3" stroke="currentColor" strokeWidth="1.8" />
        <path d="M5 6v6c0 1.66 3.13 3 7 3s7-1.34 7-3V6" stroke="currentColor" strokeWidth="1.8" />
        <path d="M5 12v6c0 1.66 3.13 3 7 3s7-1.34 7-3v-6" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    </div>
  )
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
      <path d="M3.4 20.4 21 12 3.4 3.6 3.4 10l12 2-12 2z" />
    </svg>
  )
}

function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none">
      <path
        d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.4 2.4M15.3 15.3l2.4 2.4M17.7 6.3l-2.4 2.4M8.7 15.3l-2.4 2.4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}

function Spinner() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 animate-spin" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" className="opacity-25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

function SquareIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  )
}

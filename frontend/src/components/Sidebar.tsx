import { useState, useRef, useEffect } from 'react'
import { useSession } from '../session/SessionContext'

/**
 * Conversation sidebar (F1). Lists the caller's sessions, lets them
 * start a new one, switch, rename (inline), and delete (with confirm).
 *
 * Two layout modes (F3):
 *   - `variant="column"` (default): always visible as a 256px column.
 *     Used on `sm:` and up.
 *   - `variant="drawer"`: a slide-in overlay, hidden by default,
 *     toggled via `open`. Used on `<sm` for the mobile experience.
 */
export function Sidebar({
  disabled = false,
  variant = 'column',
  open = false,
  onClose,
}: {
  disabled?: boolean
  variant?: 'column' | 'drawer'
  open?: boolean
  onClose?: () => void
}) {
  const {
    sessions,
    activeId,
    isLoadingList,
    newSession,
    selectSession,
    renameSession,
    deleteSession,
  } = useSession()

  const handleNew = async () => {
    try {
      await newSession()
      // In drawer mode, dismiss so the user can see the new chat.
      onClose?.()
    } catch {
      /* AuthContext will bounce anon users; nothing to surface here */
    }
  }

  const handleSelect = async (id: string) => {
    await selectSession(id)
    onClose?.()
  }

  return (
    <aside
      className={
        variant === 'drawer'
          ? `fixed inset-y-0 left-0 z-40 w-72 transform border-r border-line bg-surface transition-transform duration-200 ${
              open ? 'translate-x-0' : '-translate-x-full'
            }`
          : 'flex h-full w-full flex-col border-r border-line bg-surface'
      }
      aria-label="Conversations"
    >
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-3">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
          Conversations
        </h2>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={handleNew}
            disabled={disabled}
            className="inline-flex h-7 items-center gap-1 rounded-md border border-line bg-surface px-2 text-xs font-medium text-content transition hover:border-brand-300 hover:bg-brand-50 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Start a new conversation"
          >
            <PlusIcon />
            New
          </button>
          {variant === 'drawer' && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close conversations"
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted transition hover:bg-inset hover:text-content"
            >
              <CloseIcon />
            </button>
          )}
        </div>
      </div>

      <div className="scroll-slim flex-1 overflow-y-auto px-2 py-2">
        {isLoadingList && sessions.length === 0 ? (
          <div className="px-2 py-3 text-xs text-muted">Loading…</div>
        ) : sessions.length === 0 ? (
          <div className="px-2 py-6 text-center text-xs text-muted">
            No conversations yet.
            <br />
            <button
              type="button"
              onClick={handleNew}
              disabled={disabled}
              className="mt-2 font-medium text-brand-700 hover:text-brand-800 disabled:opacity-50"
            >
              Start your first one
            </button>
          </div>
        ) : (
          <ul className="space-y-0.5">
            {sessions.map(s => (
              <SessionRow
                key={s.id}
                id={s.id}
                title={s.title}
                lastActiveAt={s.last_active_at}
                isActive={s.id === activeId}
                disabled={disabled}
                onSelect={() => handleSelect(s.id)}
                onRename={t => renameSession(s.id, t)}
                onDelete={() => deleteSession(s.id)}
              />
            ))}
          </ul>
        )}
      </div>
    </aside>
  )
}

function SessionRow({
  id,
  title,
  lastActiveAt,
  isActive,
  disabled,
  onSelect,
  onRename,
  onDelete,
}: {
  id: string
  title: string | null
  lastActiveAt: string
  isActive: boolean
  disabled: boolean
  onSelect: () => void
  onRename: (title: string) => void | Promise<void>
  onDelete: () => void | Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(title || '')
  const [confirming, setConfirming] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  const startEdit = () => {
    setDraft(title || '')
    setEditing(true)
  }

  const commitEdit = async () => {
    const t = draft.trim()
    if (!t) {
      setEditing(false)
      return
    }
    if (t !== (title || '')) {
      try {
        await onRename(t)
      } catch {
        /* swallow; the user can retry */
      }
    }
    setEditing(false)
  }

  const cancelEdit = () => {
    setDraft(title || '')
    setEditing(false)
  }

  const onDeleteClick = async () => {
    if (!confirming) {
      setConfirming(true)
      return
    }
    try {
      await onDelete()
    } catch {
      /* swallow; the row stays */
    }
    setConfirming(false)
  }

  return (
    <li
      className={`group relative rounded-lg ${
        isActive
          ? 'bg-brand-50 ring-1 ring-brand-200 dark:bg-brand-900/40 dark:ring-brand-700'
          : 'hover:bg-inset'
      }`}
    >
      {editing ? (
        <div className="flex items-center gap-1 px-2 py-1.5">
          <input
            ref={inputRef}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') void commitEdit()
              else if (e.key === 'Escape') cancelEdit()
            }}
            onBlur={() => void commitEdit()}
            className="flex-1 rounded-md border border-line bg-surface px-2 py-1 text-sm text-content focus:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-200"
            aria-label="Rename conversation"
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={onSelect}
          disabled={disabled}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-content disabled:cursor-not-allowed disabled:opacity-50"
        >
          <ChatBubble small active={isActive} />
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">
              {title || 'New chat'}
            </div>
            <div className="truncate text-[11px] text-muted">
              {relativeTime(lastActiveAt)}
            </div>
          </div>
        </button>
      )}

      {!editing && (
        <div className="absolute right-1 top-1.5 flex items-center gap-0.5 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
          <IconButton
            title="Rename"
            ariaLabel={`Rename "${title || 'New chat'}"`}
            onClick={startEdit}
          >
            <PencilIcon />
          </IconButton>
          <IconButton
            title="Delete"
            ariaLabel={`Delete "${title || 'New chat'}"`}
            onClick={onDeleteClick}
            danger={confirming}
          >
            <TrashIcon />
          </IconButton>
        </div>
      )}

      {confirming && (
        <div
          role="alert"
          className="mx-2 mb-1.5 rounded-md border border-rose-200 bg-rose-50 px-2 py-1.5 text-[11px] text-rose-700"
        >
          Delete this conversation? Click the trash again to confirm.
        </div>
      )}
      <span className="sr-only">{id}</span>
    </li>
  )
}

function IconButton({
  children,
  onClick,
  title,
  ariaLabel,
  danger,
}: {
  children: React.ReactNode
  onClick: () => void
  title: string
  ariaLabel: string
  danger?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={ariaLabel}
      className={`inline-flex h-6 w-6 items-center justify-center rounded-md transition ${
        danger
          ? 'bg-rose-100 text-rose-700 hover:bg-rose-200'
          : 'text-muted hover:bg-surface hover:text-content'
      }`}
    >
      {children}
    </button>
  )
}

function ChatBubble({ small, active }: { small?: boolean; active?: boolean }) {
  return (
    <div
      className={`flex shrink-0 items-center justify-center rounded-md ${
        small ? 'h-6 w-6' : 'h-7 w-7'
      } ${
        active
          ? 'bg-brand-600 text-white'
          : 'bg-inset text-muted'
      }`}
    >
      <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none">
        <path
          d="M4 5h16v11H8l-4 4V5z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  )
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none">
      <path
        d="M6 6l12 12M18 6L6 18"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none">
      <path
        d="m4 20 4-1 11-11-3-3L5 16l-1 4z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none">
      <path
        d="M5 7h14M9 7V5h6v2M7 7l1 12h8l1-12"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** Compact "x minutes ago" formatter. No external dep. */
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (isNaN(then)) return ''
  const now = Date.now()
  const sec = Math.round((now - then) / 1000)
  if (sec < 60) return 'just now'
  if (sec < 3600) return `${Math.round(sec / 60)} min ago`
  if (sec < 86400) return `${Math.round(sec / 3600)} hr ago`
  const days = Math.round(sec / 86400)
  if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`
  return new Date(then).toLocaleDateString()
}

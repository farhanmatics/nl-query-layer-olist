import { useState, useRef, useEffect } from 'react'
import { useSession } from '../session/SessionContext'
import { useSwipeToClose } from '../hooks/useSwipeToClose'

/**
 * Conversations drawer (Claude-style). Slides in from the left when
 * `open` is true; lives in an overlay so the chat panel keeps its full
 * width whether the drawer is open or not. Closes itself when the user
 * selects, renames, or deletes a session.
 *
 * Width: ~280px on `sm:` and up, full-width on smaller screens. Animates
 * in/out with a 200ms translate.
 */
export function Sidebar({
  open = false,
  onClose,
}: {
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

  // Swipe-to-close on mobile: a leftward drag past 80px closes the drawer.
  const drawerRef = useRef<HTMLElement | null>(null)
  useSwipeToClose(drawerRef, () => onClose?.(), { enabled: open })

  // Close on Esc (the rail already does this too, but the drawer is
  // an independent surface so it owns its own key handling).
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const handleNew = async () => {
    try {
      await newSession()
      onClose?.()
    } catch {
      /* anon users are bounced by AuthContext */
    }
  }

  const handleSelect = async (id: string) => {
    await selectSession(id)
    onClose?.()
  }

  return (
    <>
      {/* Backdrop: click outside the panel to close. The panel itself
          stops propagation so clicks inside the panel don't trigger close. */}
      {open && (
        <button
          type="button"
          aria-label="Close conversations"
          onClick={onClose}
          className="fixed inset-0 z-30 bg-black/40 backdrop-blur-sm"
        />
      )}
      <aside
        ref={drawerRef}
        aria-label="Conversations"
        className={`fixed inset-y-0 left-0 z-40 w-72 max-w-[85vw] transform border-r border-line bg-surface shadow-lift transition-transform duration-200 ease-out touch-none ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Conversations
          </h2>
          <div className="flex items-center gap-1">
            <kbd
              className="hidden rounded border border-line bg-inset px-1 py-0.5 text-[10px] font-mono text-muted sm:inline"
              title="Toggle history (⌘B)"
            >
              ⌘B
            </kbd>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close conversations"
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted transition hover:bg-inset hover:text-content"
            >
              <CloseIcon />
            </button>
          </div>
        </div>

        <div className="px-3 pb-2">
          <button
            type="button"
            onClick={handleNew}
            className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-line bg-surface text-sm font-medium text-content transition hover:border-brand-300 hover:bg-inset"
          >
            <PlusIcon />
            New chat
          </button>
        </div>

        <div className="scroll-slim h-[calc(100%-7rem)] overflow-y-auto px-2 pb-3">
          {isLoadingList && sessions.length === 0 ? (
            <div className="px-2 py-3 text-xs text-muted">Loading…</div>
          ) : sessions.length === 0 ? (
            <div className="px-2 py-6 text-center text-xs text-muted">
              No conversations yet.
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
                  onSelect={() => handleSelect(s.id)}
                  onRename={t => renameSession(s.id, t)}
                  onDelete={() => deleteSession(s.id)}
                />
              ))}
            </ul>
          )}
        </div>
      </aside>
    </>
  )
}

function SessionRow({
  id,
  title,
  lastActiveAt,
  isActive,
  onSelect,
  onRename,
  onDelete,
}: {
  id: string
  title: string | null
  lastActiveAt: string
  isActive: boolean
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
          ? 'bg-active ring-1 ring-active-ring'
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
          className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm ${
            isActive ? 'text-active-content' : 'text-content'
          }`}
        >
          <ChatBubble small active={isActive} />
          <div className="min-w-0 flex-1">
            <div className={`truncate font-medium ${isActive ? 'text-active-content' : ''}`}>
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

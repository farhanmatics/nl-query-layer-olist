import { useAuth } from '../auth/AuthContext'
import { useSession } from '../session/SessionContext'
import { ThemeToggle } from './ThemeToggle'
import { AccountMenu } from './AccountMenu'

/**
 * Vertical icon rail (Claude-style). Always visible; holds the controls
 * the user needs without opening the drawer. Clicking the "history" icon
 * opens the sessions drawer; clicking the brand or "new chat" creates
 * a new conversation.
 *
 * Width: 56px. Always visible (no responsive hiding — the rail replaces
 * the always-visible sidebar, so on small screens you still get the
 * essential controls without losing real estate to a list).
 */
export function SidebarRail({ onOpenHistory }: { onOpenHistory: () => void }) {
  const { user, logout } = useAuth()
  const { newSession } = useSession()

  return (
    <nav
      aria-label="App navigation"
      className="flex h-full w-14 shrink-0 flex-col items-center justify-between border-r border-line bg-surface py-3"
    >
      <div className="flex flex-col items-center gap-2">
        <BrandMark />
        <div className="my-1 h-px w-6 bg-line" aria-hidden="true" />
        <RailButton title="New chat (⌘K)" ariaLabel="New chat" onClick={() => void newSession()}>
          <PlusIcon />
        </RailButton>
        <RailButton title="History (⌘B)" ariaLabel="Conversation history" onClick={onOpenHistory}>
          <HistoryIcon />
        </RailButton>
      </div>

      <div className="flex flex-col items-center gap-2">
        <ThemeToggle />
        {user && <AccountMenu email={user.email} onLogout={logout} compact />}
      </div>
    </nav>
  )
}

function RailButton({
  title,
  ariaLabel,
  onClick,
  children,
}: {
  title: string
  ariaLabel: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={ariaLabel}
      className="flex h-9 w-9 items-center justify-center rounded-lg text-muted transition hover:bg-inset hover:text-content focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300"
    >
      {children}
    </button>
  )
}

function BrandMark() {
  return (
    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-sm">
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none">
        <ellipse cx="12" cy="6" rx="7" ry="3" stroke="currentColor" strokeWidth="1.8" />
        <path d="M5 6v6c0 1.66 3.13 3 7 3s7-1.34 7-3V6" stroke="currentColor" strokeWidth="1.8" />
        <path d="M5 12v6c0 1.66 3.13 3 7 3s7-1.34 7-3v-6" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    </div>
  )
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function HistoryIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 7v5l3 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

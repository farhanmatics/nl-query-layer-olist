import { useState, useEffect, useRef, useCallback } from 'react'
import { Sidebar } from '../components/Sidebar'
import { ChatPanel } from '../components/ChatPanel'
import { checkHealth, query, QueryResponse, AbortError } from '../api'
import { useAuth } from '../auth/AuthContext'
import { useSession } from '../session/SessionContext'
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { deriveTitle } from '../utils/title'

/**
 * The authenticated chat (F1) with F3 polish.
 *
 * Layout:
 *   - <sm:  sidebar is a slide-in drawer (toggled by the panel header).
 *   - sm+:  sidebar is a fixed left column.
 *
 * Session-id source: SessionContext.activeId (server-issued, owned by
 * the user). The backend now reads the prior turn from the messages
 * table (B4 prep), so a follow-up inherits across reloads.
 */
export function ChatPage() {
  const { user, logout } = useAuth()
  const { activeId, messages: storedMessages, appendTurn, newSession } = useSession()
  const [isLoading, setIsLoading] = useState(false)
  const [health, setHealth] = useState<'checking' | 'online' | 'offline'>(
    'checking',
  )
  // F3: the text of the most recent failed send. When set, the composer
  // shows a Retry banner. Cleared on the next successful send.
  const [failedText, setFailedText] = useState<string | null>(null)
  // F3: in-flight AbortController so the cancel button can kill the
  // request mid-flight.
  const abortRef = useRef<AbortController | null>(null)
  // F3: mobile drawer state.
  const [drawerOpen, setDrawerOpen] = useState(false)
  const isMobile = !useMediaQuery('(min-width: 640px)')

  useEffect(() => {
    let active = true
    const ping = async () => {
      try {
        const h = await checkHealth()
        if (active) setHealth(h?.db === 'ok' && h?.llm === 'ok' ? 'online' : 'offline')
      } catch {
        if (active) setHealth('offline')
      }
    }
    ping()
    const id = setInterval(ping, 15000)
    return () => {
      active = false
      clearInterval(id)
    }
  }, [])

  // F3: cancel button kills the in-flight request. The server will see
  // a closed connection and abort the LLM call too.
  const handleCancel = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setIsLoading(false)
  }, [])

  const handleNewChat = useCallback(async () => {
    try {
      await newSession()
      setDrawerOpen(false)
    } catch {
      /* anon users are bounced by AuthContext */
    }
  }, [newSession])

  // F3: keyboard shortcuts. Disabled when no user (the login page has its
  // own form focus).
  useKeyboardShortcuts({
    enabled: !!user,
    onNewChat: () => void handleNewChat(),
    onEscape: () => setDrawerOpen(false),
  })

  const sendCore = useCallback(
    async (text: string) => {
      const controller = new AbortController()
      abortRef.current = controller
      setIsLoading(true)
      setFailedText(null)
      try {
        // F2-final: a durable turn needs a server session. If none is active
        // (fresh user, or all sessions deleted), create one — titled from this
        // first question — and send against it. Without this the turn would go
        // out session-less, skip persistence, and vanish on reload.
        let sid = activeId
        if (!sid) {
          const created = await newSession(deriveTitle(text))
          sid = created.id
        }
        const response = await query(text, sid, { signal: controller.signal })
        appendTurn(text, response)
      } catch (error) {
        if (error instanceof AbortError) {
          // User-initiated cancel. Show a quiet acknowledgement in the
          // transcript so they know the request was stopped (not still
          // running in the background).
          const cancelled: QueryResponse = {
            operation: null,
            filters: null,
            result: null,
            formatted_answer: null,
            source: null,
            error: 'Cancelled.',
            context: null,
          }
          appendTurn(text, cancelled)
          return
        }
        // Network / server failure: surface a clear error AND remember
        // the text so the user can retry without retyping.
        const fallback: QueryResponse = {
          operation: null,
          filters: null,
          result: null,
          formatted_answer: null,
          source: null,
          error: `Couldn't reach the backend: ${
            error instanceof Error ? error.message : 'unknown error'
          }`,
          context: null,
        }
        appendTurn(text, fallback)
        setFailedText(text)
      } finally {
        abortRef.current = null
        setIsLoading(false)
      }
    },
    [activeId, newSession, appendTurn],
  )

  // Convert stored messages to the ChatPanel shape.
  const messages = storedMessages
    .map(m => toPanelMessage(m))
    .filter((m): m is Message => m !== null)

  return (
    <div className="flex h-full w-full bg-bg text-content">
      {/* Desktop sidebar (sm+). */}
      <div className="hidden w-64 shrink-0 sm:block">
        <Sidebar disabled={isLoading} />
      </div>

      {/* Mobile drawer (<sm). Backdrop closes on click. */}
      {isMobile && drawerOpen && (
        <button
          type="button"
          aria-label="Close conversations"
          onClick={() => setDrawerOpen(false)}
          className="fixed inset-0 z-30 bg-black/40 sm:hidden"
        />
      )}
      {isMobile && (
        <Sidebar
          variant="drawer"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          disabled={isLoading}
        />
      )}

      <div className="mx-auto flex h-full w-full max-w-3xl flex-col px-4">
        <ChatPanel
          messages={messages}
          isLoading={isLoading}
          health={health}
          user={user}
          onSendMessage={sendCore}
          onCancel={handleCancel}
          onRetry={text => void sendCore(text)}
          onOpenSidebar={() => setDrawerOpen(true)}
          onLogout={logout}
          failedText={failedText}
        />
      </div>
    </div>
  )
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  response?: QueryResponse
  at: number
}

function toPanelMessage(m: import('../api').MessageRecord): Message | null {
  const at = new Date(m.created_at).getTime()
  if (isNaN(at)) return null
  if (m.role === 'user') {
    if (!m.question) return null
    return {
      id: m.id,
      role: 'user',
      content: m.question,
      at,
    }
  }
  // assistant
  const r = m.response
  const content =
    r?.formatted_answer ||
    r?.error ||
    r?.context?.clarify?.prompt ||
    (r ? `Query executed: ${r.operation}` : '')
  return {
    id: m.id,
    role: 'assistant',
    content,
    response: r || undefined,
    at,
  }
}

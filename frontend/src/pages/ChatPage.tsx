import { useState, useEffect, useRef } from 'react'
import { SidebarRail } from '../components/SidebarRail'
import { Sidebar } from '../components/Sidebar'
import { ChatPanel } from '../components/ChatPanel'
import { checkHealth, query, QueryResponse, AbortError } from '../api'
import { useAuth } from '../auth/AuthContext'
import { useSession } from '../session/SessionContext'
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts'
import { deriveTitle } from '../utils/title'

/**
 * The authenticated chat (Claude-style layout).
 *
 * Shell:
 *   - Left: 56px icon rail (always visible)
 *   - Center: the main panel — fills all remaining width, no max-w-3xl
 *     center (was wasting huge amounts of space on wide screens)
 *   - Overlay: a 280px conversations drawer that slides in from the left
 *     when the user clicks the history icon, hits Cmd+B, or sends a new
 *     question
 *
 * Session-id source: SessionContext.activeId (server-issued, owned by
 * the user). The orchestrator now reads the prior turn from the messages
 * table so a follow-up inherits across reloads.
 */
export function ChatPage() {
  const { user, logout } = useAuth()
  const {
    activeId,
    messages: storedMessages,
    appendUserMessage,
    appendAssistantResponse,
    newSession,
    drawerOpen,
    openDrawer,
    closeDrawer,
  } = useSession()
  const [isLoading, setIsLoading] = useState(false)
  const [health, setHealth] = useState<'checking' | 'online' | 'offline'>(
    'checking',
  )
  // F3: in-flight AbortController so the cancel button can kill the
  // request mid-flight.
  // F3: the text of the most recent failed send. When set, the composer
  // shows a Retry banner. Cleared on the next successful send.
  const [, setFailedText] = useState<string | null>(null)

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

  // F3: cancel button kills the in-flight request via an AbortController.
  // The server sees a closed connection and aborts the LLM call too.
  const abortRef = useRef<AbortController | null>(null)
  const handleCancel = () => {
    abortRef.current?.abort()
    abortRef.current = null
    setIsLoading(false)
  }

  const handleNewChat = async () => {
    try {
      await newSession()
    } catch {
      /* anon users are bounced by AuthContext */
    }
  }

  // F3: keyboard shortcuts.
  //   Cmd/Ctrl+K         → new chat
  //   Cmd/Ctrl+B (or ⇧O) → toggle history drawer
  useKeyboardShortcuts({
    enabled: !!user,
    onNewChat: () => void handleNewChat(),
    onToggleDrawer: () => (drawerOpen ? closeDrawer() : openDrawer()),
    onEscape: () => drawerOpen && closeDrawer(),
  })

  const sendCore = async (text: string) => {
    setIsLoading(true)
    setFailedText(null)
    const controller = new AbortController()
    abortRef.current = controller
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
      appendUserMessage(text)
      const response = await query(text, sid, { signal: controller.signal })
      appendAssistantResponse(response)
    } catch (error) {
      if (error instanceof AbortError) {
        const cancelled: QueryResponse = {
          operation: null,
          filters: null,
          result: null,
          formatted_answer: null,
          source: null,
          error: 'Cancelled.',
          context: null,
        }
        appendAssistantResponse(cancelled)
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
      appendAssistantResponse(fallback)
      setFailedText(text)
    } finally {
      abortRef.current = null
      setIsLoading(false)
    }
  }

  // Convert stored messages to the ChatPanel shape.
  const messages = storedMessages
    .map(m => toPanelMessage(m))
    .filter((m): m is Message => m !== null)

  return (
    <div className="flex h-full w-full bg-bg text-content">
      <SidebarRail onOpenHistory={openDrawer} />
      <Sidebar open={drawerOpen} onClose={closeDrawer} />
      <main className="flex h-full min-w-0 flex-1 flex-col">
        <ChatPanel
          messages={messages}
          isLoading={isLoading}
          health={health}
          user={user}
          onSendMessage={sendCore}
          onCancel={handleCancel}
          onRetry={text => void sendCore(text)}
          onOpenSidebar={openDrawer}
          onLogout={logout}
        />
      </main>
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

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  ReactNode,
} from 'react'
import {
  createSession as apiCreateSession,
  deleteSession as apiDeleteSession,
  listMessages as apiListMessages,
  listSessions as apiListSessions,
  MessageRecord,
  renameSession as apiRenameSession,
  SessionMeta,
} from '../api'
import { useAuth } from '../auth/AuthContext'
import { deriveTitle } from '../utils/title'
import { newLocalId } from '../utils/id'

/**
 * F1: durable conversations owned by the authed user. One source of
 * truth for the sidebar's session list, the active session, and the
 * messages of the active session.
 *
 * The plan: on mount (authed), fetch the sessions list and select the
 * most recent. "New chat" creates a fresh session server-side. Switching
 * sessions loads their messages. Renaming and deleting hit the
 * /api/sessions/:id endpoints (all IDOR-safe server-side).
 */

interface SessionContextValue {
  sessions: SessionMeta[]
  activeId: string | null
  messages: MessageRecord[]
  isLoadingList: boolean
  isLoadingMessages: boolean
  /** Whether the conversations drawer is open (controlled from the rail). */
  drawerOpen: boolean
  openDrawer: () => void
  closeDrawer: () => void
  /**
   * Create a new server session and make it active. An optional title is
   * passed straight to the backend (used to title a conversation from its
   * first question). Returns the created row so callers can use its id
   * immediately without waiting for the activeId state to flush.
   */
  newSession: (title?: string) => Promise<SessionMeta>
  selectSession: (id: string) => Promise<void>
  renameSession: (id: string, title: string) => Promise<void>
  deleteSession: (id: string) => Promise<void>
  /**
   * Append the user's question to the in-memory transcript immediately
   * (optimistic UI). The assistant reply is added separately via
   * appendAssistantResponse once /api/query returns.
   */
  appendUserMessage: (question: string) => void
  appendAssistantResponse: (response: import('../api').QueryResponse) => void
}

const SessionContext = createContext<SessionContextValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const { status, user } = useAuth()
  const [sessions, setSessions] = useState<SessionMeta[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<MessageRecord[]>([])
  const [isLoadingList, setIsLoadingList] = useState(false)
  const [isLoadingMessages, setIsLoadingMessages] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  // A freshly created session has no server-side messages yet. Skip the
  // load for it once, so the message-load effect can't clobber an optimistic
  // append with an empty list (a race when create + send happen together).
  const skipLoadFor = useRef<string | null>(null)

  // Load the session list on mount (authed only). Re-load when the user
  // changes (e.g. logout → login as someone else).
  useEffect(() => {
    if (status !== 'authed' || !user) {
      setSessions([])
      setActiveId(null)
      setMessages([])
      return
    }
    let active = true
    setIsLoadingList(true)
    apiListSessions()
      .then(rows => {
        if (!active) return
        setSessions(rows)
        // Auto-select the most recent session unless the user already picked
        // one (e.g. created a new chat while the list was still loading).
        if (rows.length > 0) {
          setActiveId(prev => prev ?? rows[0].id)
        }
      })
      .catch(() => {
        if (!active) return
        setSessions([])
      })
      .finally(() => {
        if (active) setIsLoadingList(false)
      })
    return () => {
      active = false
    }
  }, [status, user])

  // Load messages when the active session changes.
  useEffect(() => {
    if (!activeId) {
      setMessages([])
      return
    }
    // Just created this session locally → nothing on the server to load,
    // and an empty fetch could overwrite the optimistic first turn.
    if (skipLoadFor.current === activeId) {
      skipLoadFor.current = null
      return
    }
    let active = true
    setIsLoadingMessages(true)
    apiListMessages(activeId)
      .then(rows => {
        if (!active) return
        // Keep optimistic local turns if a fetch races with an in-flight query.
        setMessages(prev => {
          const pending = prev.filter(m => m.id.startsWith('local-'))
          if (pending.length === 0) return rows
          return [...rows, ...pending]
        })
      })
      .catch(() => {
        if (!active) return
        setMessages([])
      })
      .finally(() => {
        if (active) setIsLoadingMessages(false)
      })
    return () => {
      active = false
    }
  }, [activeId])

  const newSession = useCallback(async (title?: string): Promise<SessionMeta> => {
    const created = await apiCreateSession(title)
    skipLoadFor.current = created.id
    setSessions(prev => [created, ...prev])
    setActiveId(created.id)
    setMessages([])
    return created
  }, [])

  const selectSession = useCallback(async (id: string) => {
    setActiveId(id)
    // The effect above will load messages; we don't need to await.
  }, [])

  const renameSession = useCallback(
    async (id: string, title: string) => {
      const updated = await apiRenameSession(id, title)
      setSessions(prev => prev.map(s => (s.id === id ? updated : s)))
    },
    [],
  )

  const deleteSession = useCallback(async (id: string) => {
    await apiDeleteSession(id)
    setSessions(prev => prev.filter(s => s.id !== id))
    if (activeId === id) {
      // Pick the next-most-recent, or clear.
      setActiveId(prev => {
        const remaining = sessions.filter(s => s.id !== id)
        return remaining.length > 0 ? remaining[0].id : null
      })
      setMessages([])
    }
  }, [activeId, sessions])

  const appendUserMessage = useCallback(
    (question: string) => {
      const now = new Date().toISOString()
      setMessages(prev => [
        ...prev,
        {
          id: newLocalId(),
          role: 'user',
          question,
          response: null,
          created_at: now,
        },
      ])
      setSessions(prev => {
        if (!activeId) return prev
        return prev.map(s =>
          s.id === activeId
            ? { ...s, last_active_at: now, title: s.title ?? deriveTitle(question) }
            : s,
        )
      })
    },
    [activeId],
  )

  const appendAssistantResponse = useCallback(
    (response: import('../api').QueryResponse) => {
      const now = new Date().toISOString()
      setMessages(prev => [
        ...prev,
        {
          id: newLocalId(),
          role: 'assistant',
          question: null,
          response,
          created_at: now,
        },
      ])
      setSessions(prev => {
        if (!activeId) return prev
        return prev.map(s =>
          s.id === activeId ? { ...s, last_active_at: now } : s,
        )
      })
    },
    [activeId],
  )

  const value = useMemo<SessionContextValue>(
    () => ({
      sessions,
      activeId,
      messages,
      isLoadingList,
      isLoadingMessages,
      drawerOpen,
      openDrawer: () => setDrawerOpen(true),
      closeDrawer: () => setDrawerOpen(false),
      newSession,
      selectSession,
      renameSession,
      deleteSession,
      appendUserMessage,
      appendAssistantResponse,
    }),
    [
      sessions,
      activeId,
      messages,
      isLoadingList,
      isLoadingMessages,
      drawerOpen,
      newSession,
      selectSession,
      renameSession,
      deleteSession,
      appendUserMessage,
      appendAssistantResponse,
    ],
  )

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  )
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used within a SessionProvider')
  return ctx
}

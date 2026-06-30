import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  ReactNode,
} from 'react'
import {
  fetchMe,
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
  seedCsrf,
  setUnauthorizedHandler,
  User,
} from '../api'

/**
 * Auth shell (F0). One source of truth for "who is the current user":
 *  - `loading` while we bootstrap from the session cookie (so a refresh
 *    silently re-uses the existing session)
 *  - `authed` once we have a user
 *  - `anon` once we know there's no session
 *
 * The 401 hook is set on mount so any 401 from a non-auth API call
 * (e.g. /api/query) clears local user state and lets ProtectedRoute
 * bounce the user to /login.
 */

type AuthStatus = 'loading' | 'authed' | 'anon'

interface AuthContextValue {
  status: AuthStatus
  user: User | null
  login: (email: string, password: string) => Promise<User>
  register: (email: string, password: string) => Promise<User>
  logout: () => Promise<void>
  /** Force a re-check of the session (rare; mostly for tests / dev). */
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<User | null>(null)

  const refresh = useCallback(async () => {
    try {
      const me = await fetchMe()
      if (me) {
        setUser(me)
        setStatus('authed')
      } else {
        setUser(null)
        setStatus('anon')
      }
    } catch {
      setUser(null)
      setStatus('anon')
    }
  }, [])

  // 401 from any non-auth call → drop local user state. The router
  // (ProtectedRoute) will redirect on the next render.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null)
      setStatus('anon')
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  // Bootstrap: try /me with the existing cookie, then seed a CSRF
  // token so the (anon) login form can submit.
  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const me = await fetchMe()
        if (!active) return
        if (me) {
          setUser(me)
          setStatus('authed')
        } else {
          setUser(null)
          setStatus('anon')
        }
      } catch {
        if (!active) return
        setUser(null)
        setStatus('anon')
      }
      // Always make sure we have a CSRF cookie available for the auth
      // forms (harmless if we already have one).
      try {
        await seedCsrf()
      } catch {
        /* ignore — login form will surface a clear error */
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    // Make sure the CSRF cookie is fresh before we submit.
    try {
      await seedCsrf()
    } catch {
      /* ignore */
    }
    const u = await apiLogin(email, password)
    setUser(u)
    setStatus('authed')
    return u
  }, [])

  const register = useCallback(async (email: string, password: string) => {
    try {
      await seedCsrf()
    } catch {
      /* ignore */
    }
    const u = await apiRegister(email, password)
    setUser(u)
    setStatus('authed')
    return u
  }, [])

  const logout = useCallback(async () => {
    try {
      await apiLogout()
    } finally {
      setUser(null)
      setStatus('anon')
      // Re-seed a CSRF cookie so the next person at this browser
      // can still log in.
      try {
        await seedCsrf()
      } catch {
        /* ignore */
      }
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, register, logout, refresh }),
    [status, user, login, register, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}

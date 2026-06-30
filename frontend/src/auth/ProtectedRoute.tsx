import { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'

/**
 * Bounce anon users to /login, preserving the original URL so we can
 * return them there after a successful login. While the AuthContext is
 * still bootstrapping from the cookie, show a spinner (not a flash of
 * the login page) so a refresh on an authed session doesn't visibly
 * redirect.
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-line border-t-brand-600"
          aria-label="Loading session"
        />
      </div>
    )
  }
  if (status === 'anon') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <>{children}</>
}

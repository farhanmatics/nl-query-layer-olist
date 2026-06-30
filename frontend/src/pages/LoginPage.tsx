import { useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { AuthCard } from '../components/AuthCard'
import { useAuth } from '../auth/AuthContext'

/**
 * If the user is already authed when they land on /login (e.g. they
 * bookmarked it after a logout, or a stale session got restored),
 * bounce them straight to the chat.
 */
export function LoginPage() {
  const { status } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from || '/'

  useEffect(() => {
    if (status === 'authed') {
      navigate(from, { replace: true })
    }
  }, [status, navigate, from])

  if (status === 'authed') return null
  return <AuthCard mode="login" />
}

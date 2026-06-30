import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { AuthCard } from '../components/AuthCard'
import { useAuth } from '../auth/AuthContext'

export function RegisterPage() {
  const { status } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (status === 'authed') {
      navigate('/', { replace: true })
    }
  }, [status, navigate])

  if (status === 'authed') return null
  return <AuthCard mode="register" />
}

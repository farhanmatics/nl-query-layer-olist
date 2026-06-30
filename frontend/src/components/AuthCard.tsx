import { FormEvent, useState, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

/**
 * Auth shell used by both LoginPage and RegisterPage. Holds the
 * form-level concerns (controlled inputs, submit handler, error
 * surface) so each page is just a thin "what do we call" wrapper.
 */
export function AuthCard({
  mode,
}: {
  mode: 'login' | 'register'
}) {
  const { login, register } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const isLogin = mode === 'login'
  const submitLabel = isLogin ? 'Sign in' : 'Create account'

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    if (!email.trim() || !password) {
      setError('Email and password are required.')
      return
    }
    if (!isLogin && password.length < 10) {
      setError('Password must be at least 10 characters.')
      return
    }
    setIsLoading(true)
    try {
      if (isLogin) {
        await login(email, password)
      } else {
        await register(email, password)
      }
      // AuthContext sets status to 'authed'; ProtectedRoute will render
      // the app on the next render. No navigate() needed.
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Something went wrong.'
      setError(msg)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-md flex-col items-center justify-center px-4">
      <div className="w-full rounded-2xl border border-line bg-surface p-6 shadow-lift sm:p-8">
        <div className="mb-6 flex items-center gap-3">
          <BrandMark />
          <div>
            <h1 className="text-lg font-semibold text-content">
              {isLogin ? 'Welcome back' : 'Create your account'}
            </h1>
            <p className="text-xs text-muted">
              {isLogin
                ? 'Sign in to ask questions about your data.'
                : 'A few details and you can start asking questions.'}
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Field
            id="email"
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            autoComplete="email"
            autoFocus
            required
          />
          <Field
            id="password"
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete={isLogin ? 'current-password' : 'new-password'}
            required
            hint={!isLogin ? 'At least 10 characters.' : undefined}
          />

          {error && (
            <div
              role="alert"
              className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading}
            className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-inset disabled:text-muted"
          >
            {isLoading && <Spinner />}
            {submitLabel}
          </button>
        </form>

        <div className="mt-5 border-t border-line pt-4 text-center text-xs text-muted">
          {isLogin ? (
            <>
              New here?{' '}
              <Link
                to="/register"
                className="font-medium text-brand-700 hover:text-brand-800"
              >
                Create an account
              </Link>
            </>
          ) : (
            <>
              Already have an account?{' '}
              <Link
                to="/login"
                className="font-medium text-brand-700 hover:text-brand-800"
              >
                Sign in
              </Link>
            </>
          )}
        </div>
      </div>
      <p className="mt-4 text-center text-[11px] text-muted">
        Your data stays on this server. Sessions are signed and expire.
      </p>
    </div>
  )
}

function Field({
  id,
  label,
  type,
  value,
  onChange,
  autoComplete,
  autoFocus,
  required,
  hint,
}: {
  id: string
  label: string
  type: string
  value: string
  onChange: (v: string) => void
  autoComplete?: string
  autoFocus?: boolean
  required?: boolean
  hint?: string
}): ReactNode {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-muted">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        required={required}
        className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-content placeholder:text-muted focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100"
      />
      {hint && <p className="mt-1 text-[11px] text-muted">{hint}</p>}
    </div>
  )
}

function BrandMark() {
  return (
    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-sm">
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none">
        <ellipse cx="12" cy="6" rx="7" ry="3" stroke="currentColor" strokeWidth="1.8" />
        <path d="M5 6v6c0 1.66 3.13 3 7 3s7-1.34 7-3V6" stroke="currentColor" strokeWidth="1.8" />
        <path d="M5 12v6c0 1.66 3.13 3 7 3s7-1.34 7-3v-6" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    </div>
  )
}

function Spinner() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 animate-spin" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" className="opacity-25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

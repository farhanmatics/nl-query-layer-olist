/// <reference types="vite/client" />

/**
 * Fetch wrapper hardened for the auth rollout (F0).
 *
 * Three things this owns:
 *  1. `credentials: 'include'` on every request — the session cookie rides
 *     along automatically, never an XSS-vulnerable in-memory token.
 *  2. CSRF double-submit: state-changing requests echo the
 *     `nlq_csrf` non-HttpOnly cookie value in the `X-CSRF-Token` header.
 *  3. 401 handling: when a request 401s (session expired server-side),
 *     notify the AuthContext so it can clear local user state and bounce
 *     the UI to /login. The `/api/auth/*` endpoints themselves never
 *     trigger this redirect (they own the login UI).
 */

export interface GuardReport {
  applied: string[]
  unresolved: string[]
}

export interface ClarifyBlock {
  prompt: string
  options: string[]
}

export interface QueryContext {
  inherited: boolean
  from_operation?: string | null
  carried: Record<string, unknown>
  clarify?: ClarifyBlock | null
}

export interface QueryResponse {
  operation: string | null
  filters: Record<string, unknown> | null
  result: Record<string, unknown> | null
  formatted_answer: string | null
  source: string | null
  error: string | null
  cached?: boolean
  guard?: GuardReport | null
  context?: QueryContext | null
}

export interface User {
  id: string
  email: string
  role: string | null
}

const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''

const CSRF_COOKIE_NAME = 'nlq_csrf'

/** Read a single cookie value by name (returns null if absent). */
function getCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const prefix = `${name}=`
  for (const part of document.cookie.split(';')) {
    const trimmed = part.trim()
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length))
    }
  }
  return null
}

/** Pull the CSRF token out of the non-HttpOnly cookie. */
export function getCsrfToken(): string | null {
  return getCookie(CSRF_COOKIE_NAME)
}

// --- 401 hook ---------------------------------------------------------------

type UnauthorizedHandler = (path: string) => void
let onUnauthorized: UnauthorizedHandler | null = null

/** Called by AuthContext on mount so the fetch layer can ping it on 401. */
export function setUnauthorizedHandler(fn: UnauthorizedHandler | null) {
  onUnauthorized = fn
}

// --- Errors ----------------------------------------------------------------

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, message: string, body: unknown) {
    super(message)
    this.status = status
    this.body = body
  }
}

/** True when the in-flight request was cancelled by the caller (F3). */
export class AbortError extends Error {
  constructor() {
    super('Request was cancelled')
    this.name = 'AbortError'
  }
}

interface FetchOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  // When true, do not auto-redirect on 401 (used by the auth endpoints
  // themselves so the login form can show the error inline).
  skipAuthRedirect?: boolean
  // AbortSignal for cancellation (F3 polish — cancel button).
  signal?: AbortSignal
}

async function request<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET'
  const isStateChanging = method !== 'GET'
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (isStateChanging) {
    const csrf = getCsrfToken()
    if (csrf) headers['X-CSRF-Token'] = csrf
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    credentials: 'include',
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  }).catch((e: unknown) => {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new AbortError()
    }
    throw e
  })
  if (res.status === 401 && !opts.skipAuthRedirect) {
    onUnauthorized?.(path)
    // Also try to surface the body so callers can still read the error.
  }
  if (!res.ok) {
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      /* not JSON */
    }
    const detail =
      body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : res.statusText
    throw new ApiError(res.status, detail, body)
  }
  // 204 No Content
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// --- Public API ------------------------------------------------------------

export async function query(
  question: string,
  sessionId?: string,
  options: { signal?: AbortSignal } = {},
): Promise<QueryResponse> {
  return request<QueryResponse>('/api/query', {
    method: 'POST',
    body: sessionId ? { question, session_id: sessionId } : { question },
    signal: options.signal,
  })
}

export async function checkHealth(): Promise<{
  db: string
  llm: string
  timestamp: string
}> {
  return request('/api/health', { skipAuthRedirect: true })
}

export async function fetchMe(): Promise<User | null> {
  try {
    return await request<User>('/api/auth/me', { skipAuthRedirect: true })
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null
    throw e
  }
}

export async function login(
  email: string,
  password: string,
): Promise<User> {
  return request<User>('/api/auth/login', {
    method: 'POST',
    body: { email, password },
    skipAuthRedirect: true,
  })
}

export async function register(
  email: string,
  password: string,
): Promise<User> {
  return request<User>('/api/auth/register', {
    method: 'POST',
    body: { email, password },
    skipAuthRedirect: true,
  })
}

export async function logout(): Promise<void> {
  await request<{ ok: boolean }>('/api/auth/logout', {
    method: 'POST',
    skipAuthRedirect: true,
  })
}

/** Seed a CSRF cookie for unauthenticated users (so register/login can
 * include the header). Cheap to call multiple times — the server just
 * rotates the cookie. */
export async function seedCsrf(): Promise<void> {
  await request<{ ok: boolean }>('/api/auth/csrf', {
    method: 'GET',
    skipAuthRedirect: true,
  })
}

// --- Session API (F1) -------------------------------------------------------

export interface SessionMeta {
  id: string
  title: string | null
  created_at: string
  last_active_at: string
}

export interface MessageRecord {
  id: string
  role: 'user' | 'assistant'
  question: string | null
  response: QueryResponse | null
  created_at: string
}

export async function listSessions(): Promise<SessionMeta[]> {
  return request<SessionMeta[]>('/api/sessions', { skipAuthRedirect: true })
}

export async function createSession(title?: string): Promise<SessionMeta> {
  return request<SessionMeta>('/api/sessions', {
    method: 'POST',
    body: { title: title ?? null },
  })
}

export async function renameSession(
  id: string,
  title: string,
): Promise<SessionMeta> {
  return request<SessionMeta>(`/api/sessions/${id}`, {
    method: 'PATCH',
    body: { title },
  })
}

export async function deleteSession(id: string): Promise<void> {
  await request<{ ok: boolean }>(`/api/sessions/${id}`, {
    method: 'DELETE',
  })
}

export async function listMessages(id: string): Promise<MessageRecord[]> {
  return request<MessageRecord[]>(`/api/sessions/${id}/messages`, {
    skipAuthRedirect: true,
  })
}

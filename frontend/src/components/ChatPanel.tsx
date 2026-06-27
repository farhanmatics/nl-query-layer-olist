import { useEffect, useRef, useState } from 'react'
import { MessageBubble } from './MessageBubble'
import type { Message } from '../App'

interface ChatPanelProps {
  messages: Message[]
  isLoading: boolean
  health: 'checking' | 'online' | 'offline'
  onSendMessage: (message: string) => Promise<void>
}

const EXAMPLES = [
  'How many delivered orders in São Paulo last month?',
  'What was our total revenue last year?',
  'Show revenue by state this year',
  'Top 5 products by revenue',
  'How many low reviews did we get last month?',
]

export function ChatPanel({ messages, isLoading, health, onSendMessage }: ChatPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [value, setValue] = useState('')

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  const send = (text: string) => {
    const t = text.trim()
    if (!t || isLoading) return
    setValue('')
    void onSendMessage(t)
  }

  return (
    <div className="my-4 flex h-[calc(100%-2rem)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-lift">
      {/* Header */}
      <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-3">
          <BrandMark />
          <div>
            <h1 className="text-base font-semibold leading-tight text-slate-900">
              Olist Query Assistant
            </h1>
            <p className="text-xs text-slate-500">
              Exact answers from your database — no SQL, no analyst
            </p>
          </div>
        </div>
        <HealthPill health={health} />
      </header>

      {/* Transcript */}
      <div className="scroll-slim flex-1 overflow-y-auto px-4 py-5 sm:px-5">
        {messages.length === 0 ? (
          <EmptyState onPick={send} disabled={isLoading} />
        ) : (
          <div className="space-y-1">
            {messages.map(msg => (
              <MessageBubble
                key={msg.id}
                role={msg.role}
                content={msg.content}
                response={msg.response}
                at={msg.at}
              />
            ))}
            {isLoading && <TypingIndicator />}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Composer */}
      <div className="border-t border-slate-100 bg-white/80 px-4 py-3 sm:px-5 sm:py-4">
        <form
          onSubmit={e => {
            e.preventDefault()
            send(value)
          }}
          className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-2 py-1.5 transition focus-within:border-brand-400 focus-within:bg-white focus-within:ring-2 focus-within:ring-brand-100"
        >
          <input
            value={value}
            onChange={e => setValue(e.target.value)}
            type="text"
            autoFocus
            placeholder="Ask about orders, revenue, reviews…"
            aria-label="Ask a question"
            className="flex-1 bg-transparent px-2 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
          />
          <button
            type="submit"
            disabled={isLoading || !value.trim()}
            aria-label="Send question"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
          >
            {isLoading ? <Spinner /> : <SendIcon />}
          </button>
        </form>
        <p className="mt-2 px-1 text-[11px] text-slate-400">
          Every answer is computed in SQL and cited to its source tables.
        </p>
      </div>
    </div>
  )
}

function EmptyState({ onPick, disabled }: { onPick: (q: string) => void; disabled: boolean }) {
  return (
    <div className="mx-auto flex h-full max-w-lg flex-col items-center justify-center py-8 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 ring-1 ring-brand-100">
        <SparkIcon />
      </div>
      <h2 className="text-lg font-semibold text-slate-800">Ask a question in plain English</h2>
      <p className="mt-1.5 text-sm text-slate-500">
        I translate it into a verified database query and return the exact number —
        with the source so you can trust it.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        {EXAMPLES.map(ex => (
          <button
            key={ex}
            onClick={() => onPick(ex)}
            disabled={disabled}
            className="rounded-full border border-slate-200 bg-white px-3.5 py-1.5 text-left text-xs font-medium text-slate-600 shadow-sm transition hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700 disabled:opacity-50"
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex items-end gap-2.5 py-2 animate-fade-in-up">
      <BrandMark small />
      <div className="flex items-center gap-1 rounded-2xl rounded-bl-md bg-slate-100 px-4 py-3">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="typing-dot h-1.5 w-1.5 rounded-full bg-slate-400"
            style={{ animationDelay: `${i * 0.16}s` }}
          />
        ))}
      </div>
    </div>
  )
}

function HealthPill({ health }: { health: 'checking' | 'online' | 'offline' }) {
  const map = {
    checking: { dot: 'bg-amber-400', text: 'Connecting', cls: 'text-amber-700 bg-amber-50 ring-amber-100' },
    online: { dot: 'bg-emerald-500', text: 'Connected', cls: 'text-emerald-700 bg-emerald-50 ring-emerald-100' },
    offline: { dot: 'bg-rose-500', text: 'Offline', cls: 'text-rose-700 bg-rose-50 ring-rose-100' },
  }[health]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${map.cls}`}
      title="Live backend (database + model) status"
    >
      <span className={`h-1.5 w-1.5 rounded-full ${map.dot} ${health !== 'offline' ? 'animate-pulse' : ''}`} />
      {map.text}
    </span>
  )
}

export function BrandMark({ small = false }: { small?: boolean }) {
  const size = small ? 'h-7 w-7' : 'h-9 w-9'
  return (
    <div
      className={`${size} flex shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-sm`}
    >
      <svg viewBox="0 0 24 24" className={small ? 'h-4 w-4' : 'h-5 w-5'} fill="none">
        <ellipse cx="12" cy="6" rx="7" ry="3" stroke="currentColor" strokeWidth="1.8" />
        <path d="M5 6v6c0 1.66 3.13 3 7 3s7-1.34 7-3V6" stroke="currentColor" strokeWidth="1.8" />
        <path d="M5 12v6c0 1.66 3.13 3 7 3s7-1.34 7-3v-6" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    </div>
  )
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none">
      <path d="M3.4 20.4 21 12 3.4 3.6 3.4 10l12 2-12 2z" fill="currentColor" />
    </svg>
  )
}

function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none">
      <path
        d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.4 2.4M15.3 15.3l2.4 2.4M17.7 6.3l-2.4 2.4M8.7 15.3l-2.4 2.4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
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

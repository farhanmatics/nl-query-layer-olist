import { QueryResponse } from '../api'
import { ResultCard } from './ResultCard'
import { BrandMark } from './ChatPanel'

interface MessageBubbleProps {
  role: 'user' | 'assistant'
  content: string
  response?: QueryResponse
  at: number
}

function time(at: number) {
  return new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function MessageBubble({ role, content, response, at }: MessageBubbleProps) {
  const isUser = role === 'user'
  const isError = !isUser && !!response?.error

  if (isUser) {
    return (
      <div className="flex animate-fade-in-up justify-end gap-2.5 py-2">
        <div className="flex flex-col items-end">
          <div className="max-w-md rounded-2xl rounded-br-md bg-brand-600 px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm">
            {content}
          </div>
          <span className="mt-1 px-1 text-[11px] text-slate-400">{time(at)}</span>
        </div>
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-200 text-sm font-semibold text-slate-600">
          You
        </div>
      </div>
    )
  }

  return (
    <div className="flex animate-fade-in-up gap-2.5 py-2">
      <BrandMark small />
      <div className="min-w-0 flex-1">
        <div
          className={`inline-block max-w-full rounded-2xl rounded-bl-md px-4 py-2.5 text-sm leading-relaxed ${
            isError ? 'bg-rose-50 text-rose-700' : 'bg-slate-100 text-slate-800'
          }`}
        >
          {content}
        </div>
        {response && !response.error && <ResultCard response={response} />}
        <div className="mt-1 px-1 text-[11px] text-slate-400">{time(at)}</div>
      </div>
    </div>
  )
}

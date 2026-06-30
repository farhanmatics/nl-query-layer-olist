import { QueryResponse } from '../api'
import { ResultCard } from './ResultCard'
import { CarryoverChip } from './CarryoverChip'
import { ClarifyPrompt } from './ClarifyPrompt'
import { BrandMark } from './ChatPanel'

interface MessageBubbleProps {
  role: 'user' | 'assistant'
  content: string
  response?: QueryResponse
  at: number
  disabled?: boolean
  onQuickReply?: (option: string) => void
}

function time(at: number) {
  return new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function MessageBubble({ role, content, response, at, disabled, onQuickReply }: MessageBubbleProps) {
  const isUser = role === 'user'
  const isError = !isUser && !!response?.error
  const clarify = response?.context?.clarify
  const isClarify = !isUser && !!clarify

  if (isUser) {
    return (
      <div className="flex animate-fade-in-up justify-end gap-2.5 py-2">
        <div className="flex flex-col items-end">
          <div className="max-w-md rounded-2xl rounded-br-md bg-brand-600 px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm">
            {content}
          </div>
          <span className="mt-1 px-1 text-[11px] text-muted">{time(at)}</span>
        </div>
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-inset text-sm font-semibold text-muted">
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
            isError
              ? 'bg-rose-50 text-rose-700'
              : isClarify
                ? 'bg-amber-50 text-amber-800'
                : 'bg-inset text-content'
          }`}
        >
          {content}
        </div>
        {isClarify && clarify && (
          <ClarifyPrompt
            clarify={clarify}
            disabled={!!disabled}
            onPick={opt => onQuickReply?.(opt)}
          />
        )}
        {!isError && !isClarify && <CarryoverChip context={response?.context} />}
        {response && !response.error && response.result && <ResultCard response={response} />}
        <div className="mt-1 px-1 text-[11px] text-muted">{time(at)}</div>
      </div>
    </div>
  )
}

import { QueryContext } from '../api'

/**
 * Renders what a follow-up turn inherited from the previous turn, so the
 * conversational state is *visible and verifiable* — the citation principle
 * extended to context. Shown only when the backend actually inherited
 * (context.inherited === true).
 *
 *   ↩ carried over: low reviews · last month · score ≤ 2
 */
export function CarryoverChip({ context }: { context?: QueryContext | null }) {
  if (!context || !context.inherited || context.clarify) return null

  const parts: string[] = []
  if (context.from_operation) parts.push(prettyOp(context.from_operation))
  for (const [key, value] of Object.entries(context.carried || {})) {
    const label = prettyFilter(key, value)
    if (label) parts.push(label)
  }
  if (parts.length === 0) return null

  return (
    <div className="mt-1.5 flex items-start gap-1.5 px-1 text-[11px] text-muted">
      <CarryIcon />
      <span>
        <span className="font-medium">carried over:</span>{' '}
        <span>{parts.join(' · ')}</span>
      </span>
    </div>
  )
}

function prettyOp(op: string): string {
  const map: Record<string, string> = {
    count_orders: 'order count',
    count_low_reviews: 'low reviews',
    get_revenue: 'revenue',
    top_products: 'top products',
    list_orders: 'order list',
    list_low_reviews: 'low reviews list',
    get_order_status: 'order status',
  }
  return map[op] || op.replace(/_/g, ' ')
}

function prettyFilter(key: string, value: unknown): string | null {
  if (value == null || value === '') return null
  switch (key) {
    case 'date_token':
      return String(value).replace(/_/g, ' ')
    case 'score_max':
      return `score ≤ ${value}`
    case 'city':
      return titleCase(String(value))
    case 'state':
      return String(value).toUpperCase()
    case 'status':
      return String(value)
    case 'category':
      return String(value)
    case 'by':
    case 'limit':
    case 'offset':
      return null // structural, not a user-facing filter
    default:
      return String(value)
  }
}

const titleCase = (s: string) => s.replace(/\b\w/g, c => c.toUpperCase())

function CarryIcon() {
  return (
    <svg viewBox="0 0 24 24" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" fill="none">
      <path
        d="M9 14 4 9l5-5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M4 9h11a5 5 0 0 1 5 5v1"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

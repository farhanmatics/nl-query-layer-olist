import { ChainStepTrace, MeasureMeta, QueryResponse, GuardReport } from '../api'

/* ---------- formatting helpers ---------- */

const num = (v: unknown): number => (typeof v === 'number' ? v : Number(v) || 0)
const str = (v: unknown): string => (v == null ? '' : String(v))

const fmtInt = (v: unknown) => num(v).toLocaleString('en-US')
const fmtBRL = (v: unknown) =>
  num(v).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 2 })
const fmtPct = (v: unknown) =>
  `${num(v).toLocaleString('en-US', { maximumFractionDigits: 1 })}%`

const fmtDate = (iso: unknown) => {
  const s = str(iso)
  if (!s) return '—'
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

const fmtDateRange = (range: unknown) => {
  if (!Array.isArray(range) || range.length < 2) return str(range)
  return `${fmtDate(range[0])} – ${fmtDate(range[1])}`
}

const COUNT_UNITS: Record<string, string> = {
  count_products: 'products in catalog',
  count_orders: 'orders',
  count_by_category: 'orders',
  count_by_status: 'orders',
  count_by_payment_type: 'orders',
  count_low_reviews: 'low reviews',
  late_deliveries: 'late deliveries',
}

/* ---------- root ---------- */

export function ResultCard({ response }: { response: QueryResponse }) {
  if (response.error) return null // error is rendered in the message bubble

  const op = response.operation
  const result = (response.result ?? {}) as Record<string, unknown>
  const filters = (response.filters ?? {}) as Record<string, unknown>

  let body: React.ReactNode = null

  if (op === 'get_order_status') body = <OrderDetail result={result} />
  else if (result.on_time_pct != null) body = <OnTimeRate result={result} />
  else if (result.avg_days != null) body = <StatCard value={String(result.avg_days)} unit="avg delivery days" />
  else if (result.count != null && typeof result.count === 'number')
    body = (
      <StatCard
        value={fmtInt(result.count)}
        unit={COUNT_UNITS[op ?? ''] ?? (num(result.count) === 1 ? 'result' : 'results')}
        tone={op === 'count_low_reviews' ? 'rose' : 'brand'}
      />
    )
  else if (Array.isArray(result.comparison)) body = <ComparisonTable result={result} />
  else if (Array.isArray(result.breakdown)) body = <BreakdownView result={result} op={op} />
  else if (op === 'get_revenue' || (result.revenue != null && !result.products)) body = <RevenueView result={result} />
  else if (op === 'top_products' || Array.isArray(result.products)) body = <TopProducts result={result} />
  else if (Array.isArray(result.categories)) body = <TopCategories result={result} />
  else if (op === 'list_orders') body = <OrdersTable result={result} />
  else if (op === 'list_low_reviews' || Array.isArray(result.reviews)) body = <ReviewsTable result={result} />
  else if (op === 'run_readonly_sql' && Array.isArray(result.rows)) body = <SqlRowsTable result={result} />
  else body = <pre className="overflow-x-auto rounded-lg bg-inset p-3 text-xs text-muted">{JSON.stringify(result, null, 2)}</pre>

  return (
    <div className="mt-2.5 max-w-xl overflow-hidden rounded-xl border border-line bg-surface shadow-soft">
      {response.chain && response.chain.length > 1 && (
        <ChainTrace chain={response.chain} planMode={response.context?.plan_mode} />
      )}
      <div className="p-4">{body}</div>
      <CardFooter
        filters={filters}
        source={response.source}
        guard={response.guard}
        cached={response.cached}
        measure={response.measure}
        metaOperation={response.meta_operation}
        operation={op}
      />
    </div>
  )
}

/* ---------- per-operation views ---------- */

function StatCard({ value, unit, tone = 'brand' }: { value: string; unit: string; tone?: 'brand' | 'rose' }) {
  const color =
    tone === 'rose' ? 'text-rose-600 dark:text-rose-400' : 'text-brand-600 dark:text-brand-400'
  return (
    <div className="py-2 text-center">
      <div className={`text-5xl font-bold tracking-tight tabular-nums ${color}`}>{value}</div>
      <div className="mt-1 text-sm font-medium text-muted">{unit}</div>
    </div>
  )
}

function OnTimeRate({ result }: { result: Record<string, unknown> }) {
  return (
    <div className="py-2 text-center">
      <div className="text-5xl font-bold tracking-tight tabular-nums text-brand-600 dark:text-brand-400">
        {fmtPct(result.on_time_pct)}
      </div>
      <div className="mt-1 text-sm font-medium text-muted">
        on-time delivery ({fmtInt(result.on_time_count)} of {fmtInt(result.delivered_count)} delivered)
      </div>
    </div>
  )
}

function RevenueView({ result }: { result: Record<string, unknown> }) {
  const breakdown = result.breakdown as Array<Record<string, unknown>> | undefined
  if (Array.isArray(breakdown)) {
    const groupBy = str(result.group_by) || 'group'
    const rows = breakdown.map(r => ({ label: str(r[groupBy]) || '—', value: num(r.revenue) }))
    return (
      <div>
        <SectionLabel>Revenue by {groupBy}</SectionLabel>
        <BarList rows={rows} format={fmtBRL} />
      </div>
    )
  }
  return <StatCard value={fmtBRL(result.revenue)} unit="total revenue" />
}

function TopCategories({ result }: { result: Record<string, unknown> }) {
  const by = str(result.by) || 'revenue'
  const categories = (result.categories as Array<Record<string, unknown>>) || []
  if (categories.length === 1) {
    const c = categories[0]
    return (
      <div className="py-1 text-center">
        <div className="text-[11px] uppercase tracking-wide text-muted">Top category by {by}</div>
        <div className="mt-1 text-lg font-semibold text-content">{str(c.category)}</div>
        <div className="mt-2 text-3xl font-bold tabular-nums text-brand-600 dark:text-brand-400">
          {by === 'revenue' ? fmtBRL(c.value) : fmtInt(c.value)}
        </div>
      </div>
    )
  }
  const rows = categories.map(c => ({
    label: str(c.category),
    value: num(c.value),
  }))
  return (
    <div>
      <SectionLabel>Top categories by {by === 'revenue' ? 'revenue' : 'units sold'}</SectionLabel>
      <BarList rows={rows} format={by === 'revenue' ? fmtBRL : fmtInt} ranked />
    </div>
  )
}

function ChainTrace({
  chain,
  planMode,
}: {
  chain: ChainStepTrace[]
  planMode?: string | null
}) {
  return (
    <div className="border-b border-line bg-inset/40 px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">
          Planner chain
        </span>
        {planMode && (
          <span className="rounded-md bg-surface px-1.5 py-0.5 text-[10px] font-medium text-muted ring-1 ring-line">
            {planMode} · {chain.length} steps
          </span>
        )}
      </div>
      <ol className="space-y-2">
        {chain.map(step => (
          <li key={step.step} className="flex gap-2 text-xs">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-100 text-[10px] font-bold text-brand-700 dark:bg-brand-900/40 dark:text-brand-300">
              {step.step + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-medium text-content">
                {step.meta_tool} → {step.operation}
              </div>
              <div className="mt-0.5 truncate font-mono text-[10px] text-muted">
                {summarizeStepResult(step.result)}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

function summarizeStepResult(result: Record<string, unknown>): string {
  if (Array.isArray(result.categories) && result.categories[0]) {
    const c = result.categories[0] as Record<string, unknown>
    return `category=${c.category}, value=${c.value}`
  }
  if (Array.isArray(result.products) && result.products[0]) {
    const p = result.products[0] as Record<string, unknown>
    return `product=${p.product_id ?? p.category}, value=${p.value}`
  }
  if (result.count != null) return `count=${result.count}`
  return JSON.stringify(result).slice(0, 80)
}

function TopProducts({ result }: { result: Record<string, unknown> }) {
  const by = str(result.by) || 'count'
  const products = (result.products as Array<Record<string, unknown>>) || []
  if (products.length === 1) {
    const p = products[0]
    return (
      <div className="py-1 text-center">
        <div className="text-[11px] uppercase tracking-wide text-muted">Top product by {by === 'revenue' ? 'revenue' : 'units'}</div>
        <div className="mt-1 truncate font-mono text-sm text-content">{str(p.product_id)}</div>
        {p.category && <div className="mt-0.5 text-xs text-muted">{str(p.category)}</div>}
        <div className="mt-2 text-3xl font-bold tabular-nums text-brand-600 dark:text-brand-400">
          {by === 'revenue' ? fmtBRL(p.value) : fmtInt(p.value)}
        </div>
      </div>
    )
  }
  const rows = products.map(p => ({
    label: str(p.category) || str(p.product_id).slice(0, 10),
    value: num(p.value),
  }))
  return (
    <div>
      <SectionLabel>Top {rows.length} products by {by === 'revenue' ? 'revenue' : 'units sold'}</SectionLabel>
      <BarList rows={rows} format={by === 'revenue' ? fmtBRL : fmtInt} ranked />
    </div>
  )
}

function BreakdownView({ result, op }: { result: Record<string, unknown>; op: string | null }) {
  const breakdown = (result.breakdown as Array<Record<string, unknown>>) || []
  const labelKey =
    breakdown[0]?.status != null
      ? 'status'
      : breakdown[0]?.score != null
        ? 'score'
        : breakdown[0]?.payment_type != null
          ? 'payment_type'
          : breakdown[0]?.state != null
            ? 'state'
            : 'label'
  const valueKey = breakdown[0]?.revenue != null ? 'revenue' : 'count'
  const title =
    op === 'fulfillment_status_breakdown'
      ? 'Orders by status'
      : op === 'payment_type_breakdown'
        ? 'Payment mix'
        : op === 'review_score_distribution'
          ? 'Reviews by score'
          : 'Breakdown'
  const rows = breakdown.map(r => ({
    label: str(r[labelKey]) || '—',
    value: num(r[valueKey]),
  }))
  return (
    <div>
      <SectionLabel>{title}</SectionLabel>
      <BarList rows={rows} format={valueKey === 'revenue' ? fmtBRL : fmtInt} ranked />
    </div>
  )
}

function ComparisonTable({ result }: { result: Record<string, unknown> }) {
  const rows = (result.comparison as Array<Record<string, unknown>>) || []
  const dimKey = rows[0]?.state != null ? 'state' : rows[0]?.category != null ? 'category' : 'seller_id'
  return (
    <div>
      <SectionLabel>Comparison</SectionLabel>
      <div className="-mx-1 mt-1 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-muted">
            <tr className="border-b border-line">
              <th className="px-2 py-1.5 font-medium">{dimKey.replace('_', ' ')}</th>
              <th className="px-2 py-1.5 font-medium">Orders</th>
              <th className="px-2 py-1.5 font-medium">Revenue</th>
              <th className="px-2 py-1.5 font-medium">Avg rating</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0">
                <td className="px-2 py-1.5 font-medium text-content">{str(r[dimKey]).toUpperCase()}</td>
                <td className="px-2 py-1.5 tabular-nums">{fmtInt(r.orders)}</td>
                <td className="px-2 py-1.5 tabular-nums">{fmtBRL(r.revenue)}</td>
                <td className="px-2 py-1.5 tabular-nums">{r.avg_rating != null ? num(r.avg_rating).toFixed(2) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function SqlRowsTable({ result }: { result: Record<string, unknown> }) {
  const rows = (result.rows as Array<Record<string, unknown>>) || []
  const columns = (result.columns as string[]) || (rows[0] ? Object.keys(rows[0]) : [])
  return (
    <div>
      <SectionLabel>{fmtInt(result.row_count ?? rows.length)} row(s)</SectionLabel>
      <div className="-mx-1 mt-1 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-muted">
            <tr className="border-b border-line">
              {columns.map(c => (
                <th key={c} className="px-2 py-1.5 font-medium">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0">
                {columns.map(c => (
                  <td key={c} className="px-2 py-1.5 tabular-nums text-content">
                    {str(r[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function OrdersTable({ result }: { result: Record<string, unknown> }) {
  const orders = (result.orders as Array<Record<string, unknown>>) || []
  const total = num(result.total_count)
  const offset = num(result.offset)
  return (
    <div>
      <SectionLabel>
        Showing {orders.length} of {fmtInt(total)} orders
        {total > orders.length ? ` (from #${offset + 1})` : ''}
      </SectionLabel>
      <div className="-mx-1 mt-1 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-muted">
            <tr className="border-b border-line">
              <th className="px-2 py-1.5 font-medium">Order</th>
              <th className="px-2 py-1.5 font-medium">Status</th>
              <th className="px-2 py-1.5 font-medium">Location</th>
              <th className="px-2 py-1.5 font-medium">Purchased</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0">
                <td className="px-2 py-1.5 font-mono text-muted">{str(o.order_id).slice(0, 8)}…</td>
                <td className="px-2 py-1.5"><StatusBadge status={str(o.order_status)} /></td>
                <td className="px-2 py-1.5 text-content">
                  {str(o.customer_city) || '—'}{o.customer_state ? `, ${str(o.customer_state).toUpperCase()}` : ''}
                </td>
                <td className="px-2 py-1.5 text-muted">{fmtDate(o.order_purchase_timestamp)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ReviewsTable({ result }: { result: Record<string, unknown> }) {
  const reviews = (result.reviews as Array<Record<string, unknown>>) || []
  const total = num(result.total_count)
  const offset = num(result.offset)
  return (
    <div>
      <SectionLabel>
        Showing {reviews.length} of {fmtInt(total)} low reviews
        {total > reviews.length ? ` (from #${offset + 1})` : ''}
      </SectionLabel>
      <div className="-mx-1 mt-1 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-muted">
            <tr className="border-b border-line">
              <th className="px-2 py-1.5 font-medium">Review</th>
              <th className="px-2 py-1.5 font-medium">Score</th>
              <th className="px-2 py-1.5 font-medium">Order</th>
              <th className="px-2 py-1.5 font-medium">Location</th>
              <th className="px-2 py-1.5 font-medium">Reviewed</th>
            </tr>
          </thead>
          <tbody>
            {reviews.map((r, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0">
                <td className="px-2 py-1.5 font-mono text-muted">{str(r.review_id).slice(0, 8)}…</td>
                <td className="px-2 py-1.5">
                  <span className="inline-flex items-center rounded-md bg-rose-50 px-1.5 py-0.5 text-[11px] font-semibold text-rose-700 ring-1 ring-rose-200">
                    {str(r.review_score)}★
                  </span>
                </td>
                <td className="px-2 py-1.5 font-mono text-muted">{str(r.order_id).slice(0, 8)}…</td>
                <td className="px-2 py-1.5 text-content">
                  {str(r.customer_city) || '—'}{r.customer_state ? `, ${str(r.customer_state).toUpperCase()}` : ''}
                </td>
                <td className="px-2 py-1.5 text-muted">{fmtDate(r.review_creation_date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function OrderDetail({ result }: { result: Record<string, unknown> }) {
  const dates = [
    { label: 'Purchased', value: result.order_purchase_timestamp },
    { label: 'Est. delivery', value: result.order_estimated_delivery_date },
    { label: 'Delivered', value: result.order_delivered_customer_date },
  ].filter(d => d.value)
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wide text-muted">Order</div>
          <div className="truncate font-mono text-sm text-content">{str(result.order_id)}</div>
        </div>
        <StatusBadge status={str(result.order_status)} large />
      </div>
      <div className="mt-3 flex items-center gap-1.5 text-sm text-content">
        <PinIcon />
        {str(result.customer_city) || 'Unknown'}
        {result.customer_state ? `, ${str(result.customer_state).toUpperCase()}` : ''}
      </div>
      {dates.length > 0 && (
        <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line pt-3">
          {dates.map(d => (
            <div key={d.label}>
              <div className="text-[11px] text-muted">{d.label}</div>
              <div className="text-xs font-medium text-content">{fmtDate(d.value)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ---------- shared primitives ---------- */

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="mb-2 text-sm font-semibold text-content">{children}</div>
}

function BarList({
  rows,
  format,
  ranked = false,
}: {
  rows: { label: string; value: number }[]
  format: (v: number) => string
  ranked?: boolean
}) {
  const max = Math.max(...rows.map(r => r.value), 1)
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2.5">
          {ranked && (
            <span className="w-4 shrink-0 text-right text-xs font-semibold text-muted">{i + 1}</span>
          )}
          <div className="min-w-0 flex-1">
            <div className="mb-0.5 flex items-baseline justify-between gap-2">
              <span className="truncate text-xs font-medium text-muted">{r.label}</span>
              <span className="shrink-0 text-xs font-semibold tabular-nums text-content">{format(r.value)}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-inset">
              <div
                className="h-full origin-left animate-grow-bar rounded-full bg-gradient-to-r from-brand-400 to-brand-600"
                style={{ width: `${Math.max((r.value / max) * 100, 2)}%` }}
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

const STATUS_TONES: Record<string, string> = {
  delivered: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  shipped: 'bg-sky-50 text-sky-700 ring-sky-200',
  canceled: 'bg-rose-50 text-rose-700 ring-rose-200',
  unavailable: 'bg-inset text-muted ring-line',
  processing: 'bg-amber-50 text-amber-700 ring-amber-200',
  invoiced: 'bg-violet-50 text-violet-700 ring-violet-200',
  approved: 'bg-teal-50 text-teal-700 ring-teal-200',
  created: 'bg-inset text-muted ring-line',
}

function StatusBadge({ status, large = false }: { status: string; large?: boolean }) {
  const tone = STATUS_TONES[status.toLowerCase()] || 'bg-inset text-muted ring-line'
  return (
    <span
      className={`inline-flex items-center rounded-full font-medium capitalize ring-1 ${tone} ${
        large ? 'px-3 py-1 text-sm' : 'px-2 py-0.5 text-[11px]'
      }`}
    >
      {status || 'unknown'}
    </span>
  )
}

/* ---------- footer: filters + trust signals ---------- */

function CardFooter({
  filters,
  source,
  guard,
  cached,
  measure,
  metaOperation,
  operation,
}: {
  filters: Record<string, unknown>
  source: string | null
  guard?: GuardReport | null
  cached?: boolean
  measure?: MeasureMeta | null
  metaOperation?: string | null
  operation?: string | null
}) {
  const chips = buildFilterChips(filters)
  const guarded = guard?.applied && guard.applied.length > 0
  const hasFooter = chips.length > 0 || source || guarded || cached || measure || metaOperation
  if (!hasFooter) return null

  return (
    <div className="space-y-2 border-t border-line bg-inset/60 px-4 py-3">
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {chips.map(c => (
            <span
              key={c}
              className="inline-flex items-center rounded-md bg-surface px-2 py-0.5 text-[11px] font-medium text-muted ring-1 ring-line"
            >
              {c}
            </span>
          ))}
        </div>
      )}

      {measure && (
        <div className="text-[11px] text-muted" title={measure.definition}>
          <span className="font-medium text-content">Measure:</span> {measure.definition}
          {metaOperation && operation && metaOperation !== operation && (
            <span className="ml-1.5 text-muted">
              ({metaOperation} → {operation})
            </span>
          )}
        </div>
      )}

      {guarded && (
        <div className="flex items-start gap-1.5 text-[11px] text-amber-700">
          <ShieldIcon />
          <span>
            <span className="font-medium">Auto-applied from your wording:</span>{' '}
            <span className="font-mono">{guard!.applied.join(', ')}</span>
          </span>
        </div>
      )}

      <div className="flex items-center justify-between gap-2">
        {source && (
          <div className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted">
            <VerifiedIcon />
            <span className="truncate" title={source}>Verified from {source}</span>
          </div>
        )}
        {cached && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-inset px-1.5 py-0.5 text-[10px] font-medium text-muted">
            <BoltIcon /> cached
          </span>
        )}
      </div>
    </div>
  )
}

function buildFilterChips(filters: Record<string, unknown>): string[] {
  const chips: string[] = []
  const f = filters || {}
  if (f.city) chips.push(`City: ${titleCase(str(f.city))}`)
  if (f.state) chips.push(`State: ${str(f.state).toUpperCase()}`)
  if (f.status) chips.push(`Status: ${str(f.status)}`)
  if (f.category) chips.push(`Category: ${str(f.category)}`)
  if (f.score_max != null) chips.push(`Score ≤ ${str(f.score_max)}`)
  if (f.date_range) chips.push(`📅 ${fmtDateRange(f.date_range)}`)
  return chips
}

const titleCase = (s: string) => s.replace(/\b\w/g, c => c.toUpperCase())

/* ---------- icons ---------- */

function PinIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-muted" fill="none">
      <path d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11Z" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="12" cy="10" r="2.5" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}
function ShieldIcon() {
  return (
    <svg viewBox="0 0 24 24" className="mt-0.5 h-3.5 w-3.5 shrink-0" fill="none">
      <path d="M12 3 5 6v5c0 4.4 3 7.6 7 9 4-1.4 7-4.6 7-9V6l-7-3Z" stroke="currentColor" strokeWidth="1.6" />
      <path d="m9.5 12 1.8 1.8 3.2-3.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}
function VerifiedIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 shrink-0 text-emerald-500" fill="none">
      <path d="M12 3 5 6v5c0 4.4 3 7.6 7 9 4-1.4 7-4.6 7-9V6l-7-3Z" stroke="currentColor" strokeWidth="1.6" />
      <path d="m9.5 12 1.8 1.8 3.2-3.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}
function BoltIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3 w-3" fill="currentColor">
      <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z" />
    </svg>
  )
}

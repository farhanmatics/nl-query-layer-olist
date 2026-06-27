import { QueryResponse, GuardReport } from '../api'

interface ResultCardProps {
  response: QueryResponse
}

export function ResultCard({ response }: ResultCardProps) {
  if (response.error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
        <div className="text-red-700 font-semibold">⚠️ Error</div>
        <div className="text-red-600 text-sm mt-1">{response.error}</div>
      </div>
    )
  }

  const { operation, result, formatted_answer, source, filters, guard } = response

  // Render based on operation type
  if (operation === 'get_order_status' && result) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-6 mb-4 shadow-sm">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Order Details</h3>
        <div className="space-y-3">
          <Field label="Order ID" value={result.order_id as string} />
          <Field
            label="Status"
            value={
              <span className="inline-block px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
                {result.order_status as string}
              </span>
            }
          />
          <Field label="Customer" value={`${result.customer_city}, ${result.customer_state}`} />
          <Field
            label="Purchased"
            value={new Date(result.order_purchase_timestamp as string).toLocaleDateString()}
          />
          {result.order_delivered_customer_date && (
            <Field
              label="Delivered"
              value={new Date(result.order_delivered_customer_date as string).toLocaleDateString()}
            />
          )}
        </div>
      </div>
    )
  }

  if (operation === 'count_orders' && result) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-6 mb-4 shadow-sm">
        <div className="text-center">
          <div className="text-5xl font-bold text-blue-600 mb-2">
            {(result.count as number).toLocaleString()}
          </div>
          <div className="text-gray-600 text-lg mb-4">
            {result.count === 1 ? 'order' : 'orders'}
          </div>
          {formatted_answer && (
            <div className="text-gray-700 italic mb-4">{formatted_answer}</div>
          )}
        </div>
        <GuardNote guard={guard} />
        {filters && <FiltersSummary filters={filters} />}
        {source && <Citation source={source} />}
      </div>
    )
  }

  // Default: show formatted answer or full result
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6 mb-4 shadow-sm">
      {formatted_answer && (
        <div className="text-gray-700 mb-4">{formatted_answer}</div>
      )}
      {result && Object.keys(result).length > 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded p-3 mb-4 overflow-x-auto">
          <pre className="text-sm text-gray-700">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
      <GuardNote guard={guard} />
      {filters && <FiltersSummary filters={filters} />}
      {source && <Citation source={source} />}
    </div>
  )
}

function GuardNote({ guard }: { guard?: GuardReport | null }) {
  if (!guard || !guard.applied || guard.applied.length === 0) return null

  return (
    <div className="mt-4 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
      <span aria-hidden className="text-amber-600">🛡️</span>
      <div className="text-sm text-amber-800">
        <span className="font-medium">Filters auto-applied</span> from your wording:{' '}
        <span className="font-mono">{guard.applied.join(', ')}</span>
      </div>
    </div>
  )
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center">
      <label className="font-medium text-gray-700">{label}:</label>
      <span className="text-gray-900">{value}</span>
    </div>
  )
}

function FiltersSummary({ filters }: { filters: Record<string, unknown> }) {
  const hasFilters = Object.keys(filters).some(k => filters[k])
  if (!hasFilters) return null

  return (
    <details className="mt-4 pt-4 border-t border-gray-200">
      <summary className="cursor-pointer text-sm font-medium text-gray-600 hover:text-gray-900">
        Applied filters
      </summary>
      <div className="mt-2 space-y-1">
        {Object.entries(filters).map(
          ([key, value]) =>
            value && (
              <div key={key} className="text-sm text-gray-600">
                <strong>{key}:</strong> {String(value)}
              </div>
            ),
        )}
      </div>
    </details>
  )
}

function Citation({ source }: { source: string }) {
  return (
    <div className="mt-4 pt-4 border-t border-gray-200">
      <small className="text-gray-500">
        <strong>Source:</strong> {source}
      </small>
    </div>
  )
}

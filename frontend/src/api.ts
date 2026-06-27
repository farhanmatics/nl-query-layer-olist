export interface GuardReport {
  applied: string[]
  unresolved: string[]
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
}

export async function query(question: string): Promise<QueryResponse> {
  const response = await fetch('/api/query', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ question }),
  })

  if (!response.ok) {
    throw new Error(`API error: ${response.statusText}`)
  }

  return response.json()
}

export async function checkHealth() {
  const response = await fetch('/api/health')
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.statusText}`)
  }
  return response.json()
}

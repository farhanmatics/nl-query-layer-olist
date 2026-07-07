/**
 * Generate a client-side message id for optimistic UI updates.
 *
 * crypto.randomUUID() requires a secure context (HTTPS or localhost).
 * On HTTP deployments (e.g. ECS public IP), it throws and would crash
 * React when appending messages — reload works because server ids are used.
 */
export function newLocalId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    try {
      return `local-${crypto.randomUUID()}`
    } catch {
      /* fall through — HTTP origin */
    }
  }
  return `local-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`
}

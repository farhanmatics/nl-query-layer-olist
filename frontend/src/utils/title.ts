/**
 * Derive a conversation title from its first user question: whitespace-
 * collapsed and truncated. Mirrors the backend's appdb.derive_session_title
 * so the sidebar shows the same label the server persists (no refetch needed).
 */
export function deriveTitle(question: string, maxLen = 60): string {
  const cleaned = question.trim().replace(/\s+/g, ' ')
  if (!cleaned) return 'New chat'
  return cleaned.length > maxLen
    ? cleaned.slice(0, maxLen - 1).trimEnd() + '…'
    : cleaned
}

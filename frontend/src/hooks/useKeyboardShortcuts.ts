import { useEffect } from 'react'

/**
 * Global keyboard shortcuts (F3 polish).
 *
 *   Cmd/Ctrl + K   →  new chat
 *   Esc            →  close mobile drawer (when open)
 *
 * The shortcuts are scoped to the chat page: register them only when
 * `enabled` is true so the login page doesn't accidentally trigger
 * "new chat" before the user is signed in.
 *
 * Inputs are NOT captured when the user is typing in an input/textarea
 * EXCEPT for Cmd/Ctrl+K which always works (matches the pattern of
 * command palettes — Cmd+K works even from a text field).
 */
export function useKeyboardShortcuts({
  enabled,
  onNewChat,
  onEscape,
}: {
  enabled: boolean
  onNewChat: () => void
  onEscape?: () => void
}) {
  useEffect(() => {
    if (!enabled) return
    const handler = (e: KeyboardEvent) => {
      // Cmd+K / Ctrl+K — new chat, regardless of focus.
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        onNewChat()
        return
      }
      // Esc — close drawer. Skip if the user is in a text field; Esc is
      // sometimes used to blur/cancel input there.
      if (e.key === 'Escape' && onEscape) {
        const target = e.target as HTMLElement | null
        const tag = target?.tagName?.toLowerCase()
        const inText = tag === 'input' || tag === 'textarea' || target?.isContentEditable
        if (!inText) {
          onEscape()
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [enabled, onNewChat, onEscape])
}

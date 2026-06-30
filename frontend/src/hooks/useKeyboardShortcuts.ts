import { useEffect } from 'react'

/**
 * Global keyboard shortcuts (F3 polish).
 *
 *   Cmd/Ctrl + K         →  new chat
 *   Cmd/Ctrl + B         →  toggle conversations drawer
 *   Cmd/Ctrl + Shift + O →  same as Cmd+B (alternative)
 *   Esc                  →  close the drawer (when open)
 *
 * The shortcuts are scoped to the chat page: register them only when
 * `enabled` is true so the login page doesn't accidentally trigger
 * "new chat" before the user is signed in.
 *
 * Inputs are NOT captured when the user is typing in an input/textarea
 * EXCEPT for the modifier shortcuts (Cmd+K / Cmd+B), which always work —
 * matches the pattern of command palettes.
 */
export function useKeyboardShortcuts({
  enabled,
  onNewChat,
  onToggleDrawer,
  onEscape,
}: {
  enabled: boolean
  onNewChat: () => void
  onToggleDrawer?: () => void
  onEscape?: () => void
}) {
  useEffect(() => {
    if (!enabled) return
    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      const key = e.key.toLowerCase()

      // Cmd+K — new chat, always (command-palette pattern).
      if (mod && !e.shiftKey && key === 'k') {
        e.preventDefault()
        onNewChat()
        return
      }

      // Cmd+B or Cmd+Shift+O — toggle the drawer. Shift modifier on 'o'
      // is how we sidestep 'B' conflicts in browsers (Cmd+B is sometimes
      // used for bold in form fields; we always preventDefault either way).
      if (mod && !onToggleDrawer) {
        // nothing
      }
      if (mod && onToggleDrawer) {
        const isToggleB = !e.shiftKey && key === 'b'
        const isToggleO = e.shiftKey && key === 'o'
        if (isToggleB || isToggleO) {
          e.preventDefault()
          onToggleDrawer()
          return
        }
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
  }, [enabled, onNewChat, onToggleDrawer, onEscape])
}

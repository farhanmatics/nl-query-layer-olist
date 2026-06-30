import { useEffect } from 'react'

/**
 * Subscribe a ref-bound handler to `pointerdown` events outside the ref's
 * element. Use for closing dropdowns / drawers when the user clicks
 * elsewhere. Skips the event when the target is inside the ref.
 */
export function useClickOutside(
  ref: React.RefObject<HTMLElement>,
  handler: () => void,
  enabled: boolean = true,
): void {
  useEffect(() => {
    if (!enabled) return
    const onDown = (e: PointerEvent) => {
      const el = ref.current
      if (!el) return
      if (el.contains(e.target as Node)) return
      handler()
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [ref, handler, enabled])
}

import { useEffect, useRef } from 'react'

/**
 * Swipe-to-close on mobile. Detects a leftward horizontal drag (touch
 * or pointer) on a ref-bound element and calls the handler when the
 * drag exceeds a threshold. Used by the conversations drawer so a
 * user can dismiss it the way they would a native sheet.
 *
 * Caveats:
 *  - Skips if the gesture starts on a horizontally-scrollable element
 *    (rare in our drawer, but cheap to be defensive).
 *  - Pointer events handle both touch and mouse; on a mouse the
 *    swipe only fires after release (pointerup), so the UI doesn't
 *    "follow" the cursor the way a touch swipe would. That's fine —
 *    the drawer's slide-out animation still happens.
 */
export function useSwipeToClose(
  ref: React.RefObject<HTMLElement>,
  onClose: () => void,
  options: { threshold?: number; enabled?: boolean } = {},
) {
  const { threshold = 80, enabled = true } = options
  const startX = useRef<number | null>(null)
  const startY = useRef<number | null>(null)
  // Tracks whether the gesture has been "claimed" by a horizontal
  // swipe (vs a vertical scroll). Once claimed, vertical movement
  // is ignored for the duration of the gesture.
  const isHorizontal = useRef<boolean>(false)

  useEffect(() => {
    if (!enabled) return
    const el = ref.current
    if (!el) return

    const onDown = (e: PointerEvent) => {
      // Only respond to primary-button / touch / pen.
      if (e.pointerType === 'mouse' && e.button !== 0) return
      startX.current = e.clientX
      startY.current = e.clientY
      isHorizontal.current = false
    }

    const onMove = (e: PointerEvent) => {
      if (startX.current === null || startY.current === null) return
      const dx = e.clientX - startX.current
      const dy = e.clientY - startY.current
      // Decide axis on the first significant move. Once decided, we
      // don't flip mid-gesture.
      if (!isHorizontal.current && Math.abs(dx) + Math.abs(dy) < 8) return
      if (!isHorizontal.current) {
        isHorizontal.current = Math.abs(dx) > Math.abs(dy)
        if (!isHorizontal.current) return
      }
      if (dx < -threshold) {
        onClose()
        // Reset so a single gesture doesn't fire multiple closes.
        startX.current = null
        startY.current = null
        isHorizontal.current = false
      }
    }

    const onUp = () => {
      startX.current = null
      startY.current = null
      isHorizontal.current = false
    }

    el.addEventListener('pointerdown', onDown)
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onUp)
    el.addEventListener('pointercancel', onUp)
    return () => {
      el.removeEventListener('pointerdown', onDown)
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', onUp)
      el.removeEventListener('pointercancel', onUp)
    }
  }, [ref, onClose, threshold, enabled])
}

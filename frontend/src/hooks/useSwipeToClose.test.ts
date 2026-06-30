import { describe, it, expect, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useRef } from 'react'
import { useSwipeToClose } from '../hooks/useSwipeToClose'

/**
 * PointerEvent constructor in jsdom is incomplete; the easiest way to
 * dispatch a pointer-style sequence in tests is to build plain
 * Event objects with the properties we set via defineProperty.
 */
function makePointerEvent(type: string, clientX: number, clientY: number, button = 0) {
  const e = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(e, 'clientX', { value: clientX })
  Object.defineProperty(e, 'clientY', { value: clientY })
  Object.defineProperty(e, 'pointerType', { value: 'touch' })
  Object.defineProperty(e, 'button', { value: button })
  return e
}

function setupHook(enabled = true, threshold = 80) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const onClose = vi.fn()
  const { result } = renderHook(() => {
    const ref = useRef<HTMLElement>(el)
    useSwipeToClose(ref, onClose, { enabled, threshold })
    return ref.current
  })
  return { el, onClose, ref: result }
}

function dispatchTo(el: HTMLElement, e: Event) {
  el.dispatchEvent(e)
}

describe('useSwipeToClose', () => {
  it('fires onClose on a leftward swipe past the threshold', () => {
    const { el, onClose } = setupHook()
    dispatchTo(el, makePointerEvent('pointerdown', 100, 200))
    dispatchTo(el, makePointerEvent('pointermove', 0, 200)) // dx=-100, > threshold
    expect(onClose).toHaveBeenCalledTimes(1)
    document.body.removeChild(el)
  })

  it('does NOT fire on a leftward swipe that is too short', () => {
    const { el, onClose } = setupHook()
    dispatchTo(el, makePointerEvent('pointerdown', 100, 200))
    dispatchTo(el, makePointerEvent('pointermove', 50, 200)) // dx=-50
    expect(onClose).not.toHaveBeenCalled()
    document.body.removeChild(el)
  })

  it('does NOT fire on a rightward (left-to-right) swipe', () => {
    const { el, onClose } = setupHook()
    dispatchTo(el, makePointerEvent('pointerdown', 0, 200))
    dispatchTo(el, makePointerEvent('pointermove', 200, 200)) // dx=+200
    expect(onClose).not.toHaveBeenCalled()
    document.body.removeChild(el)
  })

  it('does NOT fire on a vertical (scroll-like) gesture', () => {
    const { el, onClose } = setupHook()
    dispatchTo(el, makePointerEvent('pointerdown', 100, 100))
    dispatchTo(el, makePointerEvent('pointermove', 100, 0)) // dy=-100
    expect(onClose).not.toHaveBeenCalled()
    document.body.removeChild(el)
  })

  it('does nothing when enabled is false', () => {
    const { el, onClose } = setupHook(false)
    dispatchTo(el, makePointerEvent('pointerdown', 100, 200))
    dispatchTo(el, makePointerEvent('pointermove', 0, 200))
    expect(onClose).not.toHaveBeenCalled()
    document.body.removeChild(el)
  })
})

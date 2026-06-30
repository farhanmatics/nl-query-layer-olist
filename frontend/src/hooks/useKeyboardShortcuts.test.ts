import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts'

function fireKey(opts: { metaKey?: boolean; ctrlKey?: boolean; key: string; target?: EventTarget | null }) {
  const event = new KeyboardEvent('keydown', {
    key: opts.key,
    metaKey: !!opts.metaKey,
    ctrlKey: !!opts.ctrlKey,
    bubbles: true,
    cancelable: true,
  })
  if (opts.target) {
    Object.defineProperty(event, 'target', { value: opts.target })
  }
  window.dispatchEvent(event)
  return event
}

describe('useKeyboardShortcuts', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('fires onNewChat on Cmd+K (mac)', () => {
    const onNewChat = vi.fn()
    const onEscape = vi.fn()
    renderHook(() => useKeyboardShortcuts({ enabled: true, onNewChat, onEscape }))
    const ev = fireKey({ metaKey: true, key: 'k' })
    expect(onNewChat).toHaveBeenCalledTimes(1)
    expect(ev.defaultPrevented).toBe(true)
  })

  it('fires onNewChat on Ctrl+K (non-mac)', () => {
    const onNewChat = vi.fn()
    renderHook(() => useKeyboardShortcuts({ enabled: true, onNewChat }))
    fireKey({ ctrlKey: true, key: 'k' })
    expect(onNewChat).toHaveBeenCalledTimes(1)
  })

  it('fires onNewChat even when typing in an input (command-palette pattern)', () => {
    const onNewChat = vi.fn()
    renderHook(() => useKeyboardShortcuts({ enabled: true, onNewChat }))
    const input = document.createElement('input')
    document.body.appendChild(input)
    fireKey({ metaKey: true, key: 'k', target: input })
    expect(onNewChat).toHaveBeenCalledTimes(1)
    document.body.removeChild(input)
  })

  it('fires onEscape when not in a text field', () => {
    const onEscape = vi.fn()
    renderHook(() => useKeyboardShortcuts({ enabled: true, onNewChat: () => {}, onEscape }))
    fireKey({ key: 'Escape' })
    expect(onEscape).toHaveBeenCalledTimes(1)
  })

  it('does NOT fire onEscape when typing in an input', () => {
    const onEscape = vi.fn()
    renderHook(() => useKeyboardShortcuts({ enabled: true, onNewChat: () => {}, onEscape }))
    const input = document.createElement('input')
    document.body.appendChild(input)
    fireKey({ key: 'Escape', target: input })
    expect(onEscape).not.toHaveBeenCalled()
    document.body.removeChild(input)
  })

  it('does NOT fire onEscape when typing in a textarea', () => {
    const onEscape = vi.fn()
    renderHook(() => useKeyboardShortcuts({ enabled: true, onNewChat: () => {}, onEscape }))
    const ta = document.createElement('textarea')
    document.body.appendChild(ta)
    fireKey({ key: 'Escape', target: ta })
    expect(onEscape).not.toHaveBeenCalled()
    document.body.removeChild(ta)
  })

  it('does nothing when enabled is false', () => {
    const onNewChat = vi.fn()
    renderHook(() => useKeyboardShortcuts({ enabled: false, onNewChat }))
    fireKey({ metaKey: true, key: 'k' })
    expect(onNewChat).not.toHaveBeenCalled()
  })

  it('ignores unrelated keys', () => {
    const onNewChat = vi.fn()
    renderHook(() => useKeyboardShortcuts({ enabled: true, onNewChat }))
    fireKey({ key: 'a' })
    fireKey({ key: 'Enter' })
    expect(onNewChat).not.toHaveBeenCalled()
  })
})

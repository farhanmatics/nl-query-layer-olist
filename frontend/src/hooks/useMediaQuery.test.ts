import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useMediaQuery } from '../hooks/useMediaQuery'

describe('useMediaQuery', () => {
  const listeners: Array<(e: { matches: boolean }) => void> = []

  beforeEach(() => {
    listeners.length = 0
    // jsdom doesn't implement matchMedia by default.
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        addEventListener: (_: string, cb: (e: { matches: boolean }) => void) => {
          listeners.push(cb)
        },
        removeEventListener: (_: string, cb: (e: { matches: boolean }) => void) => {
          const i = listeners.indexOf(cb)
          if (i >= 0) listeners.splice(i, 1)
        },
        addListener: (cb: (e: { matches: boolean }) => void) => {
          listeners.push(cb)
        },
        removeListener: (cb: (e: { matches: boolean }) => void) => {
          const i = listeners.indexOf(cb)
          if (i >= 0) listeners.splice(i, 1)
        },
        dispatchEvent: () => true,
      })),
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns the current matchMedia().matches value', () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: true,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => true,
      })),
    })
    const { result } = renderHook(() => useMediaQuery('(min-width: 640px)'))
    expect(result.current).toBe(true)
  })

  it('returns false when matches is false', () => {
    const { result } = renderHook(() => useMediaQuery('(min-width: 640px)'))
    expect(result.current).toBe(false)
  })

  it('re-renders when the match flips via media-query change', () => {
    // The mock object is shared between all `matchMedia()` calls in this
    // test. The hook reads `mq.matches` inside the change handler, so we
    // flip that field on the same object the hook captured.
    let sharedMatches = false
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        get matches() {
          return sharedMatches
        },
        media: query,
        addEventListener: (_: string, cb: (e: { matches: boolean }) => void) => {
          listeners.push(cb)
        },
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => true,
      })),
    })
    const { result } = renderHook(() => useMediaQuery('(min-width: 640px)'))
    expect(result.current).toBe(false)
    sharedMatches = true
    act(() => {
      listeners.forEach(cb => cb({ matches: true }))
    })
    expect(result.current).toBe(true)
  })
})

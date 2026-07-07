import { describe, expect, it, vi } from 'vitest'
import { newLocalId } from './id'

describe('newLocalId', () => {
  it('falls back when randomUUID throws (HTTP / non-secure context)', () => {
    vi.stubGlobal('crypto', {
      randomUUID: () => {
        throw new Error('secure context required')
      },
    })
    const id = newLocalId()
    expect(id.startsWith('local-')).toBe(true)
    expect(id).not.toBe('local-undefined')
    vi.unstubAllGlobals()
  })

  it('uses randomUUID when available', () => {
    vi.stubGlobal('crypto', {
      randomUUID: () => 'test-uuid-1234',
    })
    expect(newLocalId()).toBe('local-test-uuid-1234')
    vi.unstubAllGlobals()
  })
})

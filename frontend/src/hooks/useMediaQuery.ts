import { useEffect, useState } from 'react'

/**
 * Subscribe to a CSS media query. SSR-safe (returns the initial value
 * during the first render). Re-renders only when the match flips.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mq = window.matchMedia(query)
    const onChange = () => setMatches(mq.matches)
    onChange() // sync once on mount
    if (mq.addEventListener) {
      mq.addEventListener('change', onChange)
      return () => mq.removeEventListener('change', onChange)
    }
    // Safari < 14 fallback
    mq.addListener(onChange)
    return () => mq.removeListener(onChange)
  }, [query])

  return matches
}

import '@testing-library/jest-dom/vitest'

// jsdom doesn't implement matchMedia by default; components that read
// the user's preferred color scheme (ThemeContext) need it. Provide a
// minimal no-op implementation.
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  })
}

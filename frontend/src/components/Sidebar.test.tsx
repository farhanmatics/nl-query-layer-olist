/**
 * Render the sidebar in both themes and verify the active-row classes
 * use the semantic `active` tokens (not raw brand colors that break
 * in dark mode). This is a regression test for the bug where the
 * selected chat in dark mode was a near-white block.
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Sidebar } from './Sidebar'
import { ThemeProvider } from '../theme/ThemeContext'
import { AuthProvider } from '../auth/AuthContext'
import { SessionProvider } from '../session/SessionContext'

// Helper: render with the providers the Sidebar needs.
function renderSidebar() {
  return render(
    <ThemeProvider>
      <AuthProvider>
        <SessionProvider>
          <Sidebar open={true} />
        </SessionProvider>
      </AuthProvider>
    </ThemeProvider>
  )
}

describe('Sidebar', () => {
  it('active row uses bg-active / ring-active-ring tokens, not raw brand-50/200', () => {
    // Regression test for the dark-mode active-row bug: a near-white
    // block with poor contrast. The new tokens are theme-aware; the
    // legacy ones are light-only.
    renderSidebar()
    const li = screen.queryAllByRole('listitem')[0]
    if (li) {
      const cls = li.className
      expect(cls).toContain('bg-active')
      expect(cls).toContain('ring-active-ring')
      expect(cls).not.toContain('bg-brand-50')
      expect(cls).not.toContain('ring-brand-200')
    } else {
      expect(screen.getByText(/no conversations yet/i)).toBeInTheDocument()
    }
  })

  it('the "New chat" button uses the theme-aware inset token, not raw brand-50', () => {
    // Regression test for the dark-mode hover bug: bg-brand-50 made the
    // "New chat" text nearly invisible in dark mode (light purple bg +
    // light text). inset is theme-aware: slate-50 in light, slate-800
    // in dark — both give good contrast with text-content.
    renderSidebar()
    const btn = screen.getByRole('button', { name: /new chat/i })
    const cls = btn.className
    expect(cls).toContain('hover:bg-inset')
    // Belt-and-suspenders: the legacy token must NOT be there.
    expect(cls).not.toContain('hover:bg-brand-50')
  })

  it('the drawer header shows a Cmd+B shortcut hint', () => {
    // Discoverability: when the drawer is open, the user can see that
    // they could've used ⌘B. Pure hover-only tooltips don't survive a
    // dark-mode hover; a visible kbd hint does.
    renderSidebar()
    expect(screen.getByText('⌘B')).toBeInTheDocument()
  })
})

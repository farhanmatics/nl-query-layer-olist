import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { AccountMenu } from './AccountMenu'
import { ThemeProvider } from '../theme/ThemeContext'

// Helper: render with the ThemeProvider (AccountMenu uses useTheme).
function renderAccountMenu(props: React.ComponentProps<typeof AccountMenu>) {
  return render(
    <ThemeProvider>
      <AccountMenu {...props} />
    </ThemeProvider>
  )
}

describe('AccountMenu', () => {
  it('shows the email in the trigger (non-compact)', () => {
    renderAccountMenu({ email: 'alice@example.com', onLogout: () => {} })
    // The trigger button has the email in its accessible label and content.
    const trigger = screen.getByRole('button', { name: /account menu/i })
    expect(trigger).toBeInTheDocument()
    expect(trigger.textContent).toContain('alice')
  })

  it('hides the email in the trigger (compact)', () => {
    renderAccountMenu({ email: 'alice@example.com', onLogout: () => {}, compact: true })
    const trigger = screen.getByRole('button', { name: /account menu/i })
    // In compact mode, only the avatar (initial) is shown — not the
    // email text. The full email is in the dropdown's header on open.
    expect(trigger.textContent?.includes('alice@example.com')).toBe(false)
    expect(trigger.textContent?.trim().length).toBeLessThan(5)
  })

  it('opens the menu and shows the privacy note', () => {
    renderAccountMenu({ email: 'alice@example.com', onLogout: () => {} })
    fireEvent.click(screen.getByRole('button', { name: /account menu/i }))
    expect(screen.getByText(/privacy/i)).toBeInTheDocument()
    expect(screen.getByText(/only you can see/i)).toBeInTheDocument()
  })

  it('calls onLogout when Sign out is clicked', () => {
    const onLogout = vi.fn().mockResolvedValue(undefined)
    renderAccountMenu({ email: 'alice@example.com', onLogout })
    fireEvent.click(screen.getByRole('button', { name: /account menu/i }))
    fireEvent.click(screen.getByText(/sign out/i))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })
})

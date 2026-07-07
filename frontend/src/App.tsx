import { Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { ChatPage } from './pages/ChatPage'
import { ErrorBoundary } from './components/ErrorBoundary'

/**
 * Route table (F0). All real UI lives behind a ProtectedRoute so the
 * cookie bootstrap in AuthContext runs first; a refresh on an authed
 * session silently re-uses it.
 */
function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <ErrorBoundary>
              <ChatPage />
            </ErrorBoundary>
          </ProtectedRoute>
        }
      />
    </Routes>
  )
}

export default App

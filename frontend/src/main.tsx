import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.tsx'
// Self-hosted Inter (variable) — bundled into the build, no Google Fonts CDN
// call, so nothing leaks to a third party (consistent with the data-stays-local
// product thesis). Loads offline / air-gapped.
import '@fontsource-variable/inter'
import './index.css'
import { ThemeProvider } from './theme/ThemeContext'
import { AuthProvider } from './auth/AuthContext'
import { SessionProvider } from './session/SessionContext'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
          <SessionProvider>
            <App />
          </SessionProvider>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>,
)

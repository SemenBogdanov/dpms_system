import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { ThemedToaster } from '@/components/ThemedToaster'
import { AuthProvider } from '@/contexts/AuthContext'
import { ThemeProvider } from '@/contexts/ThemeProvider'
import { installClientDiagnostics } from '@/lib/clientDiagnostics'
import App from './App'
import '@fontsource-variable/victor-mono'
import './index.css'

installClientDiagnostics()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <ThemeProvider>
          <AuthProvider>
            <App />
            <ThemedToaster />
          </AuthProvider>
        </ThemeProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>
)

window.requestAnimationFrame(() => {
  window.dispatchEvent(new Event('dpms:ready'))
  const url = new URL(window.location.href)
  if (url.searchParams.has('dpms_reload') || url.searchParams.has('chunk_reload')) {
    url.searchParams.delete('dpms_reload')
    url.searchParams.delete('chunk_reload')
    window.history.replaceState(window.history.state, '', url.toString())
  }
})

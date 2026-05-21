import { Toaster } from 'react-hot-toast'
import { useTheme } from '@/contexts/theme'

export function ThemedToaster() {
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  return (
    <Toaster
      position="top-right"
      toastOptions={{
        style: {
          background: isDark ? '#151922' : '#ffffff',
          border: isDark ? '1px solid #283142' : '1px solid #e5e7eb',
          color: isDark ? '#edf2f7' : '#0f172a',
          fontFamily: isDark ? 'Victor Mono Variable, ui-monospace, monospace' : undefined,
        },
      }}
    />
  )
}

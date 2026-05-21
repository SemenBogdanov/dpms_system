import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  THEME_STORAGE_KEY,
  ThemeContext,
  applyTheme,
  readStoredTheme,
  type ThemeMode,
} from '@/contexts/theme'

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>(readStoredTheme)

  useEffect(() => {
    applyTheme(theme)
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  }, [theme])

  const setTheme = useCallback((nextTheme: ThemeMode) => {
    setThemeState(nextTheme)
  }, [])

  const toggleTheme = useCallback(() => {
    setThemeState((current) => (current === 'dark' ? 'light' : 'dark'))
  }, [])

  const value = useMemo(() => ({ theme, setTheme, toggleTheme }), [theme, setTheme, toggleTheme])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

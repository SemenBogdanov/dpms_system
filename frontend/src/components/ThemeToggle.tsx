import { Moon, Sun } from 'lucide-react'
import { useTheme } from '@/contexts/theme'

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  const isDark = theme === 'dark'

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 bg-white text-gray-500 transition-colors hover:bg-gray-50 hover:text-gray-700"
      aria-label={isDark ? 'Включить светлую тему' : 'Включить темную тему'}
      title={isDark ? 'Светлая тема' : 'Темная тема'}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  )
}

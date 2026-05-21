import { Moon, Sparkles, Sun } from 'lucide-react'
import { type ThemeMode, useTheme } from '@/contexts/theme'

const themeOptions: Array<{ value: ThemeMode; label: string; title: string; icon: typeof Sun }> = [
  { value: 'light', label: 'Светлая', title: 'Светлая тема', icon: Sun },
  { value: 'dark', label: 'Темная', title: 'Темная тема', icon: Moon },
  { value: 'rose', label: 'Розовая', title: 'Розовая тема', icon: Sparkles },
]

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  return (
    <div
      className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white p-1 shadow-sm"
      role="group"
      aria-label="Выбор темы"
    >
      {themeOptions.map((option) => {
        const Icon = option.icon
        const selected = theme === option.value
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => setTheme(option.value)}
            className={`inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-500 transition-colors hover:bg-gray-50 hover:text-gray-700 ${
              selected ? 'bg-primary text-primary-foreground shadow-sm hover:bg-primary hover:text-primary-foreground' : ''
            }`}
            aria-label={option.title}
            aria-pressed={selected}
            title={option.title}
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only">{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}

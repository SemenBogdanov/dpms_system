// Preferences must never make the application depend on persistent storage.
const memory = new Map<string, string>()
const memoryOnly = new Set<string>()

export function readPreference(key: string): string | null {
  if (memoryOnly.has(key)) return memory.get(key) ?? null
  try {
    if (typeof window === 'undefined') return memory.get(key) ?? null
    const value = window.localStorage.getItem(key)
    if (value === null) memory.delete(key)
    else memory.set(key, value)
    return value
  } catch {
    return memory.get(key) ?? null
  }
}

export function writePreference(key: string, value: string): void {
  memory.set(key, value)
  try {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(key, value)
    memoryOnly.delete(key)
  } catch {
    // A failed write must take precedence over the old persistent value.
    memoryOnly.add(key)
  }
}

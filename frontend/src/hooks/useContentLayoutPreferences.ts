import { useSyncExternalStore } from 'react'
import {
  contentLayoutSections,
  contentLayoutStorageKey,
  normalizeContentLayoutPreference,
  parseContentLayoutPreferences,
  serializeContentLayoutPreferences,
} from '@/lib/contentLayout'
import type { ContentLayoutPreference, ContentLayoutPreferences } from '@/lib/contentLayout'
import { readPreference, writePreference } from '@/lib/preferenceStorage'

type Listener = () => void
type ContentLayoutStore = {
  getSnapshot: () => ContentLayoutPreferences
  subscribe: (listener: Listener) => () => void
  setPreference: (sectionId: string, value: ContentLayoutPreference) => boolean
  resetPreference: (sectionId: string) => boolean
}

const emptyPreferences: ContentLayoutPreferences = Object.freeze({})
const getServerSnapshot = () => emptyPreferences
const sectionIds = new Set(contentLayoutSections.map((section) => section.id))
const stores = new Map<string, ContentLayoutStore>()
const disabledStore: ContentLayoutStore = {
  getSnapshot: getServerSnapshot,
  subscribe: () => () => {},
  setPreference: () => false,
  resetPreference: () => false,
}

function immutablePreferences(preferences: ContentLayoutPreferences): ContentLayoutPreferences {
  Object.values(preferences).forEach((preference) => Object.freeze(preference))
  return Object.freeze(preferences)
}

function applyStoredSection(preferences: ContentLayoutPreferences, sectionId: string, raw: string | null) {
  const preference = parseContentLayoutPreferences(raw)[sectionId]
  if (preference) preferences[sectionId] = preference
  else delete preferences[sectionId]
}

// The shared helper deliberately hides write failures behind its memory fallback.
function readPersistentPreference(key: string): { value: string | null } | undefined {
  try {
    if (typeof window !== 'undefined') return { value: window.localStorage.getItem(key) }
  } catch {
    return undefined
  }
  return undefined
}

function createStore(userId: string): ContentLayoutStore {
  const sectionByKey = new Map(contentLayoutSections.map(({ id }) => [contentLayoutStorageKey(userId, id), id]))
  const initial: ContentLayoutPreferences = {}
  for (const [key, sectionId] of sectionByKey) {
    applyStoredSection(initial, sectionId, readPreference(key))
  }
  let snapshot = immutablePreferences(initial)
  let serialized = serializeContentLayoutPreferences(snapshot)
  const memoryOnly = new Set<string>()
  const listeners = new Set<Listener>()

  function publish(preferences: ContentLayoutPreferences) {
    const next = immutablePreferences(preferences)
    const nextSerialized = serializeContentLayoutPreferences(next)
    if (nextSerialized === serialized) return
    snapshot = next
    serialized = nextSerialized
    listeners.forEach((listener) => listener())
  }

  function refresh(sectionId?: string, includeMemoryOnly = false) {
    const next = { ...snapshot }
    for (const id of sectionId === undefined ? sectionIds : [sectionId]) {
      if (memoryOnly.has(id) && !includeMemoryOnly) continue
      const stored = readPersistentPreference(contentLayoutStorageKey(userId, id))
      if (!stored) continue
      memoryOnly.delete(id)
      applyStoredSection(next, id, stored.value)
    }
    publish(next)
  }

  function onStorage(event: StorageEvent) {
    const sectionId = event.key === null ? undefined : sectionByKey.get(event.key)
    if (event.key !== null && sectionId === undefined) return
    try {
      if (event.storageArea && event.storageArea !== window.localStorage) return
    } catch {
      return
    }
    // Read the current value: an already queued event may describe an older write.
    refresh(sectionId, true)
  }

  function persist(sectionId: string, preference?: ContentLayoutPreference): boolean {
    const key = contentLayoutStorageKey(userId, sectionId)
    // Each atomic storage write owns one section, so concurrent edits cannot erase other sections.
    const nextSerialized = serializeContentLayoutPreferences(preference ? { [sectionId]: preference } : {})
    writePreference(key, nextSerialized)
    const durable = readPersistentPreference(key)?.value === nextSerialized
    if (durable) memoryOnly.delete(sectionId)
    else memoryOnly.add(sectionId)
    const next = { ...snapshot }
    applyStoredSection(next, sectionId, nextSerialized)
    publish(next)
    return durable
  }

  return {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener)
      if (listeners.size === 1 && typeof window !== 'undefined') {
        window.addEventListener('storage', onStorage)
      }
      refresh()
      return () => {
        listeners.delete(listener)
        if (listeners.size === 0 && typeof window !== 'undefined') {
          window.removeEventListener('storage', onStorage)
        }
      }
    },
    setPreference(sectionId, value) {
      if (!sectionIds.has(sectionId)) return false
      const preference = normalizeContentLayoutPreference(value)
      if (!preference) return false
      refresh()
      return persist(sectionId, preference)
    },
    resetPreference(sectionId) {
      if (!sectionIds.has(sectionId)) return false
      refresh()
      return persist(sectionId)
    },
  }
}

export function useContentLayoutPreferences(userId: string | undefined | null) {
  let store = disabledStore
  if (userId) {
    const key = contentLayoutStorageKey(userId)
    const existing = stores.get(key)
    store = existing ?? createStore(userId)
    if (!existing) stores.set(key, store)
  }
  const preferences = useSyncExternalStore(store.subscribe, store.getSnapshot, getServerSnapshot)
  return { preferences, setPreference: store.setPreference, resetPreference: store.resetPreference }
}

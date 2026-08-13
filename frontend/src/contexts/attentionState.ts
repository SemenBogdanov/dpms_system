import { createContext, useContext } from 'react'
import type { AttentionSummary } from '@/api/types'

export type AttentionContextValue = {
  summary: AttentionSummary
  loading: boolean
  stale: boolean
  revision: number
  refresh: () => Promise<void>
}

export const AttentionContext = createContext<AttentionContextValue | null>(null)

export function useAttention() {
  const value = useContext(AttentionContext)
  if (!value) throw new Error('useAttention must be used inside AttentionProvider')
  return value
}

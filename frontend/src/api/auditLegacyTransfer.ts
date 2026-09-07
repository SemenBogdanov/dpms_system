import type { LegacyKind, LegacyMapping, LegacySheet } from './auditLegacy'
import { api } from './client'

export interface TransferCaseDecision {
  mode: 'existing' | 'create'
  target_case_id?: string | null
  title?: string | null
  digital_product?: string | null
  contract_date?: string | null
  fill_empty?: Array<'title' | 'digital_product' | 'contract_date'>
}
export interface TransferActorDecision {
  mode: 'user' | 'historical'
  user_id?: string | null
  historical_name?: string | null
}
export interface TransferRowDecision {
  action: 'create' | 'reuse' | 'fill_empty' | 'skip'
  target_id?: string | null
  fill_empty?: Array<'title' | 'digital_product' | 'work_type' | 'object_type' | 'source_clause' | 'source_evidence_text' | 'notes' | 'alpha_comment' | 'system_url' | 'alpha_result' | 'alpha_date' | 'commission_result' | 'commission_date'>
}
export interface TransferConfig {
  namespace: string
  datasets: LegacyMapping[]
  cases: Record<string, TransferCaseDecision>
  actors: Record<string, TransferActorDecision>
  row_decisions: Record<string, TransferRowDecision>
  apply_current_assignments: boolean
}
export interface TransferIssue {
  sheet_id?: string | null
  row?: number | null
  field?: string | null
  code: string
  severity: 'error' | 'warning'
  message: string
}
export interface TransferPreviewRow {
  row_key: string
  kind: LegacyKind
  sheet_id: string
  row: number | null
  source_key: string
  outcome: 'create' | 'reuse' | 'fill_empty' | 'duplicate' | 'skip' | 'blocked'
  target_id?: string | null
  changes: Record<string, unknown>
  issues: TransferIssue[]
}
export interface TransferPreviewPage {
  revision: number
  preview_hash: string
  rows: TransferPreviewRow[]
  total_rows: number
  next_offset: number | null
}
export interface TransferPreview extends TransferPreviewPage {
  ready: boolean
  counts: Record<string, number>
  issues: TransferIssue[]
}
export interface LegacyTransfer {
  id: string
  source_id: string
  namespace: string
  status: 'draft' | 'previewed' | 'committed' | 'rolled_back'
  revision: number
  config: TransferConfig
  preview: TransferPreview | null
  summary: Record<string, unknown>
  committed_at: string | null
  rolled_back_at: string | null
  created_at: string
  updated_at: string
}
export interface TransferOptions {
  source_id: string | null
  inspection: { sheets: LegacySheet[] } | null
  cases: Array<{ id: string; case_sequence: number; title: string; digital_product: string; contract_date: string | null; status: string }>
  users: Array<{ id: string; full_name: string; email: string; is_active: boolean; audit_enabled: boolean; eligible_current_assignment: boolean }>
  kinds: string[]
  fields: string[]
  canonical_labels: Record<string, string[]>
}

const root = '/api/audit/legacy-transfers'
const path = (id: string) => `${root}/${encodeURIComponent(id)}`
export const auditLegacyTransfer = {
  options: (sourceId: string, signal?: AbortSignal) => api.get<TransferOptions>(`${root}/options`, { source_id: sourceId }, { signal }),
  list: (sourceId: string, signal?: AbortSignal) => api.get<LegacyTransfer[]>(root, { source_id: sourceId }, { signal }),
  create: (sourceId: string, config: TransferConfig) => api.post<LegacyTransfer>(root, { source_id: sourceId, config }),
  get: (id: string, signal?: AbortSignal) => api.get<LegacyTransfer>(path(id), undefined, { signal }),
  config: (id: string, revision: number, config: TransferConfig) => api.put<LegacyTransfer>(`${path(id)}/config`, { revision, config }),
  preview: (id: string, revision: number) => api.post<LegacyTransfer>(`${path(id)}/preview`, { revision }),
  rows: (id: string, offset: number, signal?: AbortSignal) => api.get<TransferPreviewPage>(`${path(id)}/preview/rows`, { offset: String(offset), limit: '100' }, { signal }),
  commit: (id: string, revision: number, previewHash: string) => api.post<LegacyTransfer>(`${path(id)}/commit`, { revision, preview_hash: previewHash, confirm: true }),
  rollback: (id: string, revision: number, reason: string) => api.post<LegacyTransfer>(`${path(id)}/rollback`, { revision, reason, confirm: true }),
}

import { api } from './client'

export type LegacyKind = 'cases' | 'atoms' | 'assignments' | 'events' | 'daily_totals'
export interface LegacyColumn { column: string; label: string }
export interface LegacyMapping {
  sheet_id: string
  header_row: number
  kind: LegacyKind
  fields: Record<string, string>
}
export interface LegacySheet {
  id: string
  name: string
  row_count: number
  column_count: number
  formula_count: number
  header_row: number
  columns: LegacyColumn[]
  suggested_mapping: { kind: LegacyKind; fields: Record<string, string> }
}
export interface LegacyReport {
  sheet_id: string
  header_row: number
  kind: LegacyKind
  total_rows: number
  valid_rows: number
  error_rows: number
  warning_rows: number
  duplicate_rows: number
  issues: Array<{ row: number | null; column: string | null; code: string; severity: 'error' | 'warning'; message: string }>
  issue_count: number
  preview_rows: Array<{ row: number; values: Record<string, string | null> }>
  columns: LegacyColumn[]
  unmapped_columns: string[]
  ready_for_import: false
}
export interface LegacyBatch {
  id: string
  sha256: string
  size_bytes: number
  status: 'uploaded' | 'checked'
  created_at: string
  updated_at: string
  revision: number
  inspection: { parser_version: string; sheets: LegacySheet[] }
  mapping: LegacyMapping | null
  report: LegacyReport | null
}

export const LEGACY_MAX_FILE_BYTES = 10 * 1024 * 1024
export const LEGACY_KINDS: Record<LegacyKind, string> = {
  cases: 'Договоры', atoms: 'Атомы', assignments: 'Назначения', events: 'События', daily_totals: 'Дневные итоги',
}
export const LEGACY_FIELDS = {
  case_key: 'Код договора', digital_product: 'Цифровой продукт', contract_date: 'Дата договора',
  atom_key: 'Код атома', title: 'Название атома', source_clause: 'Пункт источника', work_type: 'Вид работы',
  object_type: 'Тип объекта', state: 'Статус', alpha_result: 'Результат альфа-проверки', alpha_date: 'Дата альфа-проверки',
  commission_result: 'Результат комиссии', commission_date: 'Дата комиссии', system_url: 'Ссылка на систему',
  assignee_email: 'Email ответственного', actor_name: 'Имя участника', assigned_at: 'Дата назначения',
  is_current: 'Текущее назначение', occurred_at: 'Дата события', event_key: 'Код события', event_type: 'Тип события',
  metric_date: 'Дата показателя', metric_type: 'Тип показателя', value: 'Значение',
} as const
export type LegacyField = keyof typeof LEGACY_FIELDS
export const LEGACY_REQUIRED: Record<LegacyKind, LegacyField[]> = {
  cases: ['case_key', 'digital_product'],
  atoms: ['case_key', 'atom_key', 'title'],
  assignments: ['case_key', 'assignee_email', 'assigned_at'],
  events: ['case_key', 'event_key', 'event_type', 'occurred_at'],
  daily_totals: ['case_key', 'metric_date', 'metric_type', 'value'],
}

const root = '/api/audit/legacy-imports'
const batchPath = (id: string) => `${root}/${encodeURIComponent(id)}`
export const auditLegacy = {
  list: (signal?: AbortSignal) => api.get<LegacyBatch[]>(root, undefined, { signal }),
  get: (id: string, signal?: AbortSignal) => api.get<LegacyBatch>(batchPath(id), undefined, { signal }),
  upload: (file: File) => {
    const data = new FormData()
    data.append('file', file)
    return api.upload<LegacyBatch>(root, data)
  },
  check: (id: string, revision: number, mapping: LegacyMapping) =>
    api.put<LegacyBatch>(`${batchPath(id)}/mapping`, { revision, mapping }),
  source: (id: string) => api.blob(`${batchPath(id)}/source`),
  remove: (id: string, revision: number) => api.delete<void>(`${batchPath(id)}?revision=${revision}`),
}

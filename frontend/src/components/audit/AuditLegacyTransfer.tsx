import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type MutableRefObject } from 'react'
import { CheckCircle2, ChevronLeft, ChevronRight, ClipboardCheck, Link2, Loader2, Plus, RefreshCcw, RotateCcw, Save, Trash2, X } from 'lucide-react'
import { LEGACY_FIELDS, LEGACY_KINDS, LEGACY_REQUIRED, type LegacyBatch, type LegacyKind, type LegacyMapping, type LegacySheet } from '@/api/auditLegacy'
import { cn } from '@/lib/utils'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'
import { auditLegacyTransfer, type LegacyTransfer, type TransferActorDecision, type TransferCaseDecision, type TransferConfig, type TransferOptions, type TransferPreview, type TransferPreviewPage, type TransferRowDecision } from '@/api/auditLegacyTransfer'
import { ApiError } from '@/api/client'

const control = 'min-h-11 h-11 w-full min-w-0 rounded-md border border-border bg-surface px-3 text-base text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50'
const button = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed'
const secondary = `${button} border border-border bg-surface text-foreground hover:bg-muted`
const fields: Record<string, string> = { ...LEGACY_FIELDS, occurred_at: 'Подтверждённая дата события / проверки' }
export type TransferDataset = LegacyMapping
const PendingTranslations = createContext<(id: string, pending: boolean) => void>(() => {})
const CanonicalLabels = createContext<Record<string, string[]>>({})
const valueOptions: Record<string, Record<string, string>> = {
  is_current: { true: 'Да', false: 'Нет' },
  event_type: { atom_status_changed: 'Изменение статуса атома', alpha_reviewed: 'Альфа-проверка', commission_reviewed: 'Комиссия', assignment: 'Назначение' },
  metric_type: { verified: 'Проверено', alpha_reviewed: 'Альфа-проверка', commission_reviewed: 'Комиссия' },
}

function CanonicalValue({ field, value, onChange, disabled, label }: {
  field: string; value: string; onChange: (value: string) => void; disabled: boolean; label: string
}) {
  const canonical = useContext(CanonicalLabels)[field]
  const choices = canonical ? Object.fromEntries(canonical.map((item) => [item, valueOptions[field]?.[item] ?? item])) : valueOptions[field]
  return choices ? <select aria-label={label} className={control} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
    <option value="">Не задано</option>{value && !Object.prototype.hasOwnProperty.call(choices, value) && <option value={value}>{value}</option>}
    {Object.entries(choices).map(([key, name]) => <option key={key} value={key}>{name}</option>)}
  </select> : <input aria-label={label} autoComplete="off" className={control} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
}

function Translations({ field, value, onChange, disabled, name }: {
  field: string; value: Record<string, string>; onChange: (value: Record<string, string>) => void; disabled: boolean; name: string
}) {
  const [source, setSource] = useState('')
  const [target, setTarget] = useState('')
  const [error, setError] = useState('')
  const id = useId()
  const reportPending = useContext(PendingTranslations)
  useEffect(() => { reportPending(id, Boolean(source || target)) }, [id, reportPending, source, target])
  useEffect(() => () => reportPending(id, false), [id, reportPending])
  return <div className="min-w-0 space-y-2">
    {Object.entries(value).map(([from, to]) => <div key={from} className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)_44px] items-center gap-2">
      <span className="text-sm [overflow-wrap:anywhere]">{from}</span>
      <CanonicalValue field={field} label={`${name}: значение для ${from}`} value={to} disabled={disabled} onChange={(next) => onChange({ ...value, [from]: next })} />
      <button type="button" className={cn(secondary, 'h-11 w-11 p-0')} disabled={disabled} aria-label={`Удалить перевод ${from}`} title={`Удалить перевод ${from}`} onClick={() => onChange(Object.fromEntries(Object.entries(value).filter(([key]) => key !== from)))}><Trash2 aria-hidden="true" className="h-4 w-4" /></button>
    </div>)}
    <div className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_44px]">
      <label className="min-w-0 text-sm">Метка источника<input autoComplete="off" className={cn(control, 'mt-1')} value={source} disabled={disabled} onChange={(event) => { setSource(event.target.value); setError('') }} /></label>
      <label className="min-w-0 text-sm">Значение в реестре<div className="mt-1"><CanonicalValue field={field} label={`Значение в реестре: ${name}`} value={target} disabled={disabled} onChange={(next) => { setTarget(next); setError('') }} /></div></label>
      <button type="button" className={cn(secondary, 'h-11 w-11 self-end p-0')} disabled={disabled} aria-label={`Добавить перевод: ${name}`} title="Добавить перевод" onClick={() => {
        if (!source.trim() || !target.trim()) { setError('Заполните оба значения перевода.'); return }
        if (Object.prototype.hasOwnProperty.call(value, source.trim())) { setError('Эта метка уже добавлена. Измените её значение выше.'); return }
        onChange({ ...value, [source.trim()]: target.trim() }); setSource(''); setTarget(''); setError('')
      }}><Plus aria-hidden="true" className="h-4 w-4" /></button>
    </div>
    {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">{error}</p>}
  </div>
}

function DatasetEditor({ dataset, sheets, index, onChange, onRemove, disabled }: {
  dataset: TransferDataset; sheets: LegacySheet[]; index: number; onChange: (value: TransferDataset) => void; onRemove: () => void; disabled: boolean
}) {
  const id = useId()
  const sheet = sheets.find((item) => item.id === dataset.sheet_id)
  const required: string[] = LEGACY_REQUIRED[dataset.kind].filter((field) => !(field === 'atom_key' && dataset.atom_key_mode === 'content'))
  const fieldEditor = (field: string) => <div key={field} className="min-w-0 space-y-2 border-b border-border py-3">
    <div className="grid min-w-0 items-start gap-2 sm:grid-cols-2">
      <div className="min-w-0"><label htmlFor={`${id}-${field}`} className="mb-1 block text-sm font-medium">{fields[field]}{required.includes(field) ? ' *' : ''}</label>
        <select id={`${id}-${field}`} name={field} className={control} value={dataset.fields[field] ?? ''} disabled={disabled || (field === 'atom_key' && dataset.atom_key_mode === 'content')} onChange={(event) => onChange({ ...dataset, fields: { ...dataset.fields, [field]: event.target.value } })}>
          <option value="">Не сопоставлено</option>
          {(sheet?.columns ?? []).map((column) => <option key={column.column} value={column.column}>{column.column}{dataset.header_row === sheet?.header_row && column.label ? ` · ${column.label}` : ''}</option>)}
        </select>
      </div>
      <label className="min-w-0 text-sm">По умолчанию: {fields[field]}
        <div className="mt-1"><CanonicalValue field={field} label={`По умолчанию: ${fields[field]}`} value={dataset.defaults?.[field] ?? ''} disabled={disabled || (field === 'atom_key' && dataset.atom_key_mode === 'content')} onChange={(value) => onChange({ ...dataset, defaults: { ...dataset.defaults, [field]: value } })} /></div>
      </label>
    </div>
    <details className="min-w-0"><summary className="min-h-11 cursor-pointer py-3 text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">Переводы меток: {fields[field]} ({Object.keys(dataset.value_maps?.[field] ?? {}).length})</summary>
      <Translations field={field} name={fields[field]} value={dataset.value_maps?.[field] ?? {}} disabled={disabled} onChange={(value) => onChange({ ...dataset, value_maps: { ...dataset.value_maps, [field]: value } })} />
    </details>
  </div>
  return <fieldset className="min-w-0 border-t border-border pt-4" disabled={disabled}>
    <legend className="max-w-full px-0 pt-3 text-sm font-semibold [overflow-wrap:anywhere]">Набор {index + 1}: {LEGACY_KINDS[dataset.kind]}</legend>
    <div className="grid min-w-0 items-end gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.6fr)_44px]">
      <label className="min-w-0 text-sm">Лист набора {index + 1}<select className={cn(control, 'mt-1')} value={dataset.sheet_id} onChange={(event) => {
        const next = sheets.find((item) => item.id === event.target.value)
        if (next && window.confirm('Сменить лист и сбросить сопоставленные столбцы этого набора?')) onChange({ ...dataset, sheet_id: next.id, header_row: next.header_row, fields: {} })
      }}>{sheets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label className="min-w-0 text-sm">Тип набора {index + 1}<select className={cn(control, 'mt-1')} value={dataset.kind} onChange={(event) => onChange({ ...dataset, kind: event.target.value as LegacyKind })}>{Object.entries(LEGACY_KINDS).map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}</select></label>
      <label className="min-w-0 text-sm">Заголовки набора {index + 1}<input className={cn(control, 'mt-1')} type="number" inputMode="numeric" min={1} max={1048576} step={1} value={dataset.header_row || ''} onChange={(event) => onChange({ ...dataset, header_row: Number(event.target.value) })} /></label>
      <button type="button" className={cn(secondary, 'h-11 w-11 p-0')} aria-label={`Удалить набор ${index + 1}`} title="Удалить набор" onClick={() => { if (window.confirm(`Удалить набор ${index + 1} из настройки переноса?`)) onRemove() }}><Trash2 aria-hidden="true" className="h-4 w-4" /></button>
    </div>
    <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
      <label className="min-w-0 text-sm">Первая строка набора {index + 1}<input autoComplete="off" className={cn(control, 'mt-1')} type="number" inputMode="numeric" min={1} max={1048576} step={1} value={dataset.row_from ?? ''} onChange={(event) => onChange({ ...dataset, row_from: event.target.value ? Number(event.target.value) : undefined })} /></label>
      <label className="min-w-0 text-sm">Последняя строка набора {index + 1}<input autoComplete="off" className={cn(control, 'mt-1')} type="number" inputMode="numeric" min={1} max={1048576} step={1} value={dataset.row_to ?? ''} onChange={(event) => onChange({ ...dataset, row_to: event.target.value ? Number(event.target.value) : undefined })} /></label>
    </div>
    {dataset.kind === 'atoms' && <label className="mt-3 block min-w-0 text-sm">Код атома
      <select className={cn(control, 'mt-1')} value={dataset.atom_key_mode ?? 'column'} onChange={(event) => onChange({ ...dataset, atom_key_mode: event.target.value as 'column' | 'content' })}>
        <option value="column">Из столбца источника</option><option value="content">Хеш содержимого атома</option>
      </select>
    </label>}
    <div className="min-w-0">{required.map(fieldEditor)}</div>
    <details className="min-w-0"><summary className="min-h-11 cursor-pointer py-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">Дополнительные поля набора {index + 1}</summary>
      {Object.keys(fields).filter((field) => !required.includes(field)).map(fieldEditor)}
    </details>
  </fieldset>
}

export function TransferDatasets({ datasets, sheets, onChange, disabled }: {
  datasets: TransferDataset[]; sheets: LegacySheet[]; onChange: (value: TransferDataset[]) => void; disabled: boolean
}) {
  const ids = useRef<string[]>([])
  while (ids.current.length < datasets.length) ids.current.push(crypto.randomUUID())
  return <section aria-label="Наборы переноса" className="min-w-0 space-y-4">
    {datasets.map((dataset, index) => <DatasetEditor key={ids.current[index]} dataset={dataset} index={index} sheets={sheets} disabled={disabled}
      onChange={(value) => onChange(datasets.map((item, current) => current === index ? value : item))}
      onRemove={() => { ids.current.splice(index, 1); onChange(datasets.filter((_, current) => current !== index)) }} />)}
    {!datasets.length && <p className="text-sm text-muted-foreground">Наборы не выбраны.</p>}
    <button type="button" className={secondary} disabled={disabled || !sheets.length} onClick={() => {
      const sheet = sheets[0]
      if (sheet) onChange([...datasets, { sheet_id: sheet.id, header_row: sheet.header_row, kind: sheet.suggested_mapping.kind, fields: { ...sheet.suggested_mapping.fields }, atom_key_mode: 'column' }])
    }}><Plus aria-hidden="true" className="h-4 w-4" />Добавить набор</button>
  </section>
}

interface Choice { id: string; label: string; quality?: number }
const reportFields: Record<string, string> = { ...fields, source_case_mask: 'Договор источника', source_title: 'Название в источнике', source_digital_product: 'Продукт источника' }
function sourceCaseLabel(changes: Record<string, unknown>) {
  return [...new Set([changes.source_case_mask, changes.source_digital_product, changes.source_title].filter((value): value is string => typeof value === 'string' && Boolean(value)))].join(' · ')
}

export function TransferResolutions({ config, cases, users, caseSources, actorSources, disabled, onChange }: {
  config: TransferConfig; cases: Choice[]; users: Choice[]; caseSources: Choice[]; actorSources: Choice[]; disabled: boolean; onChange: (value: TransferConfig) => void
}) {
  const [caseSource, setCaseSource] = useState('')
  const [actorSource, setActorSource] = useState('')
  const [error, setError] = useState('')
  const pending = useContext(PendingTranslations)
  const id = useId()
  useEffect(() => { pending(id, Boolean(caseSource || actorSource)) }, [id, pending, caseSource, actorSource])
  useEffect(() => () => pending(id, false), [id, pending])
  const updateCase = (source: string, decision: TransferCaseDecision) => onChange({ ...config, cases: { ...config.cases, [source]: decision } })
  const updateActor = (source: string, decision: TransferActorDecision) => onChange({ ...config, actors: { ...config.actors, [source]: decision } })
  const add = (kind: 'case' | 'actor') => {
    const source = (kind === 'case' ? caseSource : actorSource).trim()
    if (!source) { setError('Укажите идентификатор из источника.'); return }
    if (Object.prototype.hasOwnProperty.call(kind === 'case' ? config.cases : config.actors, source)) { setError('Для этого идентификатора решение уже задано.'); return }
    if (kind === 'case') { updateCase(source, { mode: 'existing' }); setCaseSource('') }
    else { updateActor(source, { mode: 'user' }); setActorSource('') }
    setError('')
  }
  return <section className="min-w-0 space-y-4 border-t border-border pt-4" aria-label="Разрешение договоров и сотрудников">
    <h3 className="text-base font-semibold">Договоры и сотрудники</h3>
    <fieldset className="min-w-0 space-y-3" disabled={disabled}><legend className="mb-2 text-sm font-semibold">Договоры</legend>
      {caseSources.filter((item) => !config.cases[item.id]).map((item, index) => <label key={item.id} className="block min-w-0 text-sm [overflow-wrap:anywhere]">{item.label}<select aria-label={`Решение исходного договора ${index + 1}`} className={cn(control, 'mt-1')} value="" onChange={(event) => { if (event.target.value) updateCase(item.id, { mode: event.target.value as 'existing' | 'create' }) }}><option value="">Не сопоставлен</option><option value="existing">Связать с существующим договором</option><option value="create">Создать договор</option></select></label>)}
      {Object.entries(config.cases).map(([source, decision], index) => <div key={source} className="min-w-0 space-y-3 border-b border-border pb-3">
        <div className="flex min-w-0 items-center justify-between gap-2"><span className="text-sm [overflow-wrap:anywhere]">{caseSources.find((item) => item.id === source)?.label ?? `Договор источника ${index + 1}`}</span><button type="button" className={cn(secondary, 'h-11 w-11 shrink-0 p-0')} aria-label={`Удалить решение договора ${index + 1}`} title="Удалить решение" onClick={() => onChange({ ...config, cases: Object.fromEntries(Object.entries(config.cases).filter(([key]) => key !== source)) })}><Trash2 aria-hidden="true" className="h-4 w-4" /></button></div>
        <label className="block text-sm">Решение договора {index + 1}<select className={cn(control, 'mt-1')} value={decision.mode} onChange={(event) => updateCase(source, { mode: event.target.value as 'existing' | 'create' })}><option value="existing">Связать с существующим договором</option><option value="create">Создать договор</option></select></label>
        {decision.mode === 'existing' && <label className="block text-sm">Договор реестра {index + 1}<select className={cn(control, 'mt-1')} value={decision.target_case_id ?? ''} onChange={(event) => updateCase(source, { ...decision, target_case_id: event.target.value || null })}><option value="">Выберите договор</option>{cases.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>}
        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
          <label className="min-w-0 text-sm">Название договора {index + 1}<input className={cn(control, 'mt-1')} autoComplete="off" maxLength={255} value={decision.title ?? ''} onChange={(event) => updateCase(source, { ...decision, title: event.target.value || null })} /></label>
          <label className="min-w-0 text-sm">Продукт договора {index + 1}<input className={cn(control, 'mt-1')} autoComplete="off" maxLength={255} value={decision.digital_product ?? ''} onChange={(event) => updateCase(source, { ...decision, digital_product: event.target.value || null })} /></label>
          <label className="min-w-0 text-sm">Дата договора {index + 1}<input type="date" className={cn(control, 'mt-1')} value={decision.contract_date ?? ''} onChange={(event) => updateCase(source, { ...decision, contract_date: event.target.value || null })} /></label>
        </div>
        {decision.mode === 'existing' && <fieldset><legend className="text-sm text-muted-foreground">Заполнить только пустые поля</legend><div className="flex flex-wrap gap-x-4">
          {(['title', 'digital_product', 'contract_date'] as const).map((field) => <label key={field} className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="h-5 w-5 accent-primary" checked={decision.fill_empty?.includes(field) ?? false} onChange={(event) => updateCase(source, { ...decision, fill_empty: event.target.checked ? [...decision.fill_empty ?? [], field] : decision.fill_empty?.filter((item) => item !== field) })} />{field === 'title' ? 'Название договора' : fields[field]}</label>)}
        </div></fieldset>}
      </div>)}
      <div className="flex min-w-0 items-end gap-2"><label className="min-w-0 flex-1 text-sm">Договор из отчёта<select className={cn(control, 'mt-1')} value={caseSource} onChange={(event) => setCaseSource(event.target.value)}><option value="">Выберите строку источника</option>{caseSources.filter((item) => !config.cases[item.id]).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label><button type="button" className={cn(secondary, 'h-11 w-11 shrink-0 p-0')} title="Добавить решение договора" aria-label="Добавить решение договора" onClick={() => add('case')}><Plus aria-hidden="true" className="h-4 w-4" /></button></div>
    </fieldset>
    <fieldset className="min-w-0 space-y-3 border-t border-border pt-3" disabled={disabled}><legend className="text-sm font-semibold">Сотрудники</legend>
      {actorSources.filter((item) => !config.actors[item.id]).map((item, index) => <label key={item.id} className="block min-w-0 text-sm [overflow-wrap:anywhere]">{item.label}<select aria-label={`Решение исходного сотрудника ${index + 1}`} className={cn(control, 'mt-1')} value="" onChange={(event) => { if (event.target.value) updateActor(item.id, event.target.value === 'historical' ? { mode: 'historical', historical_name: item.label } : { mode: 'user' }) }}><option value="">Не сопоставлен</option><option value="user">Связать с сотрудником</option><option value="historical">Исторический участник</option></select></label>)}
      {Object.entries(config.actors).map(([source, decision], index) => <div key={source} className="min-w-0 space-y-3 border-b border-border pb-3">
        <div className="flex min-w-0 items-center justify-between gap-2"><span className="text-sm [overflow-wrap:anywhere]">Участник источника: {source}</span><button type="button" className={cn(secondary, 'h-11 w-11 shrink-0 p-0')} aria-label={`Удалить решение сотрудника ${index + 1}`} title="Удалить решение" onClick={() => onChange({ ...config, actors: Object.fromEntries(Object.entries(config.actors).filter(([key]) => key !== source)) })}><Trash2 aria-hidden="true" className="h-4 w-4" /></button></div>
        <label className="block text-sm">Решение сотрудника {index + 1}<select className={cn(control, 'mt-1')} value={decision.mode} onChange={(event) => updateActor(source, { mode: event.target.value as 'user' | 'historical' })}><option value="user">Связать с сотрудником</option><option value="historical">Исторический участник</option></select></label>
        {decision.mode === 'user' ? <label className="block text-sm">Сотрудник реестра {index + 1}<select className={cn(control, 'mt-1')} value={decision.user_id ?? ''} onChange={(event) => updateActor(source, { ...decision, user_id: event.target.value || null })}><option value="">Выберите сотрудника</option>{users.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          : <label className="block text-sm">Историческое имя {index + 1}<input autoComplete="off" maxLength={255} className={cn(control, 'mt-1')} value={decision.historical_name ?? ''} onChange={(event) => updateActor(source, { ...decision, historical_name: event.target.value || null })} /></label>}
      </div>)}
      <div className="flex min-w-0 items-end gap-2"><label className="min-w-0 flex-1 text-sm">Email или имя из источника<input autoComplete="off" className={cn(control, 'mt-1')} value={actorSource} onChange={(event) => setActorSource(event.target.value)} /></label><button type="button" className={cn(secondary, 'h-11 w-11 shrink-0 p-0')} title="Добавить решение сотрудника" aria-label="Добавить решение сотрудника" onClick={() => add('actor')}><Plus aria-hidden="true" className="h-4 w-4" /></button></div>
      <label className="flex min-h-11 cursor-pointer items-start gap-3 py-2 text-sm"><input type="checkbox" className="mt-0.5 h-5 w-5 shrink-0 accent-primary" checked={config.apply_current_assignments} onChange={(event) => onChange({ ...config, apply_current_assignments: event.target.checked })} />Применить текущие назначения к рабочему реестру</label>
    </fieldset>
    {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">{error}</p>}
  </section>
}

const outcomeLabels: Record<string, string> = { total: 'Всего строк', create: 'Создать', reuse: 'Без изменений', fill_empty: 'Заполнить пустые поля', duplicate: 'Дубликат', skip: 'Пропустить', blocked: 'Заблокировано', errors: 'Ошибки', warnings: 'Предупреждения', error_rows: 'Строки с ошибками', warning_rows: 'Строки с предупреждениями' }
const fillFields: NonNullable<TransferRowDecision['fill_empty']> = ['title', 'digital_product', 'work_type', 'object_type', 'source_clause', 'source_evidence_text', 'notes', 'alpha_comment', 'system_url', 'alpha_result', 'alpha_date', 'commission_result', 'commission_date']

export function TransferReport({ preview, page, offset, previousOffset, onPage, loading, disabled, decisions, onChange, sheets, onResolve, completed }: {
  preview: TransferPreview; page: TransferPreviewPage; offset: number; previousOffset: number | null; onPage: (offset: number) => void
  loading: boolean; disabled: boolean; decisions: Record<string, TransferRowDecision>; onChange: (value: Record<string, TransferRowDecision>) => void; sheets: LegacySheet[]
  onResolve: (kind: 'case' | 'actor', source: string) => void; completed: boolean
}) {
  const change = (key: string, decision: TransferRowDecision) => onChange({ ...decisions, [key]: decision })
  const pagination = <div className="flex flex-wrap items-center justify-between gap-3">
    <p role="status" className="text-sm tabular-nums">{loading ? 'Загрузка строк...' : page.total_rows ? `Строки ${offset + 1}–${offset + page.rows.length} из ${page.total_rows}` : 'Строк нет'}</p>
    <div className="flex gap-2"><button type="button" className={cn(secondary, 'h-11 w-11 p-0')} disabled={loading || previousOffset === null} aria-label="Предыдущие строки" title="Предыдущие строки" onClick={() => previousOffset !== null && onPage(previousOffset)}><ChevronLeft aria-hidden="true" className="h-4 w-4" /></button><button type="button" className={cn(secondary, 'h-11 w-11 p-0')} disabled={loading || page.next_offset === null} aria-label="Следующие строки" title="Следующие строки" onClick={() => page.next_offset !== null && onPage(page.next_offset)}><ChevronRight aria-hidden="true" className="h-4 w-4" /></button></div>
  </div>
  return <section aria-label="Отчёт переноса" className="min-w-0 space-y-4 border-t border-border pt-4" aria-busy={loading}>
    <h3 className="text-base font-semibold">Результат проверки переноса</h3>
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">{Object.entries(preview.counts).map(([key, count]) => <div key={key}><dt className="text-sm text-muted-foreground [overflow-wrap:anywhere]">{outcomeLabels[key] ?? key}</dt><dd className="text-lg font-semibold tabular-nums">{count.toLocaleString('ru-RU')}</dd></div>)}</dl>
    {!completed && <p className="text-sm font-medium">{preview.ready ? 'Проверка пройдена. Перенос не выполнен.' : 'Перенос заблокирован. Есть нерешённые ошибки.'}</p>}
    {preview.issues.length > 0 && <details className="min-w-0" open><summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">Замечания проверки: {preview.issues.length}</summary><ul className="max-h-72 divide-y divide-border overflow-y-auto" aria-label="Общие замечания переноса" tabIndex={0}>{preview.issues.map((issue, index) => <li key={index} className="py-2 text-sm [overflow-wrap:anywhere]"><span className={issue.severity === 'error' ? 'font-medium text-rose-700 dark:text-rose-300' : 'font-medium text-amber-700 dark:text-amber-300'}>{issue.severity === 'error' ? 'Ошибка' : 'Предупреждение'}</span>{issue.row != null ? ` · Строка ${issue.row}` : ''}: {issue.message} <span className="text-xs text-muted-foreground">{issue.code}</span></li>)}</ul></details>}
    {pagination}
    <ol className="min-w-0 divide-y divide-border" aria-label="Все строки переноса" start={offset + 1}>
      {page.rows.map((row, occurrence) => {
        const decision = decisions[row.row_key]
        return <li key={`${row.row_key}:${row.sheet_id}:${row.row}:${occurrence}`} className="min-w-0 py-3 [contain-intrinsic-size:auto_100px] [content-visibility:auto]">
          <details className="min-w-0"><summary className="min-h-11 cursor-pointer py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"><span className="font-medium [overflow-wrap:anywhere]">{LEGACY_KINDS[row.kind]}{row.sheet_id !== 'config' ? ` · ${sheets.find((sheet) => sheet.id === row.sheet_id)?.name ?? row.sheet_id} · Строка ${row.row ?? '—'}` : ''}{sourceCaseLabel(row.changes) ? ` · ${sourceCaseLabel(row.changes)}` : ''}</span><span className={cn('ml-2', row.outcome === 'blocked' ? 'font-medium text-rose-700 dark:text-rose-300' : 'text-muted-foreground')}>{outcomeLabels[row.outcome]}{row.issues.length > 0 ? ` · Замечаний: ${row.issues.length}` : ''}</span></summary>
            {row.issues.length > 0 && <ul className="space-y-2 py-2">{row.issues.map((issue, index) => <li key={index} className="text-sm [overflow-wrap:anywhere]"><span className="font-medium">{issue.severity === 'error' ? 'Ошибка' : 'Предупреждение'}:</span> {issue.message}</li>)}</ul>}
            <dl className="min-w-0 space-y-2 py-3 text-sm">{Object.entries(row.changes).filter(([key]) => Boolean(reportFields[key])).map(([key, value]) => <div key={key} className="grid min-w-0 gap-1 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]"><dt className="text-muted-foreground [overflow-wrap:anywhere]">{reportFields[key]}</dt><dd className="[overflow-wrap:anywhere]">{key === 'case_key' || key === 'contract_reference' ? 'Скрыто' : value === null ? '—' : typeof value === 'object' ? 'Изменение объекта' : String(value)}</dd></div>)}</dl>
            {!completed && <div className="mb-3 flex flex-wrap gap-2">{typeof row.changes.case_mapping_key === 'string' && <button type="button" className={secondary} disabled={disabled} onClick={() => onResolve('case', String(row.changes.case_mapping_key))}><Link2 aria-hidden="true" className="h-4 w-4" />Сопоставить договор</button>}{typeof row.changes.actor_mapping_key === 'string' && <button type="button" className={secondary} disabled={disabled} onClick={() => onResolve('actor', String(row.changes.actor_mapping_key))}><Link2 aria-hidden="true" className="h-4 w-4" />Сопоставить сотрудника</button>}</div>}
            {row.kind !== 'cases' && !completed && <>
            <fieldset disabled={disabled} className="min-w-0 space-y-3 pb-3"><legend className="sr-only">Решение строки {row.row}</legend>
              <label className="block text-sm">Решение строки {row.row}<select className={cn(control, 'mt-1')} value={decision?.action ?? ''} onChange={(event) => {
                const action = event.target.value as TransferRowDecision['action'] | ''
                if (!action) { onChange(Object.fromEntries(Object.entries(decisions).filter(([key]) => key !== row.row_key))); return }
                change(row.row_key, { action, ...(action === 'reuse' || action === 'fill_empty' ? { target_id: row.target_id ?? null } : {}) })
              }}><option value="">По результату проверки</option>{(['create', 'reuse', 'fill_empty', 'skip'] as const).filter((action) => action === 'create' || action === 'skip' || (Boolean(row.target_id || decision?.target_id) && (row.kind === 'atoms' || (row.kind === 'assignments' && action === 'reuse')))).map((action) => <option key={action} value={action}>{outcomeLabels[action]}</option>)}</select></label>
              {(decision?.action === 'reuse' || decision?.action === 'fill_empty') && <p className="break-all text-xs text-muted-foreground">Предложенная запись реестра: {decision.target_id}</p>}
              {decision?.action === 'fill_empty' && <fieldset><legend className="text-sm text-muted-foreground">Заполнить только пустые поля</legend><div className="grid min-w-0 gap-x-3 sm:grid-cols-2">{fillFields.map((field) => <label key={field} className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="h-5 w-5 shrink-0 accent-primary" checked={decision.fill_empty?.includes(field) ?? false} onChange={(event) => change(row.row_key, { ...decision, fill_empty: event.target.checked ? [...decision.fill_empty ?? [], field] : decision.fill_empty?.filter((item) => item !== field) })} />{fields[field]}</label>)}</div></fieldset>}
            </fieldset>
            </>}
          </details>
        </li>
      })}
    </ol>
  </section>
}

export function TransferConfirmation({ kind, revision, digest, summary, working, blocked, failure, onClose, onSubmit }: {
  kind: 'commit' | 'rollback'; revision: number; digest: string; summary: string; working: boolean
  blocked: boolean; failure: string
  onClose: () => void; onSubmit: (reason: string) => void
}) {
  const panel = useProtectedModal<HTMLDivElement>()
  const [confirmed, setConfirmed] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const id = useId()
  const label = kind === 'commit' ? 'Подтвердить перенос' : 'Подтвердить откат'
  return <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]" onPointerDown={preventBackdropDismiss}>
    <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-summary`} tabIndex={-1} className="max-h-[calc(100dvh-2rem)] w-full max-w-xl space-y-4 overflow-y-auto overscroll-contain rounded-lg border border-border bg-surface p-4 text-foreground shadow-lg sm:p-6">
      <div className="flex items-start justify-between gap-3"><h3 id={`${id}-title`} className="pt-2 text-base font-semibold">{kind === 'commit' ? 'Перенос в рабочий реестр' : 'Откат переноса'}</h3>
        <button type="button" className={cn(secondary, 'h-11 w-11 shrink-0 p-0')} aria-label="Закрыть подтверждение" title="Закрыть подтверждение" disabled={working} onClick={() => { if ((!reason && !confirmed) || window.confirm('Закрыть подтверждение и сбросить введённые данные?')) onClose() }}><X aria-hidden="true" className="h-4 w-4" /></button>
      </div>
      <p id={`${id}-summary`} className="text-sm [overflow-wrap:anywhere]">{summary}</p>
      <p className="text-sm tabular-nums">Ревизия: {revision}</p><details className="min-w-0 border-y border-border"><summary className="min-h-11 cursor-pointer py-3 text-sm text-muted-foreground">Идентификатор проверки</summary><p className="break-all pb-3 font-mono text-xs">{digest}</p></details>
      <form className="space-y-4" onSubmit={(event) => {
        event.preventDefault()
        if (working) return
        if (!confirmed || (kind === 'rollback' && reason.trim().length < 3)) { setError(kind === 'rollback' ? 'Укажите причину (от 3 символов) и подтвердите откат.' : 'Подтвердите перенос данных.'); return }
        onSubmit(reason.trim())
      }}>
        {kind === 'rollback' && <label className="block text-sm font-medium">Причина отката<textarea autoComplete="off" rows={3} maxLength={1000} className={cn(control, 'mt-1 h-auto min-h-24 py-2')} disabled={working} value={reason} onChange={(event) => { setReason(event.target.value); setError('') }} /></label>}
        <label className="flex min-h-11 cursor-pointer items-start gap-3 py-2 text-sm"><input type="checkbox" className="mt-0.5 h-5 w-5 shrink-0 accent-primary" disabled={working} checked={confirmed} onChange={(event) => { setConfirmed(event.target.checked); setError('') }} />{kind === 'commit' ? 'Подтверждаю запись проверенных данных в рабочий реестр.' : 'Подтверждаю отмену записей этого переноса.'}</label>
        {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">{error}</p>}
        {failure && <p role="alert" className="text-sm text-rose-700 [overflow-wrap:anywhere] dark:text-rose-300">{failure}</p>}
        <button type="submit" className={cn(button, kind === 'commit' ? 'bg-primary text-primary-foreground hover:opacity-90' : 'border border-border bg-surface text-rose-700 hover:bg-muted dark:text-rose-300')} disabled={working || blocked}>
          {working ? <Loader2 aria-hidden="true" className="h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" /> : kind === 'commit' ? <CheckCircle2 aria-hidden="true" className="h-4 w-4 shrink-0" /> : <RotateCcw aria-hidden="true" className="h-4 w-4 shrink-0" />}{label}
        </button>
      </form>
    </div>
  </div>
}

function cleanConfig(config: TransferConfig): TransferConfig {
  return { ...config, datasets: config.datasets.map((dataset) => ({
    ...dataset,
    fields: Object.fromEntries(Object.entries(dataset.fields).filter(([, value]) => value)),
    defaults: Object.fromEntries(Object.entries(dataset.defaults ?? {}).filter(([, value]) => value !== '')),
    value_maps: Object.fromEntries(Object.entries(dataset.value_maps ?? {}).filter(([, value]) => Object.keys(value).length > 0)),
    atom_key_mode: dataset.atom_key_mode ?? 'column',
  })) }
}
const configSignature = (config: TransferConfig) => JSON.stringify(cleanConfig(config))
function initialConfig(batch: LegacyBatch): TransferConfig {
  const first = batch.inspection.sheets[0]
  return { namespace: 'AuditA1.9', datasets: batch.mapping ? [{ ...batch.mapping }] : first ? [{ sheet_id: first.id, header_row: first.header_row, kind: first.suggested_mapping.kind, fields: { ...first.suggested_mapping.fields }, atom_key_mode: 'column' }] : [], cases: {}, actors: {}, row_decisions: {}, apply_current_assignments: false }
}
function errorMessage(cause: unknown) { return cause instanceof Error ? cause.message : 'Не удалось выполнить запрос.' }
const statuses = { draft: 'Черновик', previewed: 'Проверен', committed: 'Перенесён', rolled_back: 'Отменён' }

export function AuditLegacyTransfer({ batch, selectedId, onSelect, busy, onBusy, onDirty }: {
  batch: LegacyBatch; selectedId: string; onSelect: (id: string, internal?: boolean) => void
  busy: MutableRefObject<boolean>; onBusy: (value: boolean) => void; onDirty: (value: boolean) => void
}) {
  const [options, setOptions] = useState<TransferOptions | null>(null)
  const [transfers, setTransfers] = useState<LegacyTransfer[]>([])
  const [transfer, setTransfer] = useState<LegacyTransfer | null>(null)
  const [config, setConfig] = useState(() => initialConfig(batch))
  const [baseline, setBaseline] = useState(() => configSignature(initialConfig(batch)))
  const [pending, setPending] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [action, setAction] = useState('')
  const [reload, setReload] = useState(0)
  const [stale, setStale] = useState(false)
  const [needsPreview, setNeedsPreview] = useState(false)
  const [confirmation, setConfirmation] = useState<{ kind: 'commit' | 'rollback'; revision: number; hash: string } | null>(null)
  const [page, setPage] = useState<TransferPreviewPage | null>(null)
  const [offsets, setOffsets] = useState([0])
  const [pageLoading, setPageLoading] = useState(false)
  const [pageError, setPageError] = useState('')
  const [sources, setSources] = useState<{ cases: Choice[]; actors: Choice[] }>({ cases: [], actors: [] })
  const mounted = useRef(true)
  const paging = useRef<AbortController | null>(null)
  const resolutionRef = useRef<HTMLDivElement>(null)
  const formRef = useRef<HTMLFormElement>(null)
  const marker = `audit-legacy-transfer-pending:${batch.id}`
  const dirty = configSignature(config) !== baseline || pending.size > 0
  const completed = transfer?.status === 'committed' || transfer?.status === 'rolled_back'
  const locked = loading || Boolean(action) || Boolean(loadError) || stale
  const editable = !locked && !completed
  const reportPending = useCallback((id: string, value: boolean) => setPending((current) => {
    if (current.has(id) === value) return current
    const next = new Set(current)
    if (value) next.add(id); else next.delete(id)
    return next
  }), [])

  const rememberSources = useCallback((rows: TransferPreviewPage['rows'], replace = false) => {
    setSources((current) => {
      const cases = new Map((replace ? [] : current.cases).map((item) => [item.id, item]))
      const actors = new Map((replace ? [] : current.actors).map((item) => [item.id, item]))
      for (const row of rows) {
        const caseId = row.changes.case_mapping_key
        const actorId = row.changes.actor_mapping_key
        const sheet = batch.inspection.sheets.find((item) => item.id === row.sheet_id)?.name ?? row.sheet_id
        if (typeof caseId === 'string') {
          const sourceLabel = sourceCaseLabel(row.changes)
          const location = row.sheet_id === 'config' ? '' : `${sheet} · Строка ${row.row ?? '—'}`
          const label = [sourceLabel, location].filter(Boolean).join(' · ')
          const quality = Number(Boolean(row.changes.source_case_mask)) + 4 * Number(Boolean(row.changes.source_digital_product)) + 2 * Number(Boolean(row.changes.source_title)) + Number(Boolean(location))
          if (label && (!cases.has(caseId) || quality > (cases.get(caseId)?.quality ?? 0))) cases.set(caseId, { id: caseId, label, quality })
        }
        if (typeof actorId === 'string' && actorId) actors.set(actorId, { id: actorId, label: actorId })
      }
      return { cases: [...cases.values()], actors: [...actors.values()] }
    })
  }, [batch.inspection.sheets])

  const adopt = useCallback((result: LegacyTransfer) => {
    setTransfer(result); setConfig(result.config); setBaseline(configSignature(result.config)); setPage(result.preview); setOffsets([0]); setPageError('')
    rememberSources(result.preview?.rows ?? [], true)
  }, [rememberSources])
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; paging.current?.abort() } }, [])
  useEffect(() => { onDirty(dirty || Boolean(confirmation)) }, [dirty, confirmation, onDirty])
  useEffect(() => () => onDirty(false), [onDirty])

  useEffect(() => {
    const controller = new AbortController()
    paging.current?.abort(); setPageLoading(false); setLoading(true); setLoadError(''); setError('')
    let uncertain = false
    try { uncertain = sessionStorage.getItem(marker) !== null } catch { /* Recovery still works in-memory when storage is unavailable. */ }
    void (async () => {
      try {
        const [nextOptions, list, result] = await Promise.all([
          auditLegacyTransfer.options(batch.id, controller.signal), auditLegacyTransfer.list(batch.id, controller.signal),
          selectedId !== 'new' ? auditLegacyTransfer.get(selectedId, controller.signal) : Promise.resolve(null),
        ])
        if (controller.signal.aborted) return
        if (result && result.source_id !== batch.id) throw new Error('Перенос относится к другому исходному файлу.')
        setOptions(nextOptions); setTransfers(list); setConfirmation(null); setStale(false)
        if (result) adopt(result)
        else { const next = initialConfig(batch); setTransfer(null); setConfig(next); setBaseline(configSignature(next)); setPage(null); setSources({ cases: [], actors: [] }) }
        setNeedsPreview(uncertain && result?.status !== 'committed' && result?.status !== 'rolled_back')
        if (uncertain) setNotice('Серверный статус загружен. Перед новой записью требуется повторная проверка.')
        if (result?.status === 'committed' || result?.status === 'rolled_back') { try { sessionStorage.removeItem(marker) } catch { /* No storage dependency for durable server status. */ } }
      } catch (cause) { if (!controller.signal.aborted) setLoadError(errorMessage(cause)) }
      finally { if (!controller.signal.aborted) setLoading(false) }
    })()
    return () => controller.abort()
  }, [batch, selectedId, reload, marker, adopt])

  const refresh = () => {
    if (busy.current || (dirty && !window.confirm('Загрузить серверную настройку и сбросить несохранённые изменения переноса?'))) return
    setReload((value) => value + 1)
  }
  const validate = () => {
    let problem = ''
    if (pending.size) problem = 'Добавьте или очистите незавершённые переводы меток и решения.'
    else if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(config.namespace)) problem = 'Укажите код источника до 120 символов: латинские буквы, цифры, точка, дефис или подчёркивание.'
    else if (!config.datasets.length || config.datasets.length > 50) problem = 'Выберите от 1 до 50 наборов.'
    else if (config.datasets.some((item) => !Number.isInteger(item.header_row) || item.header_row < 1 || item.header_row > 1048576 || [item.row_from, item.row_to].some((row) => row !== undefined && (!Number.isInteger(row) || row < 1 || row > 1048576)) || (item.row_from !== undefined && item.row_to !== undefined && item.row_from > item.row_to))) problem = 'Проверьте строки заголовков и диапазоны наборов.'
    else if (Object.values(config.cases).some((item) => item.mode === 'existing' && !item.target_case_id)) problem = 'Выберите существующий договор для каждого незавершённого решения.'
    else if (Object.values(config.actors).some((item) => item.mode === 'user' ? !item.user_id : !item.historical_name?.trim())) problem = 'Выберите сотрудника или укажите историческое имя.'
    if (problem) { setError(problem); formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"], input, select')?.focus(); return false }
    return true
  }
  const mutate = async (name: string, request: () => Promise<LegacyTransfer>) => {
    if (busy.current || locked) return
    busy.current = true; onBusy(true); setAction(name); setError(''); setNotice(''); paging.current?.abort(); setPageLoading(false)
    try { sessionStorage.setItem(marker, name) } catch { /* Mutations remain single-flight without browser storage. */ }
    try {
      const result = await request()
      if (!mounted.current) return
      adopt(result); setTransfers((current) => [result, ...current.filter((item) => item.id !== result.id)]); setStale(false)
      if (name === 'preview' || result.status === 'committed' || result.status === 'rolled_back') setNeedsPreview(false)
      setConfirmation(null)
      setNotice(name === 'commit' ? 'Данные перенесены в рабочий реестр.' : name === 'rollback' ? 'Перенос отменён.' : name === 'preview' ? 'Проверка переноса завершена.' : 'Настройка переноса сохранена.')
      try { sessionStorage.removeItem(marker) } catch { /* Server response is authoritative. */ }
      if (result.id !== selectedId) onSelect(result.id, true)
    } catch (cause) {
      if (!mounted.current) return
      setError(errorMessage(cause))
      if (name === 'preview' || name === 'commit') setNeedsPreview(true)
      if (!(cause instanceof ApiError) || cause.status === 409 || cause.status >= 500) { setStale(true); setNeedsPreview(true) }
      else if (name !== 'preview' && name !== 'commit') { try { sessionStorage.removeItem(marker) } catch { /* No automatic retry. */ } }
    } finally { busy.current = false; onBusy(false); if (mounted.current) setAction('') }
  }
  const save = () => {
    if (!editable || !validate()) return
    if (!transfer && transfers.length > 0 && !window.confirm('Для файла уже есть сохранённые переносы. Создать отдельный перенос?')) return
    void mutate('save', () => transfer ? auditLegacyTransfer.config(transfer.id, transfer.revision, cleanConfig(config)) : auditLegacyTransfer.create(batch.id, cleanConfig(config)))
  }
  const loadPage = async (offset: number) => {
    if (!transfer?.preview || pageLoading || busy.current) return
    paging.current?.abort()
    const controller = new AbortController(); paging.current = controller
    setPageLoading(true); setPageError('')
    try {
      const result = await auditLegacyTransfer.rows(transfer.id, offset, controller.signal)
      if (controller.signal.aborted) return
      if (result.preview_hash !== transfer.preview.preview_hash || result.revision !== transfer.preview.revision) { setStale(true); setNeedsPreview(true); throw new Error('Отчёт изменился. Загрузите актуальный статус и повторите проверку.') }
      setPage(result); rememberSources(result.rows)
      setOffsets((current) => current.includes(offset) ? current.slice(0, current.indexOf(offset) + 1) : [...current, offset])
    } catch (cause) { if (!controller.signal.aborted) setPageError(errorMessage(cause)) }
    finally { if (!controller.signal.aborted) setPageLoading(false) }
  }
  const canCommit = Boolean(transfer?.status === 'previewed' && transfer.preview?.ready && transfer.preview.revision === transfer.revision && !dirty && !needsPreview && !locked)
  return <section aria-label="Перенос в рабочий реестр" className="min-w-0 space-y-4 border-t border-border pt-4">
    <div className="flex items-start justify-between gap-3"><h2 className="pt-2 text-base font-semibold">Перенос в рабочий реестр</h2><button type="button" className={cn(secondary, 'h-11 w-11 shrink-0 p-0')} disabled={Boolean(action) || loading} aria-label="Обновить статус переноса" title="Обновить статус переноса" onClick={refresh}><RefreshCcw aria-hidden="true" className="h-4 w-4" /></button></div>
    <label className="block text-sm">Сохранённые переносы<select className={cn(control, 'mt-1')} value={selectedId} disabled={Boolean(action)} onChange={(event) => onSelect(event.target.value)}><option value="new">Новый перенос</option>{selectedId !== 'new' && !transfers.some((item) => item.id === selectedId) && <option value={selectedId}>Выбранный перенос</option>}{transfers.map((item) => <option key={item.id} value={item.id}>{item.namespace} · {statuses[item.status]} · {new Date(item.created_at).toLocaleString('ru-RU')}</option>)}</select></label>
    {loading && <p role="status" className="flex items-center gap-2 text-sm"><Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" />Загрузка переноса...</p>}
    {loadError && <div role="alert" className="space-y-2 text-sm"><p className="text-rose-700 [overflow-wrap:anywhere] dark:text-rose-300">{loadError}</p><button type="button" className={secondary} onClick={refresh}><RefreshCcw aria-hidden="true" className="h-4 w-4" />Повторить загрузку переноса</button></div>}
    {error && !confirmation && <p role="alert" className="text-sm text-rose-700 [overflow-wrap:anywhere] dark:text-rose-300">{error}</p>}
    {stale && <div role="alert" className="space-y-2 border-l-2 border-amber-500 pl-3 text-sm"><p>Результат запроса требует сверки с сервером. Повторная запись заблокирована.</p><button type="button" className={secondary} disabled={Boolean(action)} onClick={refresh}><RefreshCcw aria-hidden="true" className="h-4 w-4" />Загрузить актуальный статус</button></div>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    {!loading && !loadError && options && <>
      {transfer && <p className="text-sm font-medium tabular-nums">Статус: {statuses[transfer.status]} · Ревизия {transfer.revision}{transfer.committed_at ? ` · Перенесён ${new Date(transfer.committed_at).toLocaleString('ru-RU')}` : ''}</p>}
      {transfer?.status === 'committed' && <button type="button" className={cn(secondary, 'text-rose-700 dark:text-rose-300')} disabled={locked} onClick={() => setConfirmation({ kind: 'rollback', revision: transfer.revision, hash: transfer.preview?.preview_hash ?? '' })}><RotateCcw aria-hidden="true" className="h-4 w-4" />Отменить перенос</button>}
      <PendingTranslations.Provider value={reportPending}><CanonicalLabels.Provider value={options.canonical_labels}>
        <form ref={formRef} noValidate className="min-w-0 space-y-4" aria-label="Настройка переноса" onSubmit={(event) => { event.preventDefault(); save() }}>
          <fieldset disabled={!editable} className="min-w-0"><label className="block text-sm">Код источника<input name="namespace" autoComplete="off" spellCheck={false} maxLength={120} className={cn(control, 'mt-1')} value={config.namespace} onChange={(event) => setConfig({ ...config, namespace: event.target.value })} /></label></fieldset>
          <details className="min-w-0" open={!completed}><summary className="min-h-11 cursor-pointer py-3 text-sm font-semibold">Наборы и сопоставления ({config.datasets.length})</summary><TransferDatasets datasets={config.datasets} sheets={options.inspection?.sheets ?? batch.inspection.sheets} disabled={!editable} onChange={(datasets) => setConfig({ ...config, datasets })} /></details>
          <div ref={resolutionRef}><TransferResolutions config={config} caseSources={sources.cases} actorSources={sources.actors} disabled={!editable} cases={options.cases.map((item) => ({ id: item.id, label: `№${item.case_sequence} · ${item.title} · ${item.digital_product}` }))} users={options.users.map((item) => ({ id: item.id, label: `${item.full_name} · ${item.email}${item.eligible_current_assignment ? '' : ' · Только история'}` }))} onChange={setConfig} /></div>
          {!completed && <div className="flex flex-wrap items-center gap-3"><button type="submit" className={secondary} disabled={!editable}>{action === 'save' ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Save aria-hidden="true" className="h-4 w-4" />}Сохранить настройку</button>{dirty && <p role="status" className="text-sm text-muted-foreground">Есть несохранённые изменения переноса</p>}</div>}
        </form>
      </CanonicalLabels.Provider></PendingTranslations.Provider>
      {!completed && <div className="flex flex-wrap gap-2"><button type="button" disabled={!transfer || dirty || locked} className={cn(button, canCommit ? 'border border-border bg-surface text-foreground hover:bg-muted' : 'bg-primary text-primary-foreground hover:opacity-90')} onClick={() => transfer && void mutate('preview', () => auditLegacyTransfer.preview(transfer.id, transfer.revision))}>{action === 'preview' ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <ClipboardCheck aria-hidden="true" className="h-4 w-4" />}Проверить перенос</button>{canCommit && <button type="button" className={cn(button, 'bg-primary text-primary-foreground hover:opacity-90')} onClick={() => transfer?.preview && setConfirmation({ kind: 'commit', revision: transfer.revision, hash: transfer.preview.preview_hash })}><CheckCircle2 aria-hidden="true" className="h-4 w-4" />Перенести в реестр</button>}</div>}
      {needsPreview && !completed && <p className="text-sm text-muted-foreground">Перед подтверждением выполните новую проверку переноса.</p>}
      {pageError && <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">{pageError}</p>}
      {transfer?.preview && page && <TransferReport preview={transfer.preview} page={page} offset={offsets[offsets.length - 1]} previousOffset={offsets.length > 1 ? offsets[offsets.length - 2] : null} onPage={(offset) => void loadPage(offset)} loading={pageLoading} disabled={!editable} decisions={config.row_decisions} onChange={(row_decisions) => setConfig({ ...config, row_decisions })} sheets={batch.inspection.sheets} completed={completed} onResolve={(kind, source) => {
        if (kind === 'case' && !config.cases[source]) setConfig({ ...config, cases: { ...config.cases, [source]: { mode: 'existing' } } })
        if (kind === 'actor' && !config.actors[source]) setConfig({ ...config, actors: { ...config.actors, [source]: { mode: 'user' } } })
        resolutionRef.current?.scrollIntoView({ block: 'start' }); resolutionRef.current?.querySelector<HTMLElement>('select')?.focus()
      }} />}
    </>}
    {confirmation && transfer && <TransferConfirmation kind={confirmation.kind} revision={confirmation.revision} digest={confirmation.hash} working={Boolean(action)} blocked={stale} failure={error} summary={confirmation.kind === 'commit' ? `В рабочий реестр будут записаны результаты проверки ${transfer.preview?.total_rows ?? 0} строк. Пропущенные строки не переносятся.` : 'Записи этого переноса будут отменены при сохранении условий безопасного отката.'} onClose={() => setConfirmation(null)} onSubmit={(reason) => {
      if (confirmation.kind === 'commit' && !canCommit) return
      void mutate(confirmation.kind, () => confirmation.kind === 'commit' ? auditLegacyTransfer.commit(transfer.id, confirmation.revision, confirmation.hash) : auditLegacyTransfer.rollback(transfer.id, confirmation.revision, reason))
    }} />}
  </section>
}

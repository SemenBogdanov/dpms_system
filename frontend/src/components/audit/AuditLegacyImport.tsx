import { useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { UNSAFE_NavigationContext, useSearchParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, CheckCircle2, Download, FileSpreadsheet, Loader2, RefreshCcw, SlidersHorizontal, Trash2, Upload } from 'lucide-react'
import { ApiError } from '@/api/client'
import { auditLegacy, LEGACY_FIELDS, LEGACY_KINDS, LEGACY_MAX_FILE_BYTES, LEGACY_REQUIRED, type LegacyBatch, type LegacyField, type LegacyKind, type LegacyMapping, type LegacyReport, type LegacySheet } from '@/api/auditLegacy'
import { protectPersonalTaskPop } from '@/components/PersonalTaskFormNavigation'
import { cn } from '@/lib/utils'
import { AuditLegacyTransfer } from './AuditLegacyTransfer'

const control = 'h-11 min-h-11 w-full min-w-0 rounded-md border border-border bg-surface px-3 text-base text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50'
const button = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed'
const secondary = `${button} border border-border bg-surface text-foreground hover:bg-muted`
const notice = 'Файл сохранён для проверки. Рабочий реестр не изменён.'
type Draft = Omit<LegacyMapping, 'header_row'> & { header_row: string }
type Errors = Record<string, string>

function suggested(sheet: LegacySheet): Draft {
  return { sheet_id: sheet.id, header_row: String(sheet.header_row), kind: sheet.suggested_mapping.kind, fields: { ...sheet.suggested_mapping.fields } }
}
function draftFor(batch: LegacyBatch): Draft | null {
  return batch.mapping ? { ...batch.mapping, header_row: String(batch.mapping.header_row), fields: { ...batch.mapping.fields } }
    : batch.inspection.sheets[0] ? suggested(batch.inspection.sheets[0]) : null
}
function signature(draft: Draft | null): string {
  return draft ? JSON.stringify([draft.sheet_id, draft.header_row, draft.kind, Object.entries(draft.fields).filter(([, value]) => value).sort(([a], [b]) => a.localeCompare(b))]) : ''
}
function message(error: unknown) {
  return error instanceof Error ? error.message : 'Не удалось выполнить запрос. Повторите попытку.'
}
function batchLabel(batch: LegacyBatch) {
  return `${new Date(batch.created_at).toLocaleString('ru-RU')} · ${batch.sha256.slice(0, 8)}`
}

// Reuse the early popstate listener used by protected forms, before BrowserRouter.
function useStagingNavigationGuard(dirty: boolean, busy: React.MutableRefObject<boolean>, bypass: React.MutableRefObject<boolean>) {
  const { navigator } = useContext(UNSAFE_NavigationContext)
  const dirtyRef = useRef(dirty)
  dirtyRef.current = dirty
  useLayoutEffect(() => {
    const push = navigator.push
    const replace = navigator.replace
    let index = window.history.state?.idx as number | undefined
    let restoringDelta = 0
    let forwarding = false
    const mayLeave = () => bypass.current || (!busy.current && (!dirtyRef.current || window.confirm('Сопоставление не сохранено. Покинуть страницу и сбросить изменения?')))
    const guardedPush: typeof push = (...args) => {
      if (!restoringDelta && mayLeave()) { push(...args); index = window.history.state?.idx }
    }
    const guardedReplace: typeof replace = (...args) => {
      if (!restoringDelta && mayLeave()) { replace(...args); index = window.history.state?.idx }
    }
    const onPop = (event: PopStateEvent) => {
      if (forwarding || (!restoringDelta && !busy.current && !dirtyRef.current)) {
        forwarding = false
        index = event.state?.idx
        return
      }
      event.stopImmediatePropagation()
      if (restoringDelta) {
        const delta = restoringDelta
        restoringDelta = 0
        if (mayLeave()) { forwarding = true; window.history.go(delta) }
        return
      }
      const next = event.state?.idx as number | undefined
      if (typeof index === 'number' && typeof next === 'number' && index !== next) {
        restoringDelta = next - index
        window.history.go(index - next)
      }
    }
    const onUnload = (event: BeforeUnloadEvent) => {
      if (dirtyRef.current || busy.current) { event.preventDefault(); event.returnValue = '' }
    }
    navigator.push = guardedPush
    navigator.replace = guardedReplace
    const release = protectPersonalTaskPop(onPop)
    window.addEventListener('beforeunload', onUnload)
    return () => {
      if (navigator.push === guardedPush) navigator.push = push
      if (navigator.replace === guardedReplace) navigator.replace = replace
      release()
      window.removeEventListener('beforeunload', onUnload)
    }
  }, [bypass, busy, navigator])
}

function Report({ report, mapping }: { report: LegacyReport; mapping: LegacyMapping }) {
  const preview = report.preview_rows.slice(0, 30)
  const issues = report.issues.slice(0, 500)
  const fields = (Object.keys(LEGACY_FIELDS) as LegacyField[]).filter((field) => mapping.fields[field])
  return (
    <section aria-labelledby="legacy-report-title" className="min-w-0 space-y-4 border-t border-border pt-5">
      <h3 id="legacy-report-title" className="text-base font-semibold">Результат проверки</h3>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-5">
        {([['Всего строк', report.total_rows], ['Корректные строки', report.valid_rows], ['Строки с ошибками', report.error_rows], ['С предупреждениями', report.warning_rows], ['Дубликаты', report.duplicate_rows]] as const).map(([label, value]) => (
          <div key={label}><dt className="text-sm text-muted-foreground">{label}</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{value}</dd></div>
        ))}
      </dl>
      <p className="text-sm text-muted-foreground">Проверка файла завершена. Рабочий реестр не изменён.</p>
      {report.issue_count > 0 ? <div>
        <h4 className="mb-2 text-sm font-medium">Замечания: {report.issue_count}</h4>
        <ul className="max-h-80 divide-y divide-border overflow-auto" aria-label="Замечания проверки" tabIndex={0}>
          {issues.map((issue, index) => <li key={index} className="py-2 text-sm [overflow-wrap:anywhere]">
            <span className={issue.severity === 'error' ? 'font-medium text-rose-700 dark:text-rose-300' : 'font-medium text-amber-700 dark:text-amber-300'}>{issue.severity === 'error' ? 'Ошибка' : 'Предупреждение'}</span>
            {issue.row !== null && ` · Строка ${issue.row}`}{issue.column !== null && ` · Столбец ${issue.column}`}: {issue.message}
            <span className="ml-2 text-xs text-muted-foreground">{issue.code}</span>
          </li>)}
        </ul>
        {report.issue_count > issues.length && <p className="mt-2 text-sm text-muted-foreground">Показано {issues.length} из {report.issue_count} замечаний.</p>}
      </div> : <p className="flex items-center gap-2 text-sm"><CheckCircle2 aria-hidden="true" className="h-4 w-4 text-emerald-600" />Замечаний нет</p>}
      {report.unmapped_columns.length > 0 && <p className="text-sm text-muted-foreground [overflow-wrap:anywhere]">Несопоставленные столбцы: {report.unmapped_columns.join(', ')}</p>}
      <div>
        <h4 className="mb-2 text-sm font-medium">Предпросмотр: {preview.length} из {report.total_rows} строк</h4>
        {preview.length ? <div role="region" aria-label="Предпросмотр строк" tabIndex={0} className="max-h-96 overflow-auto border-y border-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">Первые 30 строк выбранного набора</caption>
            <thead className="sticky top-0 bg-surface-soft"><tr><th scope="col" className="px-3 py-2">Строка</th>{fields.map((field) => <th key={field} scope="col" className="min-w-40 max-w-72 px-3 py-2 [overflow-wrap:anywhere]">{LEGACY_FIELDS[field]} · {mapping.fields[field]}</th>)}</tr></thead>
            <tbody>{preview.map((row) => <tr key={row.row} className="border-t border-border"><th scope="row" className="px-3 py-2 tabular-nums">{row.row}</th>{fields.map((field) => <td key={field} className="max-w-72 px-3 py-2 align-top [overflow-wrap:anywhere]">{row.values[field] ?? '—'}</td>)}</tr>)}</tbody>
          </table>
        </div> : <p className="text-sm text-muted-foreground">Строк для предпросмотра нет.</p>}
      </div>
    </section>
  )
}

export function AuditLegacyImport() {
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('batch') || ''
  const transferId = params.get('transfer') || ''
  const [transferDirty, setTransferDirty] = useState(false)
  const [transferBusy, setTransferBusy] = useState(false)
  const [batches, setBatches] = useState<LegacyBatch[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [batch, setBatch] = useState<LegacyBatch | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [reload, setReload] = useState(0)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [baseline, setBaseline] = useState('')
  const [errors, setErrors] = useState<Errors>({})
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState('')
  const [action, setAction] = useState('')
  const [uploadNotice, setUploadNotice] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const formRef = useRef<HTMLFormElement>(null)
  const busy = useRef(false)
  const bypass = useRef(false)
  const mounted = useRef(true)
  const listRequest = useRef(0)
  const dirty = signature(draft) !== baseline
  useStagingNavigationGuard(dirty || Boolean(file) || transferDirty, busy, bypass)
  const selectedBatch = batch?.id === selectedId ? batch : null
  const sheet = selectedBatch?.inspection.sheets.find((item) => item.id === draft?.sheet_id)
  const checkedColumns = selectedBatch?.report?.sheet_id === draft?.sheet_id && selectedBatch?.report?.header_row === Number(draft?.header_row)
    ? selectedBatch?.report?.columns : null
  const mappingColumns = checkedColumns ?? sheet?.columns.map((column) => ({ ...column, label: Number(draft?.header_row) === sheet.header_row ? column.label : '' })) ?? []
  const blocked = Boolean(action) || loading || transferBusy
  useEffect(() => {
    if (!transferId || !selectedBatch) return
    const next = draftFor(selectedBatch)
    setDraft(next); setBaseline(signature(next)); setFile(null)
    if (fileInput.current) fileInput.current.value = ''
  }, [transferId, selectedBatch])

  const refreshList = useCallback(async () => {
    const request = ++listRequest.current
    setListLoading(true)
    setListError('')
    try {
      const result = await auditLegacy.list()
      if (mounted.current && request === listRequest.current) setBatches(result)
    } catch (cause) {
      if (mounted.current && request === listRequest.current) setListError(message(cause))
    } finally {
      if (mounted.current && request === listRequest.current) setListLoading(false)
    }
  }, [])
  useEffect(() => {
    mounted.current = true
    void refreshList()
    return () => { mounted.current = false; listRequest.current += 1 }
  }, [refreshList])

  useEffect(() => {
    const controller = new AbortController()
    setLoadError('')
    if (!selectedId) {
      setBatch(null); setDraft(null); setBaseline(''); setLoading(false); setError(''); setConflict(false)
      return () => controller.abort()
    }
    setLoading(true)
    void auditLegacy.get(selectedId, controller.signal).then((result) => {
      if (controller.signal.aborted) return
      const next = draftFor(result)
      setBatch(result); setDraft(next); setBaseline(signature(next)); setErrors({}); setError(''); setConflict(false)
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setLoadError(message(cause))
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [selectedId, reload])

  const selectBatch = (id: string, internal = false) => {
    const next = new URLSearchParams(params)
    next.delete('transfer')
    if (id) next.set('batch', id)
    else next.delete('batch')
    bypass.current = internal
    try { setParams(next) } finally { bypass.current = false }
  }
  const selectTransfer = (id: string, internal = false) => {
    const next = new URLSearchParams(params)
    if (id) next.set('transfer', id); else next.delete('transfer')
    bypass.current = internal
    try { setParams(next) } finally { bypass.current = false }
  }
  const start = (name: string) => {
    if (busy.current) return false
    busy.current = true; setAction(name); setError('')
    return true
  }
  const finish = () => {
    busy.current = false
    if (mounted.current) setAction('')
  }
  const handleFailure = (cause: unknown) => {
    if (!mounted.current) return
    setError(message(cause))
    if (cause instanceof ApiError && cause.status === 409) setConflict(true)
  }
  const upload = async (event: FormEvent) => {
    event.preventDefault()
    if (busy.current) return
    if (!file || !/\.xlsx$/i.test(file.name) || file.size === 0 || file.size > LEGACY_MAX_FILE_BYTES) {
      setFileError('Выберите непустой файл XLSX размером не более 10 МиБ.'); fileInput.current?.focus(); return
    }
    if (dirty && !window.confirm('Сопоставление не сохранено. Загрузить файл и сбросить изменения?')) return
    if (!start('upload')) return
    setUploadNotice('')
    try {
      const result = await auditLegacy.upload(file)
      if (!mounted.current) return
      setFile(null); setFileError('')
      if (fileInput.current) fileInput.current.value = ''
      setBatch(result)
      const next = draftFor(result)
      setDraft(next); setBaseline(signature(next)); setErrors({}); setConflict(false)
      setUploadNotice(notice)
      selectBatch(result.id, true)
      void refreshList()
    } catch (cause) { handleFailure(cause) } finally { finish() }
  }
  const check = async (event: FormEvent) => {
    event.preventDefault()
    if (!draft || !selectedBatch || !sheet || busy.current || loading || conflict) return
    const nextErrors: Errors = {}
    const header = Number(draft.header_row)
    if (!Number.isInteger(header) || header < 1 || header > 1048576) nextErrors.header_row = 'Укажите целый номер строки от 1 до 1048576.'
    for (const field of LEGACY_REQUIRED[draft.kind]) if (!draft.fields[field]) nextErrors[field] = 'Выберите столбец.'
    setErrors(nextErrors)
    if (nextErrors.header_row) {
      requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus())
      return
    }
    if (!start('check')) return
    try {
      const mapping: LegacyMapping = { ...draft, header_row: header, fields: Object.fromEntries(Object.entries(draft.fields).filter(([, value]) => value)) }
      const result = await auditLegacy.check(selectedBatch.id, selectedBatch.revision, mapping)
      if (!mounted.current) return
      const next = draftFor(result)
      setBatch(result); setDraft(next); setBaseline(signature(next)); setConflict(false)
      void refreshList()
    } catch (cause) { handleFailure(cause) } finally { finish() }
  }
  const reloadBatch = () => {
    if (busy.current || (dirty && !window.confirm('Загрузить актуальную ревизию и сбросить несохраненное сопоставление?'))) return
    setReload((value) => value + 1)
  }
  const download = async () => {
    if (!selectedBatch || !start('download')) return
    try {
      const blob = await auditLegacy.source(selectedBatch.id)
      if (!mounted.current) return
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = 'audit-legacy-source.xlsx'
      document.body.append(anchor); anchor.click(); anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (cause) { handleFailure(cause) } finally { finish() }
  }
  const remove = async () => {
    if (!selectedBatch || busy.current || conflict) return
    if (!window.confirm('Удалить сохранённый файл и результат проверки? Рабочий реестр не изменится.' + (dirty ? ' Несохраненное сопоставление будет потеряно.' : ''))) return
    if (!start('delete')) return
    try {
      await auditLegacy.remove(selectedBatch.id, selectedBatch.revision)
      if (!mounted.current) return
      setBatch(null); setDraft(null); setBaseline(''); setUploadNotice('Сохранённый файл удалён. Рабочий реестр не изменён.')
      selectBatch('', true)
      void refreshList()
    } catch (cause) { handleFailure(cause) } finally { finish() }
  }
  const fieldSelect = (field: LegacyField) => <div key={field} className="min-w-0">
    <label htmlFor={`legacy-field-${field}`} className="mb-1 block text-sm font-medium">{LEGACY_FIELDS[field]}{draft && LEGACY_REQUIRED[draft.kind].includes(field) ? ' *' : ''}</label>
    <select id={`legacy-field-${field}`} name={field} className={control} value={draft?.fields[field] || ''} disabled={blocked}
      aria-invalid={Boolean(errors[field])} aria-describedby={errors[field] ? `legacy-error-${field}` : undefined}
      onChange={(event) => { setDraft((value) => value && { ...value, fields: { ...value.fields, [field]: event.target.value } }); setErrors((value) => ({ ...value, [field]: '' })) }}>
      <option value="">Не сопоставлено</option>
      {mappingColumns.map((column) => <option key={column.column} value={column.column}>{column.column} · {column.label || 'Без заголовка'}</option>)}
    </select>
    {errors[field] && <p id={`legacy-error-${field}`} className="mt-1 text-sm text-rose-700 dark:text-rose-300">{errors[field]}</p>}
  </div>

  return <section aria-labelledby="legacy-title" className="min-w-0 space-y-5 text-foreground">
    <header className="border-b border-border pb-4">
      <h2 id="legacy-title" className="flex items-center gap-2 text-lg font-semibold"><FileSpreadsheet aria-hidden="true" className="h-5 w-5 shrink-0 text-primary" />Исторический импорт</h2>
      <p className="mt-1 text-sm text-muted-foreground">{transferId ? 'Источники и перенос данных' : 'Подготовка данных · без записи в рабочий реестр'}</p>
    </header>
    <form onSubmit={(event) => void upload(event)} noValidate className="space-y-2">
      <label htmlFor="legacy-file" className="block text-sm font-medium">Исходный файл XLSX · до 10 МиБ</label>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <input ref={fileInput} id="legacy-file" name="file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" disabled={blocked || Boolean(transferId)}
          className={cn(control, 'py-1 file:mr-2 file:min-h-9 file:rounded file:border-0 file:bg-muted file:px-2 file:text-sm file:text-foreground')}
          aria-invalid={Boolean(fileError)} aria-describedby={fileError ? 'legacy-file-error' : undefined}
          onChange={(event) => { setFile(event.target.files?.[0] ?? null); setFileError(''); setUploadNotice('') }} />
        <button type="submit" disabled={blocked || Boolean(transferId)} className={cn(secondary, 'shrink-0')}>
          {action === 'upload' ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Upload aria-hidden="true" className="h-4 w-4" />}Загрузить файл
        </button>
      </div>
      {fileError && <p id="legacy-file-error" role="alert" className="text-sm text-rose-700 dark:text-rose-300">{fileError}</p>}
    </form>
    {uploadNotice && !transferId && <p role="status" className="text-sm">{uploadNotice}</p>}
    <div className="border-y border-border py-4">
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <label htmlFor="legacy-batch" className="mb-1 block text-sm font-medium">Сохранённые файлы</label>
          <select id="legacy-batch" className={control} value={selectedId} disabled={Boolean(action) || transferBusy} onChange={(event) => selectBatch(event.target.value)}>
            <option value="">{listLoading ? 'Загрузка списка...' : batches.length ? 'Выберите файл' : 'Нет сохранённых файлов'}</option>
            {selectedId && !batches.some((item) => item.id === selectedId) && <option value={selectedId}>{selectedBatch ? batchLabel(selectedBatch) : 'Выбранный файл'}</option>}
            {batches.map((item) => <option key={item.id} value={item.id}>{batchLabel(item)} · {item.status === 'checked' ? 'Проверен' : 'Сохранён'}</option>)}
          </select>
        </div>
        <button type="button" aria-label="Обновить список файлов" title="Обновить список файлов" disabled={Boolean(action) || listLoading} onClick={() => void refreshList()} className={cn(secondary, 'h-11 w-11 shrink-0 p-0')}><RefreshCcw aria-hidden="true" className="h-4 w-4" /></button>
      </div>
      {listError && <p role="alert" className="mt-2 text-sm text-rose-700 [overflow-wrap:anywhere] dark:text-rose-300">{listError}</p>}
    </div>
    {loading && <p role="status" className="flex items-center gap-2 text-sm"><Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" />Загрузка файла...</p>}
    {loadError && <div role="alert" className="space-y-2 text-sm"><p className="text-rose-700 [overflow-wrap:anywhere] dark:text-rose-300">{loadError}</p><button type="button" onClick={reloadBatch} disabled={blocked} className={secondary}><RefreshCcw aria-hidden="true" className="h-4 w-4" />Повторить загрузку</button></div>}
    {error && <div role="alert" className="space-y-2 border-l-2 border-rose-400 pl-3 text-sm">
      <p className="flex items-start gap-2 [overflow-wrap:anywhere]"><AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0 text-rose-600" />{error}</p>
      {conflict && <><p>Ревизия изменилась. Ваше сопоставление сохранено в форме. Загрузите актуальную версию перед повторной проверкой.</p><button type="button" onClick={reloadBatch} disabled={blocked} className={secondary}><RefreshCcw aria-hidden="true" className="h-4 w-4" />Загрузить актуальную ревизию</button></>}
    </div>}
    {selectedBatch && <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1 text-sm">
          {!transferId && <p>{uploadNotice === notice ? null : notice}</p>}
          <p className="text-muted-foreground">{selectedBatch.status === 'checked' ? 'Проверен' : 'Сохранён'} · Ревизия {selectedBatch.revision} · {(selectedBatch.size_bytes / 1024).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} КиБ</p>
          <p className="break-all text-xs text-muted-foreground">SHA-256: {selectedBatch.sha256}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={blocked} onClick={() => void download()} className={secondary}><Download aria-hidden="true" className="h-4 w-4" />Скачать исходник</button>
          <button type="button" aria-label="Удалить сохранённый файл" title="Удалить сохранённый файл" disabled={blocked || conflict || Boolean(transferId)} onClick={() => void remove()} className={cn(secondary, 'h-11 w-11 p-0 text-rose-700 dark:text-rose-300')}><Trash2 aria-hidden="true" className="h-4 w-4" /></button>
          <button type="button" disabled={blocked} className={secondary} onClick={() => selectTransfer(transferId ? '' : 'new')}>{transferId ? <ArrowLeft aria-hidden="true" className="h-4 w-4" /> : <SlidersHorizontal aria-hidden="true" className="h-4 w-4" />}{transferId ? 'Вернуться к проверке файла' : 'Настроить перенос'}</button>
        </div>
      </div>
      {transferId ? <AuditLegacyTransfer key={selectedBatch.id} batch={selectedBatch} selectedId={transferId} onSelect={selectTransfer} busy={busy} onBusy={setTransferBusy} onDirty={setTransferDirty} /> : draft && sheet ? <form ref={formRef} onSubmit={(event) => void check(event)} noValidate className="min-w-0 space-y-4" aria-label="Сопоставление столбцов" aria-busy={action === 'check'}>
        <div className="grid min-w-0 gap-3 md:grid-cols-3">
          <div className="min-w-0"><label htmlFor="legacy-sheet" className="mb-1 block text-sm font-medium">Лист</label>
            <select id="legacy-sheet" name="sheet_id" className={control} value={draft.sheet_id} disabled={blocked} onChange={(event) => {
              const next = selectedBatch.inspection.sheets.find((item) => item.id === event.target.value)
              if (next && (!dirty || window.confirm('Сменить лист и сбросить несохраненное сопоставление?'))) { setDraft(suggested(next)); setErrors({}) }
            }}>{selectedBatch.inspection.sheets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
          </div>
          <div className="min-w-0"><label htmlFor="legacy-header" className="mb-1 block text-sm font-medium">Строка заголовков</label>
            <input id="legacy-header" name="header_row" type="number" inputMode="numeric" min={1} max={1048576} step={1} value={draft.header_row} disabled={blocked} className={control} aria-invalid={Boolean(errors.header_row)} aria-describedby={errors.header_row ? 'legacy-header-error' : undefined}
              onChange={(event) => { setDraft({ ...draft, header_row: event.target.value }); setErrors((value) => ({ ...value, header_row: '' })) }} />
            {errors.header_row && <p id="legacy-header-error" className="mt-1 text-sm text-rose-700 dark:text-rose-300">{errors.header_row}</p>}
          </div>
          <div className="min-w-0"><label htmlFor="legacy-kind" className="mb-1 block text-sm font-medium">Набор данных</label>
            <select id="legacy-kind" name="kind" className={control} value={draft.kind} disabled={blocked} onChange={(event) => { setDraft({ ...draft, kind: event.target.value as LegacyKind }); setErrors({}) }}>
              {Object.entries(LEGACY_KINDS).map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}
            </select>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">Строк данных: {sheet.row_count} · Столбцов: {sheet.column_count} · Формул: {sheet.formula_count}</p>
        <fieldset className="min-w-0"><legend className="mb-3 text-sm font-semibold">Обязательные поля</legend><div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-3">{LEGACY_REQUIRED[draft.kind].map(fieldSelect)}</div></fieldset>
        <details className="min-w-0 border-y border-border py-1"><summary className="min-h-11 cursor-pointer py-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">Дополнительные поля</summary>
          <div className="grid min-w-0 gap-3 pb-3 sm:grid-cols-2 xl:grid-cols-3">{(Object.keys(LEGACY_FIELDS) as LegacyField[]).filter((field) => !LEGACY_REQUIRED[draft.kind].includes(field)).map(fieldSelect)}</div>
        </details>
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" disabled={blocked || conflict} className={cn(button, 'bg-primary text-primary-foreground hover:opacity-90')}>
            {action === 'check' ? <Loader2 aria-hidden="true" className="h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" /> : <CheckCircle2 aria-hidden="true" className="h-4 w-4 shrink-0" />}Проверить сопоставление
          </button>
          {dirty && <p role="status" className="text-sm text-muted-foreground">Есть несохраненные изменения</p>}
        </div>
      </form> : <p role="status" className="text-sm">В файле нет доступных листов для сопоставления.</p>}
      {!transferId && selectedBatch.report && (selectedBatch.mapping && signature(draft) === signature({ ...selectedBatch.mapping, header_row: String(selectedBatch.mapping.header_row) })
        ? <Report report={selectedBatch.report} mapping={selectedBatch.mapping} />
        : <p className="border-t border-border pt-4 text-sm text-muted-foreground">Сопоставление изменено. Для актуального отчета выполните проверку.</p>)}
    </>}
  </section>
}

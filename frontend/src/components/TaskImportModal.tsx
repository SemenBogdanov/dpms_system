import { useEffect, useState, type ChangeEvent } from 'react'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Upload,
  X,
} from 'lucide-react'
import { api } from '@/api/client'
import type {
  CatalogItem,
  TaskImportCommitResponse,
  TaskImportPreview,
  TaskImportPreviewRow,
} from '@/api/types'
import { exportTaskImportCatalog, exportTaskImportTemplate } from '@/lib/csv'

interface TaskImportModalProps {
  open: boolean
  onClose: () => void
  onImported: () => void
}

function formatDueDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function rowStatus(row: TaskImportPreviewRow): JSX.Element {
  if (row.errors.length > 0) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-600">
        <AlertTriangle className="h-3.5 w-3.5" />
        Ошибка
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
      <CheckCircle2 className="h-3.5 w-3.5" />
      Готово
    </span>
  )
}

export function TaskImportModal({ open, onClose, onImported }: TaskImportModalProps) {
  const [catalog, setCatalog] = useState<CatalogItem[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<TaskImportPreview | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [importing, setImporting] = useState(false)

  useEffect(() => {
    if (!open) return
    api
      .get<CatalogItem[]>('/api/catalog', { is_active: 'true' })
      .then(setCatalog)
      .catch(() => setCatalog([]))
  }, [open])

  useEffect(() => {
    if (open) return
    setFile(null)
    setPreview(null)
    setPreviewing(false)
    setImporting(false)
  }, [open])

  if (!open) return null

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] ?? null
    setFile(selected)
    setPreview(null)
  }

  const handlePreview = async () => {
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    setPreviewing(true)
    try {
      const result = await api.upload<TaskImportPreview>('/api/tasks/import/preview', formData)
      setPreview(result)
      if (result.has_errors) {
        toast.error(`Найдено строк с ошибками: ${result.error_rows}`)
      } else {
        toast.success(`Готово к импорту: ${result.valid_rows} задач`)
      }
    } catch (e) {
      setPreview(null)
      toast.error(e instanceof Error ? e.message : 'Не удалось проверить CSV')
    } finally {
      setPreviewing(false)
    }
  }

  const handleImport = async () => {
    if (!file || !preview || preview.has_errors || preview.valid_rows === 0) return
    const formData = new FormData()
    formData.append('file', file)
    setImporting(true)
    try {
      const result = await api.upload<TaskImportCommitResponse>('/api/tasks/import', formData)
      toast.success(`Импортировано задач: ${result.created_count}`)
      onImported()
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось импортировать задачи')
    } finally {
      setImporting(false)
    }
  }

  const previewRows = preview?.rows ?? []
  const issueRows = previewRows.filter((row) => row.errors.length > 0)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="task-import-title"
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <div className="flex max-h-[calc(100vh-3rem)] w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-white shadow-lg">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-4">
          <div>
            <div className="flex items-center gap-2">
              <FileSpreadsheet className="h-5 w-5 text-accent-dark" aria-hidden="true" />
              <h2 id="task-import-title" className="text-lg font-semibold text-slate-900">
                Импорт задач из CSV
              </h2>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              Задачи попадут в очередь. Q, тип, сложность и лига считаются по активному справочнику операций.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label="Закрыть импорт задач"
            disabled={previewing || importing}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="overflow-y-auto px-6 py-4">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={exportTaskImportTemplate}
                    className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <Download className="h-4 w-4" />
                    Шаблон CSV
                  </button>
                  <button
                    type="button"
                    onClick={() => exportTaskImportCatalog(catalog)}
                    disabled={catalog.length === 0}
                    className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    <Download className="h-4 w-4" />
                    Справочник операций
                  </button>
                </div>
                <p className="mt-3 text-sm text-slate-600">
                  Обязательные колонки: title, quantity и catalog_item_id либо catalog_item_name. Теги можно разделять точкой с запятой, запятой или вертикальной чертой.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700" htmlFor="task-import-file">
                  CSV-файл
                </label>
                <div className="mt-1 flex flex-col gap-3 sm:flex-row sm:items-center">
                  <input
                    id="task-import-file"
                    type="file"
                    accept=".csv,text/csv"
                    onChange={handleFileChange}
                    className="block w-full rounded-md border border-slate-300 text-sm text-slate-700 file:mr-3 file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200"
                    disabled={previewing || importing}
                  />
                  <button
                    type="button"
                    onClick={handlePreview}
                    disabled={!file || previewing || importing}
                    className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-dark disabled:opacity-50"
                  >
                    <Upload className="h-4 w-4" />
                    {previewing ? 'Проверяем...' : 'Проверить'}
                  </button>
                </div>
              </div>

              {preview && (
                <div className="rounded-lg border border-slate-200 bg-white">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
                    <div className="text-sm text-slate-700">
                      Строк: {preview.total_rows} · готово: {preview.valid_rows} · ошибок: {preview.error_rows}
                    </div>
                    {preview.has_errors ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-1 text-xs font-medium text-red-600">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        Нужно исправить CSV
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        Можно импортировать
                      </span>
                    )}
                  </div>
                  <div className="max-h-96 overflow-auto">
                    <table className="min-w-full divide-y divide-slate-100">
                      <thead className="sticky top-0 bg-slate-50">
                        <tr>
                          <th className="px-3 py-2 text-left text-xs font-medium text-slate-600">Строка</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-slate-600">Статус</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-slate-600">Задача</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-slate-600">Операция</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-slate-600">Q</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-slate-600">Срок</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {previewRows.map((row) => (
                          <tr key={row.row_number} className={row.errors.length ? 'bg-red-50/40' : ''}>
                            <td className="whitespace-nowrap px-3 py-2 text-sm text-slate-500">{row.row_number}</td>
                            <td className="whitespace-nowrap px-3 py-2">{rowStatus(row)}</td>
                            <td className="min-w-64 px-3 py-2 text-sm text-slate-700">
                              <div className="font-medium">{row.title || '—'}</div>
                              {row.tags.length > 0 && (
                                <div className="mt-1 flex flex-wrap gap-1">
                                  {row.tags.map((tag) => (
                                    <span key={tag} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                                      {tag}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </td>
                            <td className="min-w-56 px-3 py-2 text-sm text-slate-600">
                              <div>{row.catalog_item_name ?? '—'}</div>
                              {row.task_type && row.complexity && row.min_league && (
                                <div className="mt-0.5 text-xs text-slate-400">
                                  {row.task_type} · {row.complexity} · лига {row.min_league} · x{row.quantity ?? 0}
                                </div>
                              )}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2 text-sm font-medium text-slate-700">
                              {row.estimated_q === null ? '—' : Number(row.estimated_q).toFixed(1)}
                            </td>
                            <td className="whitespace-nowrap px-3 py-2 text-sm text-slate-500">
                              {formatDueDate(row.due_date)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>

            <aside className="space-y-4">
              {preview?.warnings.map((warning) => (
                <div key={warning} className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                  {warning}
                </div>
              ))}

              <div className="rounded-lg border border-slate-200 bg-white p-4">
                <h3 className="text-sm font-semibold text-slate-800">Ошибки проверки</h3>
                {!preview && <p className="mt-2 text-sm text-slate-500">После проверки здесь появятся строки, которые нужно исправить.</p>}
                {preview && issueRows.length === 0 && (
                  <p className="mt-2 text-sm text-emerald-700">Ошибок нет.</p>
                )}
                {issueRows.length > 0 && (
                  <ul className="mt-2 max-h-72 space-y-2 overflow-y-auto">
                    {issueRows.map((row) =>
                      row.errors.map((issue) => (
                        <li key={`${row.row_number}-${issue.field}-${issue.message}`} className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
                          <span className="font-medium">Строка {row.row_number}, {issue.field}:</span> {issue.message}
                        </li>
                      ))
                    )}
                  </ul>
                )}
              </div>
            </aside>
          </div>
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            disabled={previewing || importing}
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={handleImport}
            disabled={!preview || preview.has_errors || preview.valid_rows === 0 || importing || previewing}
            className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-dark disabled:opacity-50"
          >
            <FileSpreadsheet className="h-4 w-4" />
            {importing ? 'Импортируем...' : `Импортировать${preview ? ` (${preview.valid_rows})` : ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}

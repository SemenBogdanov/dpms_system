import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Archive,
  ArchiveRestore,
  ChevronDown,
  ChevronRight,
  Download,
  ExternalLink,
  FileText,
  History,
  Link2,
  Loader2,
  Paperclip,
  Pencil,
  Plus,
  Trash2,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type {
  PersonalTask,
  PersonalTaskArtifact,
  PersonalTaskArtifactStatus,
  PersonalTaskArtifactType,
  PersonalTaskArtifactVersion,
} from '@/api/types'
import { cn } from '@/lib/utils'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'

const artifactTypeLabel: Record<PersonalTaskArtifactType, string> = {
  document: 'Документ',
  link: 'Ссылка',
  result: 'Результат',
}

const artifactTypeIcon: Record<PersonalTaskArtifactType, typeof FileText> = {
  document: FileText,
  link: Link2,
  result: Paperclip,
}

function formatBytes(bytes: number | null): string {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} ГБ`
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function ProtectedModal({ children }: { children: ReactNode }) {
  const panelRef = useProtectedModal<HTMLDivElement>()
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/50 p-3 backdrop-blur-sm sm:items-center"
      onPointerDown={preventBackdropDismiss}
    >
      <div ref={panelRef} tabIndex={-1} className="contents">
        {children}
      </div>
    </div>
  )
}

function IconTooltipButton({
  label,
  onClick,
  children,
  disabled,
  danger,
}: {
  label: string
  onClick: () => void
  children: ReactNode
  disabled?: boolean
  danger?: boolean
}) {
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        disabled={disabled}
        className={cn(
          'inline-flex h-8 items-center justify-center gap-1 rounded-lg border px-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40',
          danger
            ? 'border-rose-200 bg-white text-rose-600 hover:bg-rose-50 dark:border-rose-800 dark:bg-slate-900 dark:text-rose-300 dark:hover:bg-rose-950/40'
            : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800',
        )}
      >
        {children}
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-[calc(100%+0.35rem)] left-1/2 z-50 hidden w-max max-w-72 -translate-x-1/2 rounded-md bg-slate-950 px-2.5 py-1.5 text-center text-xs font-normal leading-4 text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 sm:block"
      >
        {label}
      </span>
    </span>
  )
}

function latestVersion(artifact: PersonalTaskArtifact): PersonalTaskArtifactVersion | null {
  if (!artifact.versions || artifact.versions.length === 0) return null
  return [...artifact.versions].sort((a, b) => b.version_number - a.version_number)[0]
}

type AddMode = 'create' | 'version'
type ArtifactSourceChoice = 'file' | 'link'
type AddForm = {
  artifactType: PersonalTaskArtifactType
  resultSource: ArtifactSourceChoice
  title: string
  description: string
  changeNote: string
  url: string
  file: File | null
}

const emptyAddForm: AddForm = {
  artifactType: 'document',
  resultSource: 'file',
  title: '',
  description: '',
  changeNote: '',
  url: '',
  file: null,
}

type EditForm = {
  title: string
  description: string
  status: PersonalTaskArtifactStatus
}

export function PersonalTaskArtifactsPanel({
  task,
  onChanged,
}: {
  task: PersonalTask
  onChanged?: () => void
}) {
  const [artifacts, setArtifacts] = useState<PersonalTaskArtifact[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [expandedHistory, setExpandedHistory] = useState<Set<string>>(new Set())
  const [addMode, setAddMode] = useState<AddMode | null>(null)
  const [addTarget, setAddTarget] = useState<PersonalTaskArtifact | null>(null)
  const [addForm, setAddForm] = useState<AddForm>(emptyAddForm)
  const [editTarget, setEditTarget] = useState<PersonalTaskArtifact | null>(null)
  const [editForm, setEditForm] = useState<EditForm>({
    title: '',
    description: '',
    status: 'active',
  })
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const taskArchived = task.status === 'archived'

  const loadArtifacts = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.get<PersonalTaskArtifact[]>(
        `/api/personal-tasks/${task.id}/artifacts`,
        { include_archived: 'true' },
      )
      setArtifacts(data)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки материалов')
    } finally {
      setLoading(false)
    }
  }, [task.id])

  useEffect(() => {
    void loadArtifacts()
  }, [loadArtifacts])

  const handleChange = useCallback(() => {
    void loadArtifacts()
    onChanged?.()
  }, [loadArtifacts, onChanged])

  const openCreate = () => {
    setAddMode('create')
    setAddTarget(null)
    setAddForm({ ...emptyAddForm })
  }

  const openAddVersion = (artifact: PersonalTaskArtifact) => {
    setAddMode('version')
    setAddTarget(artifact)
    setAddForm({
      ...emptyAddForm,
      artifactType: artifact.artifact_type,
      resultSource: latestVersion(artifact)?.source_kind ?? 'file',
    })
  }

  const closeAdd = () => {
    setAddMode(null)
    setAddTarget(null)
    setAddForm({ ...emptyAddForm })
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const needsFile = addForm.artifactType === 'document'
    || (addForm.artifactType === 'result' && addForm.resultSource === 'file')
  const needsUrl = addForm.artifactType === 'link'
    || (addForm.artifactType === 'result' && addForm.resultSource === 'link')

  const submitAdd = async () => {
    if (addMode === 'create' && !addForm.title.trim()) {
      toast.error('Укажите название')
      return
    }
    if (needsUrl && !addForm.url.trim()) {
      toast.error('Укажите URL')
      return
    }
    if (needsFile && !addForm.file) {
      toast.error('Выберите файл')
      return
    }
    setBusy(true)
    try {
      const fd = new FormData()
      if (addMode === 'create') {
        fd.append('artifact_type', addForm.artifactType)
        fd.append('title', addForm.title.trim())
        if (addForm.description.trim()) fd.append('description', addForm.description.trim())
        if (addForm.changeNote.trim()) fd.append('change_note', addForm.changeNote.trim())
        if (addForm.url.trim()) fd.append('url', addForm.url.trim())
        if (addForm.file) fd.append('file', addForm.file)
        await api.upload<PersonalTaskArtifact>(
          `/api/personal-tasks/${task.id}/artifacts`,
          fd,
        )
        toast.success('Материал добавлен')
      } else if (addTarget) {
        if (addForm.changeNote.trim()) fd.append('change_note', addForm.changeNote.trim())
        if (addForm.url.trim()) fd.append('url', addForm.url.trim())
        if (addForm.file) fd.append('file', addForm.file)
        await api.upload<PersonalTaskArtifact>(
          `/api/personal-tasks/${task.id}/artifacts/${addTarget.id}/versions`,
          fd,
        )
        toast.success('Версия добавлена')
      }
      closeAdd()
      handleChange()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setBusy(false)
    }
  }

  const openEdit = (artifact: PersonalTaskArtifact) => {
    setEditTarget(artifact)
    setEditForm({
      title: artifact.title,
      description: artifact.description || '',
      status: artifact.status,
    })
  }

  const closeEdit = () => {
    setEditTarget(null)
  }

  const submitEdit = async () => {
    if (!editTarget) return
    if (!editForm.title.trim()) {
      toast.error('Укажите название')
      return
    }
    setBusy(true)
    try {
      await api.patch<PersonalTaskArtifact>(
        `/api/personal-tasks/${task.id}/artifacts/${editTarget.id}`,
        {
          title: editForm.title.trim(),
          description: editForm.description.trim() || null,
          status: editForm.status,
        },
      )
      toast.success('Материал обновлён')
      closeEdit()
      handleChange()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка обновления')
    } finally {
      setBusy(false)
    }
  }

  const toggleArchive = async (artifact: PersonalTaskArtifact) => {
    const next: PersonalTaskArtifactStatus = artifact.status === 'archived' ? 'active' : 'archived'
    setBusy(true)
    try {
      await api.patch<PersonalTaskArtifact>(
        `/api/personal-tasks/${task.id}/artifacts/${artifact.id}`,
        { status: next },
      )
      toast.success(next === 'archived' ? 'Материал в архиве' : 'Материал восстановлен')
      handleChange()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка архивирования')
    } finally {
      setBusy(false)
    }
  }

  const permanentDelete = async (artifact: PersonalTaskArtifact) => {
    if (!taskArchived || artifact.status !== 'archived') {
      toast.error('Удаление доступно только для архивного материала в архивной задаче')
      return
    }
    if (!window.confirm('Безвозвратно удалить материал?')) return
    setBusy(true)
    try {
      await api.delete(`/api/personal-tasks/${task.id}/artifacts/${artifact.id}`)
      toast.success('Материал удалён')
      handleChange()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка удаления')
    } finally {
      setBusy(false)
    }
  }

  const downloadVersion = async (version: PersonalTaskArtifactVersion, title: string) => {
    if (version.source_kind === 'link' && version.url) {
      window.open(version.url, '_blank', 'noopener,noreferrer')
      return
    }
    setBusy(true)
    try {
      const blob = await api.blob(
        `/api/personal-tasks/${task.id}/artifacts/${version.artifact_id}/versions/${version.id}/content`,
      )
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = version.original_filename || title
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(objectUrl)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки файла')
    } finally {
      setBusy(false)
    }
  }

  const toggleHistory = (artifactId: string) => {
    setExpandedHistory((prev) => {
      const next = new Set(prev)
      if (next.has(artifactId)) next.delete(artifactId)
      else next.add(artifactId)
      return next
    })
  }

  const sortedArtifacts = useMemo(() => {
    return [...artifacts].sort((a, b) => {
      if (a.status !== b.status) return a.status === 'archived' ? 1 : -1
      return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
    })
  }, [artifacts])

  const canMutate = !taskArchived

  return (
    <section className="border-t border-slate-200 pt-4 dark:border-slate-700">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h4 className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
          <Paperclip className="h-4 w-4" />
          Материалы
        </h4>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">{artifacts.length}</span>
          {canMutate && (
            <IconTooltipButton label="Добавить материал" onClick={openCreate}>
              <Plus className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Добавить</span>
            </IconTooltipButton>
          )}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-6 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загрузка материалов…
        </div>
      ) : sortedArtifacts.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-200 p-3 text-xs text-slate-400 dark:border-slate-700">
          Материалы пока не добавлены.
        </p>
      ) : (
        <div className="space-y-2">
          {sortedArtifacts.map((artifact) => {
            const Icon = artifactTypeIcon[artifact.artifact_type]
            const version = latestVersion(artifact)
            const isArchived = artifact.status === 'archived'
            const historyOpen = expandedHistory.has(artifact.id)
            const versionCount = artifact.versions?.length || 0
            const canDelete = taskArchived && isArchived
            return (
              <div
                key={artifact.id}
                className={cn(
                  'rounded-lg border p-3',
                  isArchived
                    ? 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50'
                    : 'border-slate-200 dark:border-slate-700',
                )}
              >
                <div className="flex items-start gap-2">
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-slate-500 dark:text-slate-400" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className={cn(
                        'font-medium text-slate-900 dark:text-slate-100',
                        isArchived && 'text-slate-400 dark:text-slate-500',
                      )}>
                        {artifact.title}
                      </span>
                      <span className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500 dark:border-slate-600 dark:text-slate-400">
                        {artifactTypeLabel[artifact.artifact_type]}
                      </span>
                      {isArchived && (
                        <span className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] text-slate-500 dark:border-slate-600 dark:text-slate-400">
                          архив
                        </span>
                      )}
                    </div>
                    {artifact.description && (
                      <p className="mt-0.5 break-words text-xs text-slate-500 dark:text-slate-400">{artifact.description}</p>
                    )}
                    {version && (
                      <p className="mt-0.5 text-[11px] text-slate-400">
                        v{version.version_number}
                        {version.original_filename ? ` · ${version.original_filename}` : ''}
                        {version.size_bytes ? ` · ${formatBytes(version.size_bytes)}` : ''}
                        {version.created_at ? ` · ${formatDate(version.created_at)}` : ''}
                        {version.change_note ? ` · ${version.change_note}` : ''}
                      </p>
                    )}
                  </div>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {version && (
                    <>
                      {version.source_kind === 'link' && version.url ? (
                        <IconTooltipButton label="Открыть ссылку" onClick={() => window.open(version.url ?? "", "_blank", "noopener,noreferrer")}>
                          <ExternalLink className="h-3.5 w-3.5" />
                        </IconTooltipButton>
                      ) : (
                        <IconTooltipButton label="Скачать" onClick={() => void downloadVersion(version, artifact.title)}>
                          <Download className="h-3.5 w-3.5" />
                        </IconTooltipButton>
                      )}
                    </>
                  )}
                  {canMutate && artifact.can_edit && (
                    <>
                      {!isArchived && (
                        <IconTooltipButton label="Добавить версию" onClick={() => openAddVersion(artifact)} disabled={busy}>
                          <History className="h-3.5 w-3.5" />
                        </IconTooltipButton>
                      )}
                      <IconTooltipButton label="Редактировать" onClick={() => openEdit(artifact)} disabled={busy}>
                        <Pencil className="h-3.5 w-3.5" />
                      </IconTooltipButton>
                      <IconTooltipButton
                        label={isArchived ? 'Восстановить' : 'В архив'}
                        onClick={() => void toggleArchive(artifact)}
                        disabled={busy}
                      >
                        {isArchived ? <ArchiveRestore className="h-3.5 w-3.5" /> : <Archive className="h-3.5 w-3.5" />}
                      </IconTooltipButton>
                    </>
                  )}
                  {canDelete && (
                    <IconTooltipButton label="Удалить безвозвратно" onClick={() => void permanentDelete(artifact)} disabled={busy} danger>
                      <Trash2 className="h-3.5 w-3.5" />
                    </IconTooltipButton>
                  )}
                  {versionCount > 1 && (
                    <button
                      type="button"
                      onClick={() => toggleHistory(artifact.id)}
                      className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                    >
                      {historyOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                      История ({versionCount})
                    </button>
                  )}
                </div>

                {historyOpen && versionCount > 1 && (
                  <div className="mt-2 space-y-1 border-l-2 border-slate-200 pl-3 dark:border-slate-700">
                    {[...artifact.versions]
                      .sort((a, b) => b.version_number - a.version_number)
                      .map((v) => (
                        <div key={v.id} className="flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
                          <span className="shrink-0 tabular-nums font-medium">v{v.version_number}</span>
                          {v.source_kind === 'link' && v.url ? (
                            <button
                              type="button"
                              onClick={() => window.open(v.url ?? "", "_blank", "noopener,noreferrer")}
                              className="inline-flex items-center gap-1 text-sky-600 hover:underline dark:text-sky-400"
                            >
                              <ExternalLink className="h-3 w-3" />
                              открыть
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => void downloadVersion(v, artifact.title)}
                              className="inline-flex items-center gap-1 text-sky-600 hover:underline dark:text-sky-400"
                            >
                              <Download className="h-3 w-3" />
                              скачать
                            </button>
                          )}
                          {v.original_filename && <span className="truncate">{v.original_filename}</span>}
                          {v.size_bytes ? <span>· {formatBytes(v.size_bytes)}</span> : null}
                          <span>· {formatDate(v.created_at)}</span>
                        </div>
                      ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {addMode && (
        <ProtectedModal>
          <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-4 shadow-2xl dark:border-slate-700 dark:bg-slate-900">
            <div className="mb-4 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                {addMode === 'create' ? 'Новый материал' : `Новая версия: ${addTarget?.title ?? ''}`}
              </h3>
              <button type="button" onClick={closeAdd} aria-label="Закрыть" className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="grid gap-3">
              {addMode === 'create' && (
                <>
                  <label className="grid gap-1">
                    <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Тип</span>
                    <select
                      value={addForm.artifactType}
                      onChange={(e) => {
                        setAddForm((p) => ({
                          ...p,
                          artifactType: e.target.value as PersonalTaskArtifactType,
                          resultSource: 'file',
                          url: '',
                          file: null,
                        }))
                        if (fileInputRef.current) fileInputRef.current.value = ''
                      }}
                      className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400 dark:border-slate-700 dark:bg-slate-800"
                    >
                      <option value="document">Документ (файл)</option>
                      <option value="link">Ссылка (URL)</option>
                      <option value="result">Результат (файл или URL)</option>
                    </select>
                  </label>
                  <label className="grid gap-1">
                    <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Название</span>
                    <input
                      autoFocus
                      value={addForm.title}
                      onChange={(e) => setAddForm((p) => ({ ...p, title: e.target.value }))}
                      placeholder="Название материала"
                      className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400 dark:border-slate-700 dark:bg-slate-800"
                    />
                  </label>
                  <label className="grid gap-1">
                    <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Описание</span>
                    <input
                      value={addForm.description}
                      onChange={(e) => setAddForm((p) => ({ ...p, description: e.target.value }))}
                      placeholder="Краткое описание"
                      className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400 dark:border-slate-700 dark:bg-slate-800"
                    />
                  </label>
                </>
              )}
              {addForm.artifactType === 'result' && (
                <fieldset className="grid gap-1">
                  <legend className="text-xs font-medium text-slate-500 dark:text-slate-400">Формат результата</legend>
                  <div className="grid grid-cols-2 gap-2" role="group" aria-label="Формат результата">
                    {(['file', 'link'] as const).map((source) => (
                      <button
                        key={source}
                        type="button"
                        aria-pressed={addForm.resultSource === source}
                        onClick={() => {
                          setAddForm((previous) => ({
                            ...previous,
                            resultSource: source,
                            file: null,
                            url: '',
                          }))
                          if (fileInputRef.current) fileInputRef.current.value = ''
                        }}
                        className={cn(
                          'rounded-lg border px-3 py-2 text-sm font-medium transition-colors',
                          addForm.resultSource === source
                            ? 'border-primary bg-primary/10 text-primary'
                            : 'border-slate-200 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800',
                        )}
                      >
                        {source === 'file' ? 'Файл' : 'Ссылка'}
                      </button>
                    ))}
                  </div>
                </fieldset>
              )}
              {needsUrl && (
                <label className="grid gap-1">
                  <span className="text-xs font-medium text-slate-500 dark:text-slate-400">URL</span>
                  <input
                    value={addForm.url}
                    onChange={(e) => setAddForm((p) => ({ ...p, url: e.target.value }))}
                    placeholder="https://…"
                    className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400 dark:border-slate-700 dark:bg-slate-800"
                  />
                </label>
              )}
              {needsFile && (
                <label className="grid gap-1">
                  <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Файл</span>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.docx,.xlsx,.xls,.pptx,.txt,.md,.csv"
                    onChange={(e) => setAddForm((p) => ({ ...p, file: e.target.files?.[0] ?? null }))}
                    className="block w-full text-sm text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200 dark:text-slate-400 dark:file:bg-slate-800 dark:file:text-slate-200"
                  />
                </label>
              )}
              <label className="grid gap-1">
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Комментарий к версии</span>
                <input
                  value={addForm.changeNote}
                  onChange={(e) => setAddForm((p) => ({ ...p, changeNote: e.target.value }))}
                  placeholder="Что изменилось"
                  className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400 dark:border-slate-700 dark:bg-slate-800"
                />
              </label>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={closeAdd} className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">
                Отмена
              </button>
              <button type="button" onClick={() => void submitAdd()} disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40">
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                {addMode === 'create' ? 'Добавить' : 'Добавить версию'}
              </button>
            </div>
          </div>
        </ProtectedModal>
      )}

      {editTarget && (
        <ProtectedModal>
          <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-4 shadow-2xl dark:border-slate-700 dark:bg-slate-900">
            <div className="mb-4 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Редактировать материал</h3>
              <button type="button" onClick={closeEdit} aria-label="Закрыть" className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="grid gap-3">
              <label className="grid gap-1">
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Название</span>
                <input
                  autoFocus
                  value={editForm.title}
                  onChange={(e) => setEditForm((p) => ({ ...p, title: e.target.value }))}
                  className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400 dark:border-slate-700 dark:bg-slate-800"
                />
              </label>
              <label className="grid gap-1">
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Описание</span>
                <input
                  value={editForm.description}
                  onChange={(e) => setEditForm((p) => ({ ...p, description: e.target.value }))}
                  className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400 dark:border-slate-700 dark:bg-slate-800"
                />
              </label>
              <label className="grid gap-1">
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Статус</span>
                <select
                  value={editForm.status}
                  onChange={(e) => setEditForm((p) => ({ ...p, status: e.target.value as PersonalTaskArtifactStatus }))}
                  className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400 dark:border-slate-700 dark:bg-slate-800"
                >
                  <option value="active">Активный</option>
                  <option value="archived">Архивный</option>
                </select>
              </label>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={closeEdit} className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">
                Отмена
              </button>
              <button type="button" onClick={() => void submitEdit()} disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40">
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                Сохранить
              </button>
            </div>
          </div>
        </ProtectedModal>
      )}
    </section>
  )
}

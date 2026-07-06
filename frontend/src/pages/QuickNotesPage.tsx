import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  Archive,
  CheckCircle2,
  Copy,
  Download,
  FileText,
  Grid2X2,
  List,
  ListTodo,
  MessageSquare,
  Paperclip,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  Search,
  Send,
  Share2,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type {
  Contact,
  PersonalTask,
  QuickNote,
  QuickNoteAttachment,
  QuickNoteComment,
  QuickNoteCreate,
  QuickNoteShare,
  QuickNoteStatus,
  QuickNoteUpdate,
  SharedQuickNote,
} from '@/api/types'
import { cn } from '@/lib/utils'

type NoteFilter = QuickNoteStatus | 'all'
type NoteTab = 'mine' | 'shared'
type ViewMode = 'preview' | 'list'
type DetailState = { note: QuickNote; share?: QuickNoteShare } | null

const emptyForm = {
  title: '',
  body: '',
  context: '',
  tagsText: '',
}

const statusLabel: Record<QuickNoteStatus, string> = {
  draft: 'Черновик',
  processed: 'Разобрано',
  archived: 'Архив',
}

const filterOptions: Array<{ value: NoteFilter; label: string }> = [
  { value: 'all', label: 'Все' },
  { value: 'draft', label: 'Черновики' },
  { value: 'processed', label: 'Разобрано' },
  { value: 'archived', label: 'Архив' },
]

function parseTags(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
    .filter((item, index, array) => array.indexOf(item) === index)
    .slice(0, 8)
}

function tagsToText(value: string[] | null | undefined): string {
  return (value ?? []).join(', ')
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} Б`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} КБ`
  return `${(value / (1024 * 1024)).toFixed(1)} МБ`
}

function statusClass(status: QuickNoteStatus): string {
  if (status === 'draft') return 'bg-blue-50 text-blue-700'
  if (status === 'processed') return 'bg-emerald-50 text-emerald-700'
  return 'bg-slate-100 text-slate-600'
}

function previewText(value: string): string {
  const cleaned = value.replace(/\s+/g, ' ').trim()
  return cleaned.length > 180 ? `${cleaned.slice(0, 180)}...` : cleaned
}

function contactName(contact: Contact): string {
  return contact.direction === 'incoming' ? contact.requester_name : contact.recipient_name
}

function contactEmail(contact: Contact): string {
  return contact.direction === 'incoming' ? contact.requester_email : contact.recipient_email
}

function contactUserId(contact: Contact): string {
  return contact.direction === 'incoming' ? contact.requester_id : contact.recipient_id
}

function noteToPlainText(note: QuickNote): string {
  const lines = [note.title.trim() || 'Заметка', '', note.body.trim()]
  if (note.context) lines.push('', `Контекст: ${note.context}`)
  if (note.tags.length > 0) lines.push('', `Теги: ${note.tags.map((tag) => `#${tag}`).join(' ')}`)
  return lines.join('\n').trim()
}

function isSharedQuickNote(value: QuickNote | SharedQuickNote): value is SharedQuickNote {
  return Boolean((value as SharedQuickNote).share && (value as SharedQuickNote).note)
}

export function QuickNotesPage() {
  const navigate = useNavigate()
  const { noteId } = useParams<{ noteId: string }>()
  const [notes, setNotes] = useState<QuickNote[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<NoteFilter>('all')
  const [search, setSearch] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [activeTab, setActiveTab] = useState<NoteTab>('mine')
  const [contacts, setContacts] = useState<Contact[]>([])
  const [sharedNotes, setSharedNotes] = useState<SharedQuickNote[]>([])
  const [sharedLoading, setSharedLoading] = useState(false)
  const [sharesByNote, setSharesByNote] = useState<Record<string, QuickNoteShare[]>>({})
  const [selectedRecipients, setSelectedRecipients] = useState<Record<string, string[]>>({})
  const [commentsByNote, setCommentsByNote] = useState<Record<string, QuickNoteComment[]>>({})
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({})
  const [replyToByNote, setReplyToByNote] = useState<Record<string, QuickNoteComment | null>>({})
  const [attachmentsByNote, setAttachmentsByNote] = useState<Record<string, QuickNoteAttachment[]>>({})
  const [uploadingNoteId, setUploadingNoteId] = useState<string | null>(null)
  const [sharingBusy, setSharingBusy] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [promotingNoteId, setPromotingNoteId] = useState<string | null>(null)
  const [noteModalOpen, setNoteModalOpen] = useState(false)
  const [accessModalOpen, setAccessModalOpen] = useState(false)
  const [filesModalOpen, setFilesModalOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detail, setDetail] = useState<DetailState>(null)
  const [editing, setEditing] = useState<QuickNote | null>(null)
  const [form, setForm] = useState(emptyForm)

  const loadNotes = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (filter !== 'all') params.status = filter
      if (search.trim()) params.search = search.trim()
      const data = await api.get<QuickNote[]>('/api/quick-notes', params)
      setNotes(data)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки заметок')
    } finally {
      setLoading(false)
    }
  }, [filter, search])

  const loadContacts = useCallback(async () => {
    try {
      const data = await api.get<Contact[]>('/api/contacts')
      setContacts(data)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки контактов')
    }
  }, [])

  const loadSharedNotes = useCallback(async () => {
    setSharedLoading(true)
    try {
      const data = await api.get<SharedQuickNote[]>('/api/quick-notes/shared')
      setSharedNotes(data)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки общих заметок')
    } finally {
      setSharedLoading(false)
    }
  }, [])

  const loadNoteDetail = useCallback(async (id: string) => {
    setDetailLoading(true)
    try {
      const data = await api.get<QuickNote | SharedQuickNote>(`/api/quick-notes/${id}`)
      setDetail(isSharedQuickNote(data) ? { note: data.note, share: data.share } : { note: data })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки заметки')
      navigate('/quick-notes', { replace: true })
    } finally {
      setDetailLoading(false)
    }
  }, [navigate])

  const loadNoteShares = useCallback(async (noteId: string) => {
    try {
      const data = await api.get<QuickNoteShare[]>(`/api/quick-notes/${noteId}/shares`)
      setSharesByNote((current) => ({ ...current, [noteId]: data }))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки доступа')
    }
  }, [])

  const loadComments = useCallback(async (noteId: string) => {
    try {
      const data = await api.get<QuickNoteComment[]>(`/api/quick-notes/${noteId}/comments`)
      setCommentsByNote((current) => ({ ...current, [noteId]: data }))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки обсуждения')
    }
  }, [])

  const loadAttachments = useCallback(async (noteId: string) => {
    try {
      const data = await api.get<QuickNoteAttachment[]>(`/api/quick-notes/${noteId}/attachments`)
      setAttachmentsByNote((current) => ({ ...current, [noteId]: data }))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки вложений')
    }
  }, [])

  useEffect(() => {
    loadNotes()
  }, [loadNotes])

  useEffect(() => {
    loadContacts()
    loadSharedNotes()
  }, [loadContacts, loadSharedNotes])

  useEffect(() => {
    if (noteId) {
      void loadNoteDetail(noteId)
    } else {
      setDetail(null)
      setAccessModalOpen(false)
      setFilesModalOpen(false)
    }
  }, [loadNoteDetail, noteId])

  useEffect(() => {
    if (!detail) return
    void loadComments(detail.note.id)
    void loadAttachments(detail.note.id)
    if (!detail.share) void loadNoteShares(detail.note.id)
  }, [detail, loadAttachments, loadComments, loadNoteShares])

  const acceptedContacts = useMemo(
    () => contacts.filter((contact) => contact.status === 'accepted'),
    [contacts]
  )

  const stats = useMemo(() => {
    const source = activeTab === 'mine' ? notes : sharedNotes.map((item) => item.note)
    return {
      total: source.length,
      draft: source.filter((note) => note.status === 'draft').length,
      processed: source.filter((note) => note.status === 'processed').length,
    }
  }, [activeTab, notes, sharedNotes])

  const openCreate = () => {
    setEditing(null)
    setForm(emptyForm)
    setNoteModalOpen(true)
  }

  const openEdit = (note: QuickNote) => {
    setEditing(note)
    setForm({
      title: note.title,
      body: note.body,
      context: note.context ?? '',
      tagsText: tagsToText(note.tags),
    })
    setNoteModalOpen(true)
  }

  const closeNoteModal = () => {
    setNoteModalOpen(false)
    setEditing(null)
    setForm(emptyForm)
  }

  const handleSave = async () => {
    if (!form.body.trim()) {
      toast.error('Введите текст заметки')
      return
    }
    setBusy(true)
    try {
      if (editing) {
        const payload: QuickNoteUpdate = {
          title: form.title.trim() || null,
          body: form.body,
          context: form.context.trim() || null,
          tags: parseTags(form.tagsText),
        }
        const updated = await api.patch<QuickNote>(`/api/quick-notes/${editing.id}`, payload)
        setDetail((current) => current && current.note.id === updated.id ? { ...current, note: updated } : current)
        toast.success('Заметка сохранена')
      } else {
        await api.post<QuickNote>('/api/quick-notes', {
          title: form.title.trim() || null,
          body: form.body,
          context: form.context.trim() || null,
          tags: parseTags(form.tagsText),
        } satisfies QuickNoteCreate)
        toast.success('Заметка создана')
      }
      closeNoteModal()
      await loadNotes()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setBusy(false)
    }
  }

  const updateStatus = async (note: QuickNote, status: QuickNoteStatus) => {
    try {
      const updated = await api.patch<QuickNote>(`/api/quick-notes/${note.id}`, { status })
      setDetail((current) => current && current.note.id === updated.id ? { ...current, note: updated } : current)
      await loadNotes()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка статуса')
    }
  }

  const deleteNote = async (note: QuickNote) => {
    if (!window.confirm('Удалить заметку?')) return
    try {
      await api.delete(`/api/quick-notes/${note.id}`)
      if (detail?.note.id === note.id) navigate('/quick-notes', { replace: true })
      await loadNotes()
      toast.success('Заметка удалена')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка удаления')
    }
  }

  const copyNote = async (note: QuickNote) => {
    try {
      await navigator.clipboard?.writeText(noteToPlainText(note))
      toast.success('Текст скопирован')
    } catch {
      toast.error('Не удалось скопировать')
    }
  }

  const promoteToTask = async (note: QuickNote) => {
    setPromotingNoteId(note.id)
    try {
      await api.post<PersonalTask>('/api/personal-tasks', {
        title: note.title.trim() || 'Заметка',
        description: note.body,
        context: note.context ?? null,
        tags: note.tags,
        category: 'other',
        status: 'inbox',
        priority: 'medium',
        source_quick_note_id: note.id,
      })
      await loadNotes()
      if (detail?.note.id === note.id) await loadNoteDetail(note.id)
      toast.success('Личная задача создана')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка создания задачи')
    } finally {
      setPromotingNoteId(null)
    }
  }

  const toggleRecipient = (noteId: string, recipientId: string) => {
    setSelectedRecipients((current) => {
      const existing = current[noteId] ?? []
      const next = existing.includes(recipientId)
        ? existing.filter((item) => item !== recipientId)
        : [...existing, recipientId]
      return { ...current, [noteId]: next }
    })
  }

  const shareNote = async (note: QuickNote) => {
    const selected = selectedRecipients[note.id] ?? []
    if (selected.length === 0) {
      toast.error('Выберите контакты')
      return
    }
    setSharingBusy(note.id)
    try {
      await api.post<QuickNoteShare[]>(`/api/quick-notes/${note.id}/shares`, { recipient_ids: selected })
      setSelectedRecipients((current) => ({ ...current, [note.id]: [] }))
      await loadNoteShares(note.id)
      toast.success('Доступ открыт')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка шаринга')
    } finally {
      setSharingBusy(null)
    }
  }

  const revokeShare = async (noteId: string, shareId: string) => {
    try {
      await api.delete(`/api/quick-notes/shares/${shareId}`)
      await loadNoteShares(noteId)
      toast.success('Доступ закрыт')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка закрытия доступа')
    }
  }

  const sendComment = async (noteId: string) => {
    const body = commentDrafts[noteId]?.trim()
    if (!body) {
      toast.error('Введите текст комментария')
      return
    }
    const replyTo = replyToByNote[noteId]
    try {
      await api.post<QuickNoteComment>(`/api/quick-notes/${noteId}/comments`, {
        body,
        parent_id: replyTo?.id ?? null,
      })
      setCommentDrafts((current) => ({ ...current, [noteId]: '' }))
      setReplyToByNote((current) => ({ ...current, [noteId]: null }))
      await loadComments(noteId)
      toast.success('Комментарий отправлен')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка отправки комментария')
    }
  }

  const uploadAttachment = async (noteId: string, file: File | null) => {
    if (!file) return
    const body = new FormData()
    body.append('file', file)
    setUploadingNoteId(noteId)
    try {
      await api.upload<QuickNoteAttachment>(`/api/quick-notes/${noteId}/attachments`, body)
      await loadAttachments(noteId)
      toast.success('Файл добавлен')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки файла')
    } finally {
      setUploadingNoteId(null)
    }
  }

  const downloadAttachment = async (noteId: string, attachment: QuickNoteAttachment) => {
    try {
      const blob = await api.blob(`/api/quick-notes/${noteId}/attachments/${attachment.id}/content`)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = attachment.original_filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка скачивания')
    }
  }

  const renderDiscussion = (noteId: string) => {
    const comments = commentsByNote[noteId] ?? []
    const rootComments = comments.filter((comment) => !comment.parent_id)
    const repliesByParent = comments.reduce<Record<string, QuickNoteComment[]>>((acc, comment) => {
      if (comment.parent_id) acc[comment.parent_id] = [...(acc[comment.parent_id] ?? []), comment]
      return acc
    }, {})
    const draft = commentDrafts[noteId] ?? ''
    const replyTo = replyToByNote[noteId]

    return (
      <aside className="rounded-xl border border-slate-200 bg-slate-50/80 p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <MessageSquare className="h-4 w-4 text-primary" />
            Обсуждение
          </div>
          <button type="button" onClick={() => void loadComments(noteId)} className="text-xs font-medium text-primary hover:underline">
            обновить
          </button>
        </div>
        <div className="mt-3 max-h-[46vh] space-y-2 overflow-auto pr-1">
          {comments.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-300 bg-white px-3 py-4 text-sm text-slate-500">
              Комментариев пока нет.
            </div>
          ) : (
            rootComments.map((comment) => (
              <div key={comment.id} className="space-y-2">
                <div className="rounded-lg bg-white px-3 py-2 shadow-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
                    <span className="font-medium text-slate-700">{comment.author_name}</span>
                    <span>{formatDate(comment.created_at)}</span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-5 text-slate-600">{comment.body}</p>
                  <button
                    type="button"
                    onClick={() => setReplyToByNote((current) => ({ ...current, [noteId]: comment }))}
                    className="mt-2 text-xs font-medium text-primary hover:underline"
                  >
                    Ответить
                  </button>
                </div>
                {(repliesByParent[comment.id] ?? []).map((reply) => (
                  <div key={reply.id} className="ml-5 rounded-lg border-l-2 border-primary/25 bg-white px-3 py-2">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
                      <span className="font-medium text-slate-700">{reply.author_name}</span>
                      <span>{formatDate(reply.created_at)}</span>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-5 text-slate-600">{reply.body}</p>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
        {replyTo && (
          <div className="mt-3 flex items-center justify-between gap-2 rounded-lg bg-primary/10 px-3 py-2 text-xs text-primary">
            <span className="truncate">Ответ: {replyTo.author_name}</span>
            <button type="button" onClick={() => setReplyToByNote((current) => ({ ...current, [noteId]: null }))} className="font-medium hover:underline">
              сбросить
            </button>
          </div>
        )}
        <textarea
          value={draft}
          onChange={(event) => setCommentDrafts((current) => ({ ...current, [noteId]: event.target.value }))}
          rows={3}
          className="mt-3 min-h-24 w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
          placeholder="Комментарий к заметке"
        />
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={() => sendComment(noteId)}
            disabled={!draft.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
            Отправить
          </button>
        </div>
      </aside>
    )
  }

  const renderAccess = (note: QuickNote) => {
    const noteShares = sharesByNote[note.id] ?? []
    const sharedRecipientIds = new Set(noteShares.map((share) => share.recipient_id))
    const selected = selectedRecipients[note.id] ?? []

    return (
      <section className="rounded-xl border border-slate-200 bg-slate-50/80 p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Users className="h-4 w-4 text-primary" />
            Доступ
          </div>
          <button type="button" onClick={() => void loadNoteShares(note.id)} className="text-xs font-medium text-primary hover:underline">
            обновить
          </button>
        </div>
        {acceptedContacts.length === 0 ? (
          <div className="mt-3 rounded-lg border border-dashed border-slate-300 bg-white p-3 text-sm text-slate-500">
            Добавьте контакты в разделе <Link className="font-medium text-primary hover:underline" to="/contacts">Контакты</Link>.
          </div>
        ) : (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {acceptedContacts.map((contact) => {
              const recipientId = contactUserId(contact)
              const alreadyShared = sharedRecipientIds.has(recipientId)
              return (
                <label
                  key={contact.id}
                  className={cn(
                    'flex items-start gap-2 rounded-lg border bg-white p-2 text-sm',
                    alreadyShared ? 'border-primary/30 text-slate-400' : 'border-slate-200 text-slate-700'
                  )}
                >
                  <input
                    type="checkbox"
                    checked={alreadyShared || selected.includes(recipientId)}
                    disabled={alreadyShared}
                    onChange={() => toggleRecipient(note.id, recipientId)}
                    className="mt-1"
                  />
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{contactName(contact)}</span>
                    <span className="block truncate text-xs text-slate-400">
                      {alreadyShared ? 'доступ уже открыт' : contactEmail(contact)}
                    </span>
                  </span>
                </label>
              )
            })}
          </div>
        )}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <div className="text-xs text-slate-500">Открыт доступ: {noteShares.length}</div>
          <button
            type="button"
            onClick={() => shareNote(note)}
            disabled={sharingBusy === note.id || selected.length === 0}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            <Share2 className="h-4 w-4" />
            Поделиться
          </button>
        </div>
        {noteShares.length > 0 && (
          <div className="mt-3 space-y-2">
            {noteShares.map((share) => (
              <div key={share.id} className="flex items-center justify-between gap-2 rounded-lg bg-white px-3 py-2 text-sm">
                <div className="min-w-0">
                  <div className="truncate font-medium text-slate-700">{share.recipient_name}</div>
                  <div className="truncate text-xs text-slate-400">{share.recipient_email}</div>
                </div>
                <button
                  type="button"
                  onClick={() => revokeShare(note.id, share.id)}
                  className="rounded-md border border-red-100 px-2 py-1 text-xs font-medium text-red-500 hover:bg-red-50"
                >
                  Закрыть
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    )
  }

  const renderAttachments = (note: QuickNote, canUpload: boolean) => {
    const attachments = attachmentsByNote[note.id] ?? []
    return (
      <section className="rounded-xl border border-slate-200 bg-slate-50/80 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Paperclip className="h-4 w-4 text-primary" />
            Файлы
          </div>
          {canUpload && (
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
              <Plus className="h-4 w-4" />
              {uploadingNoteId === note.id ? 'Загрузка...' : 'Добавить'}
              <input
                type="file"
                className="hidden"
                disabled={uploadingNoteId === note.id}
                onChange={(event) => void uploadAttachment(note.id, event.target.files?.[0] ?? null)}
                accept=".png,.jpg,.jpeg,.webp,.gif,.docx,.xls,.xlsx"
              />
            </label>
          )}
        </div>
        {attachments.length === 0 ? (
          <div className="mt-3 rounded-lg border border-dashed border-slate-300 bg-white p-3 text-sm text-slate-500">
            Файлов пока нет.
          </div>
        ) : (
          <div className="mt-3 space-y-2">
            {attachments.map((attachment) => (
              <button
                key={attachment.id}
                type="button"
                onClick={() => downloadAttachment(note.id, attachment)}
                className="flex w-full items-center justify-between gap-3 rounded-lg bg-white px-3 py-2 text-left text-sm hover:bg-slate-50"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <FileText className="h-4 w-4 shrink-0 text-slate-400" />
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-slate-700">{attachment.original_filename}</span>
                    <span className="text-xs text-slate-400">{formatBytes(attachment.size_bytes)}</span>
                  </span>
                </span>
                <Download className="h-4 w-4 shrink-0 text-slate-400" />
              </button>
            ))}
          </div>
        )}
      </section>
    )
  }

  const renderNoteCard = (note: QuickNote, share?: QuickNoteShare) => {
    const isList = viewMode === 'list'
    return (
      <article
        key={share?.id ?? note.id}
        role="button"
        tabIndex={0}
        onClick={() => navigate(`/quick-notes/${note.id}`)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') navigate(`/quick-notes/${note.id}`)
        }}
        className={cn(
          'rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-primary/30 hover:shadow-md',
          isList ? 'flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between' : 'space-y-3'
        )}
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="break-words text-base font-semibold text-slate-900">{note.title}</h2>
            <span className={cn('rounded px-2 py-0.5 text-xs font-medium', statusClass(note.status))}>
              {statusLabel[note.status]}
            </span>
            {share && <span className="rounded bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">от {share.owner_name}</span>}
          </div>
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-400">
            <span>{formatDate(note.updated_at)}</span>
            {note.context && <span>{note.context}</span>}
          </div>
          {!isList && <p className="mt-3 break-words text-sm leading-6 text-slate-600">{previewText(note.body)}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2" onClick={(event) => event.stopPropagation()}>
          <button type="button" onClick={() => copyNote(note)} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" title="Скопировать" aria-label="Скопировать заметку">
            <Copy className="h-4 w-4" />
          </button>
          {!share && (
            <>
              <button type="button" onClick={() => openEdit(note)} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" title="Редактировать" aria-label="Редактировать заметку">
                <Pencil className="h-4 w-4" />
              </button>
              <button type="button" onClick={() => promoteToTask(note)} disabled={promotingNoteId === note.id} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-50" title="В личную задачу" aria-label="Создать личную задачу из заметки">
                <ListTodo className="h-4 w-4" />
              </button>
            </>
          )}
        </div>
      </article>
    )
  }

  const detailNote = detail?.note
  const detailIsOwner = Boolean(detail && !detail.share)

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      {!noteId && (
        <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Заметки</h1>
          <p className="mt-1 text-sm text-slate-500">Быстрый capture, файлы и обсуждение</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <div className="grid grid-cols-3 overflow-hidden rounded-lg border border-slate-200 bg-white text-center text-xs">
            <div className="px-3 py-2">
              <div className="font-semibold text-slate-900">{stats.total}</div>
              <div className="text-slate-400">в списке</div>
            </div>
            <div className="border-l border-slate-200 px-3 py-2">
              <div className="font-semibold text-blue-700">{stats.draft}</div>
              <div className="text-slate-400">черновики</div>
            </div>
            <div className="border-l border-slate-200 px-3 py-2">
              <div className="font-semibold text-emerald-700">{stats.processed}</div>
              <div className="text-slate-400">разобрано</div>
            </div>
          </div>
          {activeTab === 'mine' && (
            <button
              type="button"
              onClick={openCreate}
              className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              <Plus className="h-4 w-4" />
              Новая заметка
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <div className="grid grid-cols-2 overflow-hidden rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-500">
          <button
            type="button"
            onClick={() => setActiveTab('mine')}
            className={cn('px-4 py-2 transition', activeTab === 'mine' ? 'bg-primary text-primary-foreground' : 'hover:bg-slate-50')}
          >
            Мои
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('shared')}
            className={cn('border-l border-slate-200 px-4 py-2 transition', activeTab === 'shared' ? 'bg-primary text-primary-foreground' : 'hover:bg-slate-50')}
          >
            Доступные
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {activeTab === 'mine' && (
            <div className="grid grid-cols-4 overflow-hidden rounded-lg border border-slate-200 bg-white text-xs font-medium text-slate-500">
              {filterOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setFilter(option.value)}
                  className={cn('px-3 py-2 transition', filter === option.value ? 'bg-primary text-primary-foreground' : 'hover:bg-slate-50')}
                >
                  {option.label}
                </button>
              ))}
            </div>
          )}
          <div className="grid grid-cols-2 overflow-hidden rounded-lg border border-slate-200 bg-white">
            <button type="button" onClick={() => setViewMode('preview')} className={cn('p-2', viewMode === 'preview' ? 'bg-primary text-primary-foreground' : 'text-slate-500 hover:bg-slate-50')} title="Превью" aria-label="Показать заметки плитками">
              <Grid2X2 className="h-4 w-4" />
            </button>
            <button type="button" onClick={() => setViewMode('list')} className={cn('border-l border-slate-200 p-2', viewMode === 'list' ? 'bg-primary text-primary-foreground' : 'text-slate-500 hover:bg-slate-50')} title="Список" aria-label="Показать заметки компактным списком">
              <List className="h-4 w-4" />
            </button>
          </div>
          {activeTab === 'mine' && (
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="min-h-10 w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 lg:w-72"
                placeholder="Поиск"
              />
            </label>
          )}
        </div>
      </div>

      {activeTab === 'mine' ? (
        <section className={cn('grid gap-3', viewMode === 'preview' ? 'lg:grid-cols-2' : '')}>
          {loading && <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">Загрузка...</div>}
          {!loading && notes.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
              Заметок пока нет.
            </div>
          )}
          {notes.map((note) => renderNoteCard(note))}
        </section>
      ) : (
        <section className={cn('grid gap-3', viewMode === 'preview' ? 'lg:grid-cols-2' : '')}>
          {sharedLoading && <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">Загрузка...</div>}
          {!sharedLoading && sharedNotes.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
              Вам пока не открывали заметки.
            </div>
          )}
          {sharedNotes.map(({ share, note }) => renderNoteCard(note, share))}
        </section>
      )}
        </>
      )}

      {noteId && detailLoading && (
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-sm text-slate-500">Загрузка заметки...</div>
      )}

      {noteModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="max-h-[92vh] w-full max-w-3xl overflow-auto rounded-xl border border-slate-200 bg-white p-4 shadow-2xl">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-base font-semibold text-slate-900">
                <FileText className="h-5 w-5 text-primary" />
                {editing ? 'Редактирование заметки' : 'Новая заметка'}
              </div>
              <button type="button" onClick={closeNoteModal} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" aria-label="Закрыть окно заметки">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_180px]">
              <input
                type="text"
                value={form.context}
                onChange={(event) => setForm((current) => ({ ...current, context: event.target.value }))}
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
                placeholder="Контекст"
                maxLength={160}
              />
              <input
                type="text"
                value={form.tagsText}
                onChange={(event) => setForm((current) => ({ ...current, tagsText: event.target.value }))}
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
                placeholder="Теги"
              />
            </div>
            <input
              type="text"
              value={form.title}
              onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
              className="mt-3 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
              placeholder="Заголовок"
              maxLength={160}
            />
            <textarea
              value={form.body}
              onChange={(event) => setForm((current) => ({ ...current, body: event.target.value }))}
              rows={12}
              className="mt-3 min-h-[320px] w-full resize-y rounded-lg border border-slate-200 px-3 py-3 text-base leading-6 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
              placeholder="Текст заметки"
            />
            <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
              <button type="button" onClick={closeNoteModal} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">
                <X className="h-4 w-4" />
                Отмена
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={busy || !form.body.trim()}
                className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                <Save className="h-4 w-4" />
                {busy ? 'Сохранение...' : editing ? 'Сохранить' : 'Создать'}
              </button>
            </div>
          </div>
        </div>
      )}

      {detailNote && (
        <section className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-1">
                <button type="button" onClick={() => copyNote(detailNote)} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" title="Копировать" aria-label="Скопировать заметку">
                  <Copy className="h-4 w-4" />
                </button>
                {detailIsOwner && (
                  <>
                    <button type="button" onClick={() => openEdit(detailNote)} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" title="Редактировать" aria-label="Редактировать заметку">
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button type="button" onClick={() => promoteToTask(detailNote)} disabled={promotingNoteId === detailNote.id} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-50" title="В задачу" aria-label="Создать личную задачу из заметки">
                      <ListTodo className="h-4 w-4" />
                    </button>
                    <button type="button" onClick={() => updateStatus(detailNote, 'processed')} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-emerald-100 text-emerald-700 hover:bg-emerald-50" title="Разобрано" aria-label="Отметить заметку разобранной">
                      <CheckCircle2 className="h-4 w-4" />
                    </button>
                    <button type="button" onClick={() => updateStatus(detailNote, 'draft')} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" title="Черновик" aria-label="Вернуть заметку в черновики">
                      <RotateCcw className="h-4 w-4" />
                    </button>
                    <button type="button" onClick={() => updateStatus(detailNote, 'archived')} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" title="Архив" aria-label="Перенести заметку в архив">
                      <Archive className="h-4 w-4" />
                    </button>
                    <button type="button" onClick={() => deleteNote(detailNote)} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-red-100 text-red-600 hover:bg-red-50" title="Удалить" aria-label="Удалить заметку">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {detailIsOwner && (
                  <button type="button" onClick={() => setAccessModalOpen(true)} className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 px-3 text-sm font-medium text-slate-600 hover:bg-slate-50" aria-label="Настроить доступ к заметке">
                    <Share2 className="h-4 w-4" />
                    Доступ
                  </button>
                )}
                <button type="button" onClick={() => setFilesModalOpen(true)} className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 px-3 text-sm font-medium text-slate-600 hover:bg-slate-50" aria-label="Открыть файлы заметки">
                  <Paperclip className="h-4 w-4" />
                  Файлы
                </button>
                <button type="button" onClick={() => navigate('/quick-notes')} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" title="К списку" aria-label="Вернуться к списку заметок">
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="break-words text-xl font-semibold text-slate-900">{detailNote.title}</h2>
                  <span className={cn('rounded px-2 py-0.5 text-xs font-medium', statusClass(detailNote.status))}>
                    {statusLabel[detailNote.status]}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-400">
                  <span>{formatDate(detailNote.updated_at)}</span>
                  {detail?.share && <span>от {detail.share.owner_name}</span>}
                  {detailNote.context && <span>{detailNote.context}</span>}
                </div>
              </div>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
              <div className="min-w-0 space-y-4">
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{detailNote.body}</p>
                  {detailNote.tags.length > 0 && (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {detailNote.tags.map((tag) => (
                        <span key={tag} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">
                          #{tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              {renderDiscussion(detailNote.id)}
            </div>
          </div>
        </section>
      )}

      {detailNote && accessModalOpen && detailIsOwner && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-xl border border-slate-200 bg-white p-4 shadow-2xl">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-base font-semibold text-slate-900">
                <Share2 className="h-5 w-5 text-primary" />
                Доступ к заметке
              </div>
              <button type="button" onClick={() => setAccessModalOpen(false)} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" aria-label="Закрыть окно доступа">
                <X className="h-4 w-4" />
              </button>
            </div>
            {renderAccess(detailNote)}
          </div>
        </div>
      )}

      {detailNote && filesModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-xl border border-slate-200 bg-white p-4 shadow-2xl">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-base font-semibold text-slate-900">
                <Paperclip className="h-5 w-5 text-primary" />
                Файлы заметки
              </div>
              <button type="button" onClick={() => setFilesModalOpen(false)} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" aria-label="Закрыть окно файлов">
                <X className="h-4 w-4" />
              </button>
            </div>
            {renderAttachments(detailNote, detailIsOwner)}
          </div>
        </div>
      )}
    </div>
  )
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
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
  QuickNoteAttachment,
  QuickNoteComment,
  QuickNoteCreate,
  QuickNoteShare,
  QuickNoteStatus,
  QuickNoteUpdate,
  SharedQuickNote,
} from '@/api/types'
import { cn } from '@/lib/utils'
import { noteGroupsApi, type GroupedQuickNote as QuickNote, type NoteGroup } from '@/api/noteGroups'
import { NoteGroupsPanel } from '@/components/NoteGroupsPanel'
import { NoteBulkActions } from '@/components/NoteBulkActions'
import { NoteContextLinks } from '@/components/NoteContextLinks'
import { NoteShareDialog } from '@/components/NoteShareDialog'
import { useProtectedModal, preventBackdropDismiss } from '@/hooks/useProtectedModal'
import { useAttention } from '@/contexts/attentionState'
import {
  useQuickNoteLive,
  type LiveStatus,
  type QuickNoteLiveEvent,
} from '@/lib/quickNoteLive'

type NoteFilter = QuickNoteStatus | 'all'
type NoteTab = 'mine' | 'shared'
type ViewMode = 'preview' | 'list'
type DetailState = { note: QuickNote; share?: QuickNoteShare } | null
type LiveConflict = { message: string } | null

const emptyForm = {
  title: '',
  body: '',
  context: '',
  tagsText: '',
}
type NoteForm = typeof emptyForm

const statusLabel: Record<QuickNoteStatus, string> = {
  draft: 'Черновик',
  processed: 'Разобрано',
  archived: 'Архив',
}

const liveStatusLabel: Record<LiveStatus, string> = {
  idle: '',
  connecting: 'Синхронизация…',
  live: 'В эфире',
  reconnecting: 'Переподключение…',
  offline: 'Нет связи',
}

const liveStatusDot: Record<LiveStatus, string> = {
  idle: 'bg-transparent',
  connecting: 'bg-amber-400',
  live: 'bg-emerald-500',
  reconnecting: 'bg-amber-400',
  offline: 'bg-red-500',
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

function formDirtyFor(form: NoteForm, editing: QuickNote | null): boolean {
  if (!editing) {
    return Boolean(form.title.trim() || form.body.trim() || form.context.trim() || form.tagsText.trim())
  }
  return (
    form.title !== editing.title ||
    form.body !== editing.body ||
    form.context !== (editing.context ?? '') ||
    form.tagsText !== tagsToText(editing.tags)
  )
}

export function QuickNotesPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const groupView = searchParams.get('group') || 'all'
  const activeTab: NoteTab = searchParams.get('view') === 'shared' ? 'shared' : 'mine'
  const setActiveTab = (tab: NoteTab) => setSearchParams(params => { params.set('view', tab); return params })
  const setGroupView = (id: string) => setSearchParams(params => { params.set('group', id); return params })
  const [groups, setGroups] = useState<NoteGroup[]>([])
  const [groupError, setGroupError] = useState('')
  const notesRequest = useRef(0)
  const [selectedNotes, setSelectedNotes] = useState<string[]>([])
  const [bulkShare, setBulkShare] = useState<{ noteIds?: string[]; groupId?: string } | null>(null)
  const activeGroup = groups.find(group => group.id === groupView)
  const { noteId } = useParams<{ noteId: string }>()
  const { refresh: refreshAttention } = useAttention()
  const [notes, setNotes] = useState<QuickNote[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<NoteFilter>('all')
  const [search, setSearch] = useState('')
  const listScope = useMemo(() => ({ filter, search, groupView }), [filter, search, groupView])
  const currentListScope = useRef(listScope)
  currentListScope.current = listScope
  const [listError, setListError] = useState('')
  const [loadedListScope, setLoadedListScope] = useState<typeof listScope | null>(null)
  const groupsRequest = useRef(0)
  const [sharedError, setSharedError] = useState('')
  const sharedRequest = useRef(0)
  const detailRequest = useRef(0)
  const detailScope = useMemo(() => ({ id: noteId }), [noteId])
  const currentDetailScope = useRef(detailScope)
  currentDetailScope.current = detailScope
  const [detailError, setDetailError] = useState('')
  const sliceRequests = useRef<Record<string, number>>({})
  const [sliceErrors, setSliceErrors] = useState<Record<string, string>>({})
  const [contactsError, setContactsError] = useState('')
  const pending = useRef(new Set<string>())
  const [pendingIds, setPendingIds] = useState(new Set<string>())
  const begin = (id: string) => {
    if (pending.current.has(id)) return false
    pending.current.add(id)
    setPendingIds(new Set(pending.current))
    return true
  }
  const end = (id: string) => {
    pending.current.delete(id)
    setPendingIds(new Set(pending.current))
  }
  const saving = useRef(false)
  const editorSession = useRef(0)
  const [viewMode, setViewMode] = useState<ViewMode>('list')
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
  const [form, setForm] = useState<NoteForm>(emptyForm)
  const [remoteUpdated, setRemoteUpdated] = useState(false)
  const [conflict, setConflict] = useState<LiveConflict>(null)

  const notePanelRef = useProtectedModal<HTMLDivElement>(noteModalOpen)

  const markNoteAttentionRead = useCallback(async (id: string) => {
    try {
      await api.post<{ marked: number }>('/api/messages/attention/context/read', {
        source_type: 'quick_note',
        source_key: id,
      })
      await refreshAttention()
    } catch {
      // The note itself remains usable if the attention projection is offline.
    }
  }, [refreshAttention])

  const loadNotes = useCallback(async () => {
    const scope = listScope
    if (currentListScope.current !== scope) return
    const requestId = ++notesRequest.current
    const current = () => requestId === notesRequest.current && currentListScope.current === scope
    setLoading(true)
    setListError('')
    try {
      const params: Record<string, string> = {}
      if (filter !== 'all') params.status = filter
      if (search.trim()) params.search = search.trim()
      if (groupView === 'ungrouped') params.ungrouped = 'true'
      else if (groupView !== 'all') params.group_id = groupView
      const data = await api.get<QuickNote[]>('/api/quick-notes', params)
      if (!current()) return
      setNotes(data)
      setLoadedListScope(scope)
    } catch (e) {
      if (current()) {
        setListError(e instanceof Error ? e.message : 'Ошибка загрузки заметок')
      }
    } finally {
      if (current()) setLoading(false)
    }
  }, [filter, search, groupView, listScope])

  const loadGroups = useCallback(async () => {
    const request = ++groupsRequest.current
    try {
      const data = await noteGroupsApi.list()
      if (request === groupsRequest.current) { setGroups(data); setGroupError('') }
    } catch (error) {
      if (request === groupsRequest.current) setGroupError(error instanceof Error ? error.message : 'Группы недоступны')
    }
  }, [])
  const reloadOrganization = async () => { await loadGroups(); await loadNotes() }
  useEffect(() => () => {
    notesRequest.current += 1
    groupsRequest.current += 1
    sharedRequest.current += 1
    detailRequest.current += 1
    editorSession.current += 1
  }, [])
  useEffect(() => { void loadGroups() }, [loadGroups])
  useEffect(() => { setSelectedNotes([]) }, [groupView, activeTab, search, filter])

  const loadContacts = useCallback(async () => {
    try {
      const data = await api.get<Contact[]>('/api/contacts')
      setContacts(data)
      setContactsError('')
    } catch (e) {
      setContactsError(e instanceof Error ? e.message : 'Ошибка загрузки контактов')
    }
  }, [])

  const loadSharedNotes = useCallback(async () => {
    const request = ++sharedRequest.current
    setSharedLoading(true)
    setSharedError('')
    try {
      const data = await api.get<SharedQuickNote[]>('/api/quick-notes/shared')
      if (request === sharedRequest.current) setSharedNotes(data)
    } catch (e) {
      if (request === sharedRequest.current) setSharedError(e instanceof Error ? e.message : 'Ошибка загрузки общих заметок')
    } finally {
      if (request === sharedRequest.current) setSharedLoading(false)
    }
  }, [])

  const silentReloadList = loadNotes
  const silentReloadShared = loadSharedNotes

  const loadNoteDetail = useCallback(async (id: string) => {
    const scope = currentDetailScope.current
    if (scope.id !== id) return
    const request = ++detailRequest.current
    const currentRequest = () => currentDetailScope.current === scope && request === detailRequest.current
    setDetailLoading(true)
    setDetailError('')
    try {
      const data = await api.get<QuickNote | SharedQuickNote>(`/api/quick-notes/${id}`)
      if (!currentRequest()) return
      if ((isSharedQuickNote(data) ? data.note.id : data.id) !== id) throw new Error('Ответ не соответствует выбранной заметке')
      setDetail((current) => {
        const next = isSharedQuickNote(data)
          ? { note: data.note, share: data.share }
          : { note: data }
        if (
          current
          && current.note.id === next.note.id
          && current.note.revision > next.note.revision
        ) {
          return current
        }
        return next
      })
    } catch (e) {
      if (currentRequest()) setDetailError(e instanceof Error ? e.message : 'Ошибка загрузки заметки')
    } finally {
      if (currentRequest()) setDetailLoading(false)
    }
  }, [])

  const loadSlice = useCallback(async <T,>(id: string, slice: string, apply: (data: T) => void) => {
    const scope = currentDetailScope.current
    if (scope.id !== id) return
    const key = `${slice}:${id}`
    const request = (sliceRequests.current[key] ?? 0) + 1
    sliceRequests.current[key] = request
    const current = () => currentDetailScope.current === scope && sliceRequests.current[key] === request
    try {
      const data = await api.get<T>(`/api/quick-notes/${id}/${slice}`)
      if (!current()) return
      apply(data)
      setSliceErrors(errors => ({ ...errors, [key]: '' }))
    } catch (e) {
      if (current()) setSliceErrors(errors => ({ ...errors, [key]: e instanceof Error ? e.message : 'Не удалось загрузить данные' }))
    }
  }, [])

  const loadNoteShares = useCallback((id: string) => loadSlice<QuickNoteShare[]>(id, 'shares', data => {
    setSharesByNote(current => ({ ...current, [id]: data }))
  }), [loadSlice])
  const loadComments = useCallback((id: string) => loadSlice<QuickNoteComment[]>(id, 'comments', data => {
    setCommentsByNote(current => ({ ...current, [id]: data }))
  }), [loadSlice])
  const loadAttachments = useCallback((id: string) => loadSlice<QuickNoteAttachment[]>(id, 'attachments', data => {
    setAttachmentsByNote(current => ({ ...current, [id]: data }))
  }), [loadSlice])
  const silentSyncSlices = useCallback(async (id: string) => {
    await Promise.all([loadNoteDetail(id), loadComments(id), loadAttachments(id), loadNoteShares(id)])
  }, [loadNoteDetail, loadComments, loadAttachments, loadNoteShares])

  useEffect(() => {
    loadNotes()
  }, [loadNotes])

  useEffect(() => {
    loadContacts()
    loadSharedNotes()
  }, [loadContacts, loadSharedNotes])

  useEffect(() => {
    if (noteId) {
      setRemoteUpdated(false)
      setConflict(null)
      void loadNoteDetail(noteId)
    } else {
      setDetail(null)
      setAccessModalOpen(false)
      setFilesModalOpen(false)
    }
  }, [loadNoteDetail, noteId])

  const detailNoteId = detail?.note.id
  const detailIsShared = Boolean(detail?.share)

  useEffect(() => {
    if (!detailNoteId) return
    void markNoteAttentionRead(detailNoteId)
    void loadComments(detailNoteId)
    void loadAttachments(detailNoteId)
    if (!detailIsShared) void loadNoteShares(detailNoteId)
  }, [detailIsShared, detailNoteId, loadAttachments, loadComments, loadNoteShares, markNoteAttentionRead])

  const { status: liveStatus, activeUsers } = useQuickNoteLive(noteId, {
    onReady: () => {
      if (noteId) {
        void markNoteAttentionRead(noteId)
        void silentSyncSlices(noteId)
        void silentReloadList()
        void silentReloadShared()
      }
    },
    onResync: (event: QuickNoteLiveEvent) => {
      if (
        event.type === 'note.updated'
        && noteModalOpen
        && editing
        && !busy
        && formDirtyFor(form, editing)
      ) {
        setRemoteUpdated(true)
      }
      if (event.note_id) {
        if (event.type === 'comment.created' || event.type === 'access.changed') {
          void markNoteAttentionRead(event.note_id)
        }
        void silentSyncSlices(event.note_id)
        void silentReloadList()
        void silentReloadShared()
      }
    },
    onDeleted: () => {
      toast('Заметка удалена')
      navigate('/quick-notes', { replace: true })
    },
    onRevoked: () => {
      if (detail?.share) {
        toast.error('Доступ к заметке закрыт')
        navigate('/quick-notes', { replace: true })
      } else {
        void silentSyncSlices(noteId ?? '')
      }
    },
  })

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

  const isFormDirty = useCallback(() => formDirtyFor(form, editing), [form, editing])

  const openCreate = () => {
    if (saving.current) return
    editorSession.current += 1
    setEditing(null)
    setForm(emptyForm)
    setRemoteUpdated(false)
    setConflict(null)
    setNoteModalOpen(true)
  }

  const openEdit = (note: QuickNote) => {
    if (saving.current) return
    editorSession.current += 1
    setEditing(note)
    setForm({
      title: note.title,
      body: note.body,
      context: note.context ?? '',
      tagsText: tagsToText(note.tags),
    })
    setRemoteUpdated(false)
    setConflict(null)
    setNoteModalOpen(true)
  }

  const forceCloseNoteModal = () => {
    editorSession.current += 1
    setNoteModalOpen(false)
    setEditing(null)
    setForm(emptyForm)
    setRemoteUpdated(false)
    setConflict(null)
  }

  const confirmDiscardOrClose = () => {
    if (saving.current) return
    if (isFormDirty()) {
      if (!window.confirm('Есть несохранённые изменения. Закрыть без сохранения?')) return
    }
    forceCloseNoteModal()
  }

  const loadFreshVersion = async () => {
    if (!editing || saving.current) return
    if (!window.confirm('Загрузить актуальную версию? Несохранённые изменения будут заменены.')) return
    const session = editorSession.current
    saving.current = true
    setBusy(true)
    try {
      const data = await api.get<QuickNote | SharedQuickNote>(`/api/quick-notes/${editing.id}`)
      const fresh = isSharedQuickNote(data) ? data.note : data
      if (editorSession.current !== session) return
      if (fresh.id !== editing.id) throw new Error('Ответ не соответствует выбранной заметке')
      saving.current = false
      openEdit(fresh)
      toast.success('Загружена актуальная версия')
    } catch (e) {
      if (editorSession.current === session) toast.error(e instanceof Error ? e.message : 'Ошибка загрузки версии')
    } finally {
      saving.current = false
      setBusy(false)
    }
  }

  const handleSave = async () => {
    if (saving.current) return
    if (!form.body.trim()) {
      toast.error('Введите текст заметки')
      return
    }
    saving.current = true
    const session = editorSession.current
    setBusy(true)
    try {
      if (editing) {
        const payload: QuickNoteUpdate = {
          title: form.title.trim() || null,
          body: form.body,
          context: form.context.trim() || null,
          tags: parseTags(form.tagsText),
          base_revision: editing.revision,
        }
        const updated = await api.patch<QuickNote>(`/api/quick-notes/${editing.id}`, payload)
        if (session !== editorSession.current) return
        setDetail((current) => (current && current.note.id === updated.id && current.note.revision <= updated.revision ? { ...current, note: updated } : current))
        setRemoteUpdated(false)
        setConflict(null)
        toast.success('Заметка сохранена')
      } else {
        await api.post<QuickNote>('/api/quick-notes', {
          ...(activeGroup && !activeGroup.archived ? { group_id: activeGroup.id } : {}),
          title: form.title.trim() || null,
          body: form.body,
          context: form.context.trim() || null,
          tags: parseTags(form.tagsText),
        } satisfies QuickNoteCreate)
        if (session !== editorSession.current) return
        toast.success('Заметка создана')
      }
      forceCloseNoteModal()
      await loadNotes()
      await loadGroups()
      await silentReloadShared()
    } catch (e) {
      if (session !== editorSession.current) return
      const message = e instanceof Error ? e.message : 'Ошибка сохранения'
      const isNetwork = e instanceof Error && e.name === 'ApiUnavailableError'
      const looksConflict = /устарел|конфликт|conflict|409|версия/i.test(message)
      if (looksConflict || (remoteUpdated && !isNetwork)) {
        setConflict({ message: message || 'Версия заметки устарела. Загрузите актуальную версию.' })
        toast.error('Версия устарела — заметка изменена с другого устройства')
      } else {
        toast.error(message)
      }
    } finally {
      saving.current = false
      setBusy(false)
    }
  }

  const updateStatus = async (note: QuickNote, status: QuickNoteStatus) => {
    if (!begin(note.id)) return
    try {
      const updated = await api.patch<QuickNote>(`/api/quick-notes/${note.id}`, {
        status,
        base_revision: note.revision,
      })
      setDetail((current) => (current && current.note.id === updated.id && current.note.revision <= updated.revision ? { ...current, note: updated } : current))
      await loadNotes()
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Ошибка статуса'
      if (/устарел|конфликт|conflict|409|версия/i.test(message)) {
        toast.error('Версия устарела — обновите заметку')
        if (currentDetailScope.current.id === note.id) void loadNoteDetail(note.id)
      } else {
        toast.error(message)
      }
    } finally { end(note.id) }
  }

  const deleteNote = async (note: QuickNote) => {
    if (pending.current.has(note.id)) return
    if (!window.confirm('Удалить заметку?')) return
    if (!begin(note.id)) return
    try {
      await api.delete(`/api/quick-notes/${note.id}`)
      if (currentDetailScope.current.id === note.id) navigate('/quick-notes', { replace: true })
      await loadNotes()
      toast.success('Заметка удалена')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка удаления')
    } finally { end(note.id) }
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
    if (!begin(note.id)) return
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
      if (currentDetailScope.current.id === note.id) await loadNoteDetail(note.id)
      toast.success('Личная задача создана')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка создания задачи')
    } finally {
      end(note.id)
      setPromotingNoteId(current => current === note.id ? null : current)
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
    if (!begin(`share:${note.id}`)) return
    setSharingBusy(note.id)
    try {
      await api.post<QuickNoteShare[]>(`/api/quick-notes/${note.id}/shares`, { recipient_ids: selected })
      setSelectedRecipients((current) => ({ ...current, [note.id]: [] }))
      await loadNoteShares(note.id)
      toast.success('Доступ открыт')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка шаринга')
    } finally {
      end(`share:${note.id}`)
      setSharingBusy(current => current === note.id ? null : current)
    }
  }

  const revokeShare = async (noteId: string, shareId: string) => {
    if (!begin(`revoke:${shareId}`)) return
    try {
      await api.delete(`/api/quick-notes/shares/${shareId}`)
      await loadNoteShares(noteId)
      toast.success('Доступ закрыт')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка отзыва доступа')
    } finally { end(`revoke:${shareId}`) }
  }

  const sendComment = async (noteId: string) => {
    const draft = commentDrafts[noteId] ?? ''
    const replyTo = replyToByNote[noteId]
    if (!draft.trim()) return
    if (!begin(`comment:${noteId}`)) return
    try {
      await api.post<QuickNoteComment>(`/api/quick-notes/${noteId}/comments`, {
        body: draft.trim(),
        parent_id: replyTo?.id ?? null,
      })
      setCommentDrafts((current) => current[noteId] === draft ? { ...current, [noteId]: '' } : current)
      setReplyToByNote((current) => current[noteId] === replyTo ? { ...current, [noteId]: null } : current)
      await loadComments(noteId)
      toast.success('Комментарий отправлен')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка отправки комментария')
    } finally { end(`comment:${noteId}`) }
  }

  const uploadAttachment = async (noteId: string, file: File | null) => {
    if (!file) return
    if (!begin(`upload:${noteId}`)) return
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
      end(`upload:${noteId}`)
      setUploadingNoteId(current => current === noteId ? null : current)
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

  const deleteAttachment = async (noteId: string, attachment: QuickNoteAttachment) => {
    if (pending.current.has(`file:${attachment.id}`)) return
    if (!window.confirm(`Удалить файл «${attachment.original_filename}»?`)) return
    if (!begin(`file:${attachment.id}`)) return
    try {
      await api.delete(`/api/quick-notes/${noteId}/attachments/${attachment.id}`)
      await loadAttachments(noteId)
      toast.success('Файл удален')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка удаления файла')
    } finally { end(`file:${attachment.id}`) }
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
        </div>
        <div className="mt-3 max-h-[46vh] space-y-2 overflow-auto pr-1">
          {sliceErrors[`comments:${noteId}`] && <p role="alert">{sliceErrors[`comments:${noteId}`]} <button type="button" onClick={() => void loadComments(noteId)}>Повторить</button></p>}
          {comments.length === 0 && !sliceErrors[`comments:${noteId}`] ? (
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
                    disabled={pendingIds.has(`comment:${noteId}`)}
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
            <button type="button" disabled={pendingIds.has(`comment:${noteId}`)} onClick={() => setReplyToByNote((current) => ({ ...current, [noteId]: null }))} className="font-medium hover:underline">
              сбросить
            </button>
          </div>
        )}
        <textarea
          disabled={pendingIds.has(`comment:${noteId}`)}
          value={draft}
          onChange={(event) => setCommentDrafts((current) => ({ ...current, [noteId]: event.target.value }))}
          rows={3}
          className="mt-3 min-h-24 w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-base outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
          placeholder="Комментарий к заметке"
        />
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={() => sendComment(noteId)}
            disabled={!draft.trim() || pendingIds.has(`comment:${noteId}`)}
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
        </div>
        <p className="mt-2 text-xs text-slate-500">Получатели могут читать заметку и оставлять комментарии.</p>
        {contactsError && <p role="alert">{contactsError} <button type="button" onClick={() => void loadContacts()}>Повторить</button></p>}
        {sliceErrors[`shares:${note.id}`] && <p role="alert">{sliceErrors[`shares:${note.id}`]} <button type="button" onClick={() => void loadNoteShares(note.id)}>Повторить</button></p>}
        {acceptedContacts.length === 0 && !contactsError ? (
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
                    disabled={alreadyShared || pendingIds.has(`share:${note.id}`)}
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
            disabled={sharingBusy === note.id || pendingIds.has(`share:${note.id}`) || selected.length === 0}
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
                  disabled={pendingIds.has(`revoke:${share.id}`)}
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
                disabled={uploadingNoteId === note.id || pendingIds.has(`upload:${note.id}`)}
                onChange={(event) => void uploadAttachment(note.id, event.target.files?.[0] ?? null)}
                accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.docx,.xls,.xlsx,.pptx,.txt,.md,.csv"
              />
            </label>
          )}
        </div>
        {sliceErrors[`attachments:${note.id}`] && <p role="alert">{sliceErrors[`attachments:${note.id}`]} <button type="button" onClick={() => void loadAttachments(note.id)}>Повторить</button></p>}
        {attachments.length === 0 && !sliceErrors[`attachments:${note.id}`] ? (
          <div className="mt-3 rounded-lg border border-dashed border-slate-300 bg-white p-3 text-sm text-slate-500">
            Файлов пока нет.
          </div>
        ) : (
          <div className="mt-3 space-y-2">
            {attachments.map((attachment) => (
              <div key={attachment.id} className="flex items-center gap-1 rounded-lg bg-white p-1">
                <button
                  type="button"
                  onClick={() => downloadAttachment(note.id, attachment)}
                  className="flex min-h-11 min-w-0 flex-1 items-center justify-between gap-3 rounded-md px-2 text-left text-sm hover:bg-slate-50"
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
                {canUpload && (
                  <button
                    type="button"
                    disabled={pendingIds.has(`file:${attachment.id}`)}
                    onClick={() => void deleteAttachment(note.id, attachment)}
                    className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-slate-400 hover:bg-red-50 hover:text-red-600"
                    title="Удалить файл"
                    aria-label={`Удалить файл ${attachment.original_filename}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
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
        className={cn(
          'rounded-lg border border-slate-200 bg-white p-4 text-left transition hover:border-primary/30',
          isList ? 'flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between' : 'space-y-3'
        )}
      >
        <div className="flex min-w-0 items-start gap-2">
          {!share && <label className="flex h-11 w-11 shrink-0 items-center justify-center">
            <input className="h-4 w-4 shrink-0" type="checkbox" aria-label={`Выбрать заметку: ${note.title}`} checked={selectedNotes.includes(note.id)}
              disabled={selectedNotes.length >= 100 && !selectedNotes.includes(note.id)}
              onChange={event => setSelectedNotes(ids => event.target.checked ? [...ids, note.id] : ids.filter(id => id !== note.id))} />
          </label>}
          <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="min-w-0 break-words text-base font-semibold text-slate-900"><Link className="inline-block min-h-11 content-center hover:text-primary" to={`/quick-notes/${note.id}`}>{note.title}</Link></h2>
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
              <button type="button" onClick={() => promoteToTask(note)} disabled={pendingIds.has(note.id) || promotingNoteId === note.id} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-50" title="В личную задачу" aria-label="Создать личную задачу из заметки">
                <ListTodo className="h-4 w-4" />
              </button>
            </>
          )}
        </div>
      </article>
    )
  }

  const detailNote = detail && detail.note.id === noteId ? detail.note : undefined
  const detailIsOwner = Boolean(detail && !detail.share)
  const showEditorWarning = remoteUpdated || conflict !== null

  const renderLiveStatus = () => {
    if (!noteId) return null
    const label = liveStatusLabel[liveStatus]
    if (!label) return null
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600"
        aria-label={`Статус: ${label}${activeUsers > 0 ? `, активных: ${activeUsers}` : ''}`}
        role="status"
      >
        <span className={cn('inline-block h-2 w-2 rounded-full', liveStatusDot[liveStatus])} aria-hidden="true" />
        {label}
        {activeUsers > 0 && <span className="text-slate-400">· {activeUsers} онлайн</span>}
      </span>
    )
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      {!noteId && (
        <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Заметки</h1>
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
              disabled={activeGroup?.archived}
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
            Доступные мне
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
                aria-label="Поиск заметок"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="min-h-10 w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 lg:w-72"
                placeholder="Поиск"
              />
            </label>
          )}
        </div>
      </div>

      {activeTab === 'mine' && <>
        {groupError && <p role="alert" className="text-sm text-red-600">{groupError} <button type="button" onClick={() => void loadGroups()} className="min-h-11 underline">Повторить</button></p>}
        <NoteGroupsPanel groups={groups} view={groupView} onView={setGroupView} onChanged={reloadOrganization} onShare={groupId => setBulkShare({ groupId })} />
        {selectedNotes.length > 0 && <NoteBulkActions noteIds={selectedNotes} groups={groups} onChanged={reloadOrganization} onClear={() => setSelectedNotes([])} onShare={() => setBulkShare({ noteIds: selectedNotes })} />}
      </>}

      {activeTab === 'mine' ? (
        <section className={cn('grid gap-3', viewMode === 'preview' ? 'lg:grid-cols-2' : '')}>
          {loading && <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">Загрузка...</div>}
          {listError && <p role="alert">{listError} {notes.length > 0 && 'Показаны ранее загруженные данные.'} <button type="button" onClick={() => void loadNotes()}>Повторить</button></p>}
          {!loading && !listError && notes.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
              Заметок пока нет.
            </div>
          )}
          {activeGroup?.collapsed ? <button type="button" disabled={pendingIds.has(`group:${activeGroup.id}`)} className="min-h-11 text-left text-sm text-primary" onClick={async () => {
            if (!begin(`group:${activeGroup.id}`)) return
            try { await noteGroupsApi.update(activeGroup, { collapsed: false }); await loadGroups() }
            catch (error) { toast.error(error instanceof Error ? error.message : 'Не удалось развернуть группу') }
            finally { end(`group:${activeGroup.id}`) }
          }}>Развернуть: {activeGroup.title}</button> : loadedListScope === listScope && notes.map((note) => renderNoteCard(note))}
        </section>
      ) : (
        <section className={cn('grid gap-3', viewMode === 'preview' ? 'lg:grid-cols-2' : '')}>
          {sharedLoading && <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">Загрузка...</div>}
          {sharedError && <p role="alert">{sharedError} <button type="button" onClick={() => void loadSharedNotes()}>Повторить</button></p>}
          {!sharedLoading && !sharedError && sharedNotes.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
              Вам пока не открывали заметки.
            </div>
          )}
          {sharedNotes.map(({ share, note }) => renderNoteCard(note, share))}
        </section>
      )}
        </>
      )}

      {bulkShare && <NoteShareDialog {...bulkShare} onClose={() => setBulkShare(null)} onApplied={() => { setSelectedNotes([]); void reloadOrganization(); toast.success('Доступ открыт') }} />}

      {noteId && detailLoading && (
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-sm text-slate-500">Загрузка заметки...</div>
      )}
      {noteId && detailError && <div role="alert">{detailError} <button type="button" onClick={() => void loadNoteDetail(noteId)}>Повторить</button> <Link to="/quick-notes">К списку заметок</Link></div>}

      {noteModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
          onPointerDown={preventBackdropDismiss}
        >
          <div ref={notePanelRef} role="dialog" aria-modal="true" aria-label={editing ? 'Редактирование заметки' : 'Новая заметка'} tabIndex={-1} className="max-h-[92vh] w-full max-w-3xl overflow-auto rounded-xl border border-slate-200 bg-white p-4 shadow-2xl outline-none">
            <fieldset disabled={busy} className="min-w-0">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-base font-semibold text-slate-900">
                <FileText className="h-5 w-5 text-primary" />
                {editing ? 'Редактирование заметки' : 'Новая заметка'}
              </div>
              <button type="button" onClick={confirmDiscardOrClose} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" aria-label="Закрыть окно заметки">
                <X className="h-4 w-4" />
              </button>
            </div>
            {showEditorWarning && (
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" role="alert">
                <div className="font-medium">
                  {conflict ? 'Версия устарела' : 'Заметка обновлена с другого устройства'}
                </div>
                <div className="mt-0.5 text-xs text-amber-700">
                  {conflict?.message ?? 'В другой вкладке или на другом устройстве уже сохранена новая версия. Ваш текст сохранён локально.'}
                </div>
                <button
                  type="button"
                  onClick={loadFreshVersion}
                  className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-amber-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-amber-700"
                >
                  Загрузить актуальную версию
                </button>
              </div>
            )}
            <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_180px]">
              <input
                type="text"
                value={form.context}
                onChange={(event) => setForm((current) => ({ ...current, context: event.target.value }))}
                className="rounded-lg border border-slate-200 px-3 py-2 text-base outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
                placeholder="Контекст"
                maxLength={160}
              />
              <input
                type="text"
                value={form.tagsText}
                onChange={(event) => setForm((current) => ({ ...current, tagsText: event.target.value }))}
                className="rounded-lg border border-slate-200 px-3 py-2 text-base outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
                placeholder="Теги"
              />
            </div>
            <input
              type="text"
              value={form.title}
              onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
              className="mt-3 w-full rounded-lg border border-slate-200 px-3 py-2 text-base outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
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
              <button type="button" onClick={confirmDiscardOrClose} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">
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
            </fieldset>
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
                    <button type="button" onClick={() => promoteToTask(detailNote)} disabled={pendingIds.has(detailNote.id) || promotingNoteId === detailNote.id} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-50" title="В задачу" aria-label="Создать личную задачу из заметки">
                      <ListTodo className="h-4 w-4" />
                    </button>
                    <button type="button" disabled={pendingIds.has(detailNote.id)} onClick={() => updateStatus(detailNote, 'processed')} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-emerald-100 text-emerald-700 hover:bg-emerald-50" title="Разобрано" aria-label="Отметить заметку разобранной">
                      <CheckCircle2 className="h-4 w-4" />
                    </button>
                    <button type="button" disabled={pendingIds.has(detailNote.id)} onClick={() => updateStatus(detailNote, 'draft')} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" title="Черновик" aria-label="Вернуть заметку в черновики">
                      <RotateCcw className="h-4 w-4" />
                    </button>
                    <button type="button" disabled={pendingIds.has(detailNote.id)} onClick={() => updateStatus(detailNote, 'archived')} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50" title="Архив" aria-label="Перенести заметку в архив">
                      <Archive className="h-4 w-4" />
                    </button>
                    <button type="button" disabled={pendingIds.has(detailNote.id)} onClick={() => deleteNote(detailNote)} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-red-100 text-red-600 hover:bg-red-50" title="Удалить" aria-label="Удалить заметку">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {renderLiveStatus()}
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
                {detailIsOwner && <NoteContextLinks sourceType="note" sourceId={detailNote.id} />}
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

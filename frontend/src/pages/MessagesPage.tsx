import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  FileText,
  Inbox,
  Mail,
  MessageSquareText,
  Plus,
  Send,
  X,
} from 'lucide-react'
import { api } from '@/api/client'
import type {
  AttentionItem,
  Contact,
  MessageThread,
  MessageThreadDetail,
  QuickNote,
} from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { useAttention } from '@/contexts/attentionState'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'
import { cn } from '@/lib/utils'


type MessagesTab = 'direct' | 'important'

type ComposeForm = {
  recipientId: string
  subject: string
  body: string
  quickNoteId: string
}

const emptyCompose: ComposeForm = {
  recipientId: '',
  subject: '',
  body: '',
  quickNoteId: '',
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function otherContact(contact: Contact) {
  return contact.direction === 'incoming'
    ? {
        id: contact.requester_id,
        name: contact.requester_name,
        email: contact.requester_email,
      }
    : {
        id: contact.recipient_id,
        name: contact.recipient_name,
        email: contact.recipient_email,
      }
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function newRequestId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`
}

export function MessagesPage() {
  const { user } = useAuth()
  const { threadId } = useParams<{ threadId: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { summary, revision, refresh: refreshAttention } = useAttention()

  const [threads, setThreads] = useState<MessageThread[]>([])
  const [directItems, setDirectItems] = useState<AttentionItem[]>([])
  const [importantItems, setImportantItems] = useState<AttentionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [detail, setDetail] = useState<MessageThreadDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const [contacts, setContacts] = useState<Contact[]>([])
  const [ownedNotes, setOwnedNotes] = useState<QuickNote[]>([])
  const [optionsLoaded, setOptionsLoaded] = useState(false)
  const [composeOpen, setComposeOpen] = useState(false)
  const [compose, setCompose] = useState<ComposeForm>(emptyCompose)
  const [composeError, setComposeError] = useState('')
  const [composeBusy, setComposeBusy] = useState(false)
  const composeRequestId = useRef(newRequestId())
  const composeSubmitting = useRef(false)
  const composePanelRef = useProtectedModal<HTMLFormElement>(composeOpen)

  const [replyBody, setReplyBody] = useState('')
  const [replyNoteId, setReplyNoteId] = useState('')
  const [replyBusy, setReplyBusy] = useState(false)
  const [replyError, setReplyError] = useState('')
  const replyRequestId = useRef(newRequestId())
  const replySubmitting = useRef(false)

  const acceptedContacts = useMemo(
    () => contacts.filter((contact) => contact.status === 'accepted').map(otherContact),
    [contacts],
  )

  const availableNotes = useMemo(
    () => ownedNotes.filter((note) => note.status !== 'archived'),
    [ownedNotes],
  )

  const tab: MessagesTab = searchParams.get('tab') === 'important' ? 'important' : 'direct'

  const selectTab = (nextTab: MessagesTab) => {
    const next = new URLSearchParams(searchParams)
    if (nextTab === 'direct') next.delete('tab')
    else next.set('tab', nextTab)
    setSearchParams(next, { replace: true })
  }

  const loadOverview = useCallback(async () => {
    setLoadError('')
    try {
      const [nextThreads, nextDirect, nextImportant] = await Promise.all([
        api.get<MessageThread[]>('/api/messages/threads'),
        api.get<AttentionItem[]>('/api/messages/attention', {
          kind: 'direct',
          unread_only: 'true',
        }),
        api.get<AttentionItem[]>('/api/messages/attention', {
          kind: 'important',
          unread_only: 'true',
        }),
      ])
      setThreads(nextThreads)
      setDirectItems(nextDirect)
      setImportantItems(nextImportant)
    } catch (error) {
      setLoadError(errorText(error, 'Не удалось загрузить сообщения'))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadOptions = useCallback(async () => {
    if (optionsLoaded) return
    try {
      const [nextContacts, nextNotes] = await Promise.all([
        api.get<Contact[]>('/api/contacts'),
        api.get<QuickNote[]>('/api/quick-notes', { limit: '300' }),
      ])
      setContacts(nextContacts)
      setOwnedNotes(nextNotes)
      setOptionsLoaded(true)
    } catch (error) {
      setComposeError(errorText(error, 'Не удалось загрузить контакты и заметки'))
    }
  }, [optionsLoaded])

  const loadThread = useCallback(async (id: string) => {
    setDetailLoading(true)
    setReplyError('')
    try {
      const nextDetail = await api.get<MessageThreadDetail>(`/api/messages/threads/${id}`)
      setDetail(nextDetail)
      if (nextDetail.unread_count > 0) {
        await api.post(`/api/messages/threads/${id}/read`, {})
        setDetail((current) => current ? { ...current, unread_count: 0 } : current)
        await refreshAttention()
        void loadOverview()
      }
    } catch (error) {
      setReplyError(errorText(error, 'Не удалось открыть переписку'))
    } finally {
      setDetailLoading(false)
    }
  }, [loadOverview, refreshAttention])

  useEffect(() => {
    void loadOverview()
  }, [loadOverview, revision])

  useEffect(() => {
    if (threadId) {
      void loadThread(threadId)
      void loadOptions()
    } else {
      setDetail(null)
    }
  }, [loadOptions, loadThread, revision, threadId])

  const composeRecipient = searchParams.get('compose')
  useEffect(() => {
    if (!composeRecipient) return
    setCompose((current) => ({ ...current, recipientId: composeRecipient }))
    setComposeOpen(true)
    void loadOptions()
  }, [composeRecipient, loadOptions])

  const openCompose = () => {
    setCompose(emptyCompose)
    setComposeError('')
    composeRequestId.current = newRequestId()
    setComposeOpen(true)
    void loadOptions()
  }

  const closeCompose = () => {
    setComposeOpen(false)
    setComposeError('')
    setCompose(emptyCompose)
    const next = new URLSearchParams(searchParams)
    next.delete('compose')
    setSearchParams(next, { replace: true })
  }

  const markAttention = async (item: AttentionItem) => {
    try {
      await api.post(`/api/messages/attention/${item.id}/read`, {})
      if (item.kind === 'direct') {
        setDirectItems((items) => items.filter((candidate) => candidate.id !== item.id))
      } else {
        setImportantItems((items) => items.filter((candidate) => candidate.id !== item.id))
      }
      await refreshAttention()
      if (item.link?.startsWith('/')) navigate(item.link)
    } catch (error) {
      setLoadError(errorText(error, 'Не удалось отметить событие просмотренным'))
    }
  }

  const submitCompose = async (event: FormEvent) => {
    event.preventDefault()
    if (composeSubmitting.current) return
    const recipientId = compose.recipientId.trim()
    const subject = compose.subject.trim()
    const body = compose.body.trim()
    if (!recipientId || !subject || !body) {
      setComposeError('Укажите получателя, тему и текст письма')
      return
    }
    if (!acceptedContacts.some((contact) => contact.id === recipientId)) {
      setComposeError('Получатель должен быть принятым контактом')
      return
    }

    composeSubmitting.current = true
    setComposeBusy(true)
    setComposeError('')
    try {
      const created = await api.post<MessageThreadDetail>('/api/messages/threads', {
        recipient_id: recipientId,
        subject,
        body,
        quick_note_id: compose.quickNoteId || null,
        request_id: composeRequestId.current,
      })
      closeCompose()
      await Promise.all([loadOverview(), refreshAttention()])
      navigate(`/messages/${created.id}`)
    } catch (error) {
      setComposeError(errorText(error, 'Не удалось отправить письмо'))
    } finally {
      composeSubmitting.current = false
      setComposeBusy(false)
    }
  }

  const submitReply = async (event: FormEvent) => {
    event.preventDefault()
    if (!detail || replySubmitting.current) return
    const body = replyBody.trim()
    if (!body) {
      setReplyError('Введите текст ответа')
      return
    }

    replySubmitting.current = true
    setReplyBusy(true)
    setReplyError('')
    try {
      await api.post(`/api/messages/threads/${detail.id}/posts`, {
        body,
        quick_note_id: replyNoteId || null,
        request_id: replyRequestId.current,
      })
      setReplyBody('')
      setReplyNoteId('')
      replyRequestId.current = newRequestId()
      await Promise.all([
        loadThread(detail.id),
        loadOverview(),
        refreshAttention(),
      ])
    } catch (error) {
      setReplyError(errorText(error, 'Не удалось отправить ответ'))
    } finally {
      replySubmitting.current = false
      setReplyBusy(false)
    }
  }

  const otherParticipants = (thread: MessageThread) =>
    thread.participants.filter((participant) => participant.user_id !== user?.id)

  const canReply = detail
    ? otherParticipants(detail).every((participant) =>
        acceptedContacts.some((contact) => contact.id === participant.user_id),
      )
    : false

  const renderAttentionItem = (item: AttentionItem, variant: 'row' | 'card' = 'card') => (
    <button
      key={item.id}
      type="button"
      onClick={() => void markAttention(item)}
      className={cn(
        'group w-full p-3 text-left transition focus:outline-none focus:ring-2 focus:ring-inset focus:ring-accent/30',
        variant === 'row'
          ? 'border-b border-slate-200 bg-slate-50 last:border-b-0 hover:bg-slate-100'
          : 'rounded-lg border border-slate-200 bg-white hover:border-primary/35 hover:bg-slate-50',
      )}
    >
      <span className="flex items-start gap-3">
        <span
          className={cn(
            'mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
            item.kind === 'direct'
              ? 'bg-rose-50 text-rose-600'
              : 'bg-emerald-50 text-emerald-700',
          )}
        >
          {item.kind === 'direct' ? (
            <MessageSquareText className="h-4 w-4" />
          ) : (
            <AlertCircle className="h-4 w-4" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-start justify-between gap-2">
            <span className="line-clamp-2 text-sm font-semibold text-slate-900">
              {item.title}
            </span>
            <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-400 transition group-hover:translate-x-0.5" />
          </span>
          {item.body && (
            <span className="mt-1 line-clamp-2 block text-sm text-slate-600">
              {item.body}
            </span>
          )}
          <span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-400">
            {item.actor_name && <span>{item.actor_name}</span>}
            <span>{formatDate(item.updated_at)}</span>
          </span>
        </span>
      </span>
    </button>
  )

  const renderThreadRow = (thread: MessageThread) => {
    const people = otherParticipants(thread)
    const active = thread.id === threadId
    return (
      <Link
        key={thread.id}
        to={`/messages/${thread.id}`}
        className={cn(
          'block w-full border-b border-slate-100 px-3 py-3 text-left transition last:border-b-0 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/30',
          active && 'bg-primary/5',
        )}
      >
        <span className="flex items-start gap-2">
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2">
              <span className={cn('truncate text-sm text-slate-900', thread.unread_count > 0 && 'font-semibold')}>
                {thread.subject}
              </span>
              {thread.unread_count > 0 && (
                <span className="inline-flex min-w-5 shrink-0 items-center justify-center rounded-full bg-rose-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                  {thread.unread_count > 99 ? '99+' : thread.unread_count}
                </span>
              )}
            </span>
            <span className="mt-1 block truncate text-xs text-slate-500">
              {people.map((person) => person.full_name).join(', ') || 'Переписка'}
            </span>
            <span className="mt-1 line-clamp-2 block text-sm text-slate-600">
              {thread.last_post_preview}
            </span>
          </span>
          <span className="shrink-0 text-[11px] text-slate-400">
            {formatDate(thread.last_post_at)}
          </span>
        </span>
      </Link>
    )
  }

  const threadPanel = detailLoading ? (
    <div className="flex min-h-[360px] items-center justify-center text-sm text-slate-500">
      Загрузка переписки…
    </div>
  ) : detail ? (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="border-b border-slate-200 px-4 py-3 sm:px-5">
        <div className="flex items-start gap-3">
          <Link
            to="/messages"
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 lg:hidden"
            aria-label="Назад к списку сообщений"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-semibold text-slate-900">{detail.subject}</h2>
            <p className="mt-0.5 truncate text-xs text-slate-500">
              {otherParticipants(detail).map((person) => `${person.full_name} · ${person.email}`).join(', ')}
            </p>
          </div>
        </div>
      </header>

      <div className="min-h-[280px] flex-1 space-y-3 overflow-y-auto bg-slate-50 p-4 sm:p-5">
        {detail.posts.map((post) => {
          const mine = post.author_id === user?.id
          return (
            <article
              key={post.id}
              className={cn(
                'rounded-lg border bg-white p-3 shadow-sm',
                mine ? 'border-primary/25' : 'border-slate-200',
              )}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <span className="text-sm font-semibold text-slate-900">
                    {mine ? 'Вы' : post.author_name}
                  </span>
                  <span className="ml-2 text-xs text-slate-400">{post.author_email}</span>
                </div>
                <time className="text-xs text-slate-400" dateTime={post.created_at}>
                  {formatDate(post.created_at)}
                </time>
              </div>
              <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
                {post.body}
              </p>
              {post.quick_note_id && post.quick_note_available && (
                <Link
                  to={`/quick-notes/${post.quick_note_id}`}
                  className="mt-3 inline-flex max-w-full items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-primary hover:border-primary/30"
                >
                  <FileText className="h-4 w-4 shrink-0" />
                  <span className="truncate">{post.quick_note_title || 'Открыть заметку'}</span>
                </Link>
              )}
            </article>
          )
        })}
      </div>

      <form onSubmit={submitReply} className="border-t border-slate-200 p-4 sm:p-5">
        {!canReply ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Контакт больше не активен. История переписки доступна только для чтения.
          </div>
        ) : (
          <>
            <textarea
              name="reply_body"
              value={replyBody}
              onChange={(event) => setReplyBody(event.target.value)}
              rows={3}
              maxLength={20_000}
              className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-base leading-6 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
              placeholder="Введите ответ…"
              aria-label="Текст ответа"
              autoComplete="off"
            />
            <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <label className="min-w-0 flex-1 sm:max-w-sm">
                <span className="sr-only">Приложить заметку</span>
                <select
                  name="reply_quick_note_id"
                  value={replyNoteId}
                  onChange={(event) => setReplyNoteId(event.target.value)}
                  className="min-h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
                  autoComplete="off"
                >
                  <option value="">Без заметки</option>
                  {availableNotes.map((note) => (
                    <option key={note.id} value={note.id}>{note.title || 'Без названия'}</option>
                  ))}
                </select>
              </label>
              <button
                type="submit"
                disabled={replyBusy || !replyBody.trim()}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
                {replyBusy ? 'Отправка…' : 'Отправить'}
              </button>
            </div>
          </>
        )}
        {replyError && <p className="mt-2 text-sm text-rose-600" role="alert">{replyError}</p>}
      </form>
    </div>
  ) : (
    <div className="flex min-h-[420px] flex-col items-center justify-center p-8 text-center">
      <span className="inline-flex h-12 w-12 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
        <Mail className="h-6 w-6" />
      </span>
      <h2 className="mt-3 text-base font-semibold text-slate-900">Выберите переписку</h2>
      <p className="mt-1 max-w-sm text-sm text-slate-500">
        Здесь откроется выбранная предметная переписка.
      </p>
    </div>
  )

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Сообщения</h1>
          <p className="mt-1 text-sm text-slate-500">Обращения коллег и важные события системы</p>
        </div>
        <button
          type="button"
          onClick={openCompose}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          <Plus className="h-4 w-4" />
          Новое письмо
        </button>
      </div>

      <div
        className="flex w-full gap-1 overflow-x-auto rounded-lg border border-slate-200 bg-white p-1 sm:w-fit"
        role="tablist"
        aria-label="Категории сообщений"
      >
        <button
          type="button"
          onClick={() => selectTab('direct')}
          role="tab"
          aria-selected={tab === 'direct'}
          className={cn(
            'inline-flex min-h-11 flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-md px-4 text-sm font-medium transition sm:flex-none',
            tab === 'direct' ? 'bg-primary text-primary-foreground' : 'text-slate-600 hover:bg-slate-50',
          )}
        >
          <MessageSquareText className="h-4 w-4" />
          Обращения
          {summary.direct_count > 0 && (
            <span className={cn('rounded-full px-1.5 py-0.5 text-[10px] font-semibold', tab === 'direct' ? 'bg-white/20 text-white' : 'bg-rose-100 text-rose-700')}>
              {summary.direct_count}
            </span>
          )}
        </button>
        <button
          type="button"
          onClick={() => selectTab('important')}
          role="tab"
          aria-selected={tab === 'important'}
          className={cn(
            'inline-flex min-h-11 flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-md px-4 text-sm font-medium transition sm:flex-none',
            tab === 'important' ? 'bg-primary text-primary-foreground' : 'text-slate-600 hover:bg-slate-50',
          )}
        >
          <CheckCircle2 className="h-4 w-4" />
          Важное
          {summary.important_count > 0 && (
            <span className={cn('rounded-full px-1.5 py-0.5 text-[10px] font-semibold', tab === 'important' ? 'bg-white/20 text-white' : 'bg-emerald-100 text-emerald-800')}>
              {summary.important_count}
            </span>
          )}
        </button>
      </div>

      {loadError && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
          {loadError}
        </div>
      )}

      {tab === 'direct' ? (
        <section
          className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm lg:grid lg:min-h-[620px] lg:grid-cols-[360px_minmax(0,1fr)]"
          role="tabpanel"
        >
          <div className={cn('border-slate-200 lg:border-r', threadId && 'hidden lg:block')}>
            <div className="border-b border-slate-200 px-4 py-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                <Inbox className="h-4 w-4 text-primary" />
                Входящие
              </div>
            </div>
            <div className="max-h-[620px] overflow-y-auto">
              {loading ? (
                <div className="p-5 text-sm text-slate-500">Загрузка…</div>
              ) : (
                <>
                  {directItems.length > 0 && (
                    <div className="border-b border-slate-200 bg-slate-50">
                      <div className="px-3 pb-1 pt-2 text-[11px] font-medium uppercase text-slate-400">
                        Требуют внимания
                      </div>
                      {directItems.map((item) => renderAttentionItem(item, 'row'))}
                    </div>
                  )}
                  {threads.length > 0 ? (
                    threads.map(renderThreadRow)
                  ) : directItems.length === 0 ? (
                    <div className="p-8 text-center text-sm text-slate-500">
                      Новых обращений и переписок пока нет.
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </div>
          <div className={cn('min-w-0', !threadId && 'hidden lg:flex lg:flex-col')}>
            {threadPanel}
          </div>
        </section>
      ) : (
        <section role="tabpanel">
          <div className="mb-3 flex items-center gap-2 px-1 text-sm font-semibold text-slate-800">
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            Непросмотренные важные события
          </div>
          {loading ? (
            <div className="p-5 text-sm text-slate-500">Загрузка…</div>
          ) : importantItems.length > 0 ? (
            <div className="grid gap-2 lg:grid-cols-2">
              {importantItems.map((item) => renderAttentionItem(item))}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
              Важных непросмотренных событий нет.
            </div>
          )}
        </section>
      )}

      {composeOpen && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4"
          onPointerDown={preventBackdropDismiss}
          role="dialog"
          aria-modal="true"
          aria-labelledby="compose-title"
        >
          <form
            ref={composePanelRef}
            tabIndex={-1}
            onSubmit={submitCompose}
            className="max-h-[92vh] w-full overscroll-contain overflow-y-auto rounded-t-xl border border-slate-200 bg-white p-4 shadow-2xl outline-none sm:max-w-2xl sm:rounded-xl sm:p-5"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Mail className="h-5 w-5 text-primary" />
                <h2 id="compose-title" className="text-base font-semibold text-slate-900">Новое письмо</h2>
              </div>
              <button
                type="button"
                onClick={closeCompose}
                className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 sm:h-9 sm:w-9"
                aria-label="Закрыть окно"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-600">Получатель</span>
                <select
                  name="recipient_id"
                  value={compose.recipientId}
                  onChange={(event) => setCompose((current) => ({ ...current, recipientId: event.target.value }))}
                  className="min-h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-base outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
                  autoComplete="off"
                  required
                >
                  <option value="">Выберите контакт</option>
                  {acceptedContacts.map((contact) => (
                    <option key={contact.id} value={contact.id}>{contact.name} · {contact.email}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-600">Тема</span>
                <input
                  name="subject"
                  value={compose.subject}
                  onChange={(event) => setCompose((current) => ({ ...current, subject: event.target.value }))}
                  maxLength={180}
                  className="min-h-11 w-full rounded-lg border border-slate-200 px-3 text-base outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
                  placeholder="Например, согласование материалов…"
                  autoComplete="off"
                  required
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-600">Текст</span>
                <textarea
                  name="body"
                  value={compose.body}
                  onChange={(event) => setCompose((current) => ({ ...current, body: event.target.value }))}
                  rows={7}
                  maxLength={20_000}
                  className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-base leading-6 outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
                  placeholder="Введите сообщение…"
                  autoComplete="off"
                  required
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-600">Заметка</span>
                <select
                  name="quick_note_id"
                  value={compose.quickNoteId}
                  onChange={(event) => setCompose((current) => ({ ...current, quickNoteId: event.target.value }))}
                  className="min-h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-base outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
                  autoComplete="off"
                >
                  <option value="">Без заметки</option>
                  {availableNotes.map((note) => (
                    <option key={note.id} value={note.id}>{note.title || 'Без названия'}</option>
                  ))}
                </select>
              </label>
            </div>

            {composeError && <p className="mt-3 text-sm text-rose-600" role="alert">{composeError}</p>}
            {!optionsLoaded && !composeError && (
              <p className="mt-3 text-sm text-slate-500">Загрузка контактов и заметок…</p>
            )}

            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={closeCompose}
                className="inline-flex min-h-11 items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={composeBusy || !optionsLoaded}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
                {composeBusy ? 'Отправка…' : 'Отправить'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}

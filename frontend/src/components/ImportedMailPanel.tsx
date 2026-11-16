import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, CalendarDays, ChevronLeft, ChevronRight, Download, Loader2, Mail, MailCheck, Paperclip, RefreshCw, Repeat } from 'lucide-react'
import { ApiError } from '@/api/client'
import { mailImport, type ImportedMailAttachment, type ImportedMailItem, type ImportedMailKind, type ImportedMailList } from '@/api/mailImport'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 50
const MAX_FILE_BYTES = 10 * 1024 * 1024
const MAX_MESSAGE_BYTES = 20 * 1024 * 1024
const actionClass = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800'
const iconClass = `${actionClass} h-11 w-11 shrink-0 p-2`
const meetingLabels = { invited: 'Приглашение', updated: 'Встреча обновлена', cancelled: 'Встреча отменена', response: 'Ответ на приглашение' }

function date(value: string | null, allDay = false) {
  if (!value) return 'Не указано'
  const parsed = new Date(value)
  return allDay ? parsed.toLocaleDateString('ru-RU') : parsed.toLocaleString('ru-RU')
}

function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} Б`
  const unit = bytes < 1024 * 1024 ? 1024 : 1024 * 1024
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(bytes / unit)} ${unit === 1024 ? 'КиБ' : 'МиБ'}`
}

function downloadName(filename: string) {
  return Array.from(filename, character => {
    const code = character.charCodeAt(0)
    return code < 32 || code === 127 || (code >= 0x202a && code <= 0x202e) || (code >= 0x2066 && code <= 0x2069) || '<>:"/\\|?*'.includes(character) ? '_' : character
  }).join('').replace(/^\.+/, '').trim() || 'attachment'
}

function MeetingState({ item }: { item: ImportedMailItem }) {
  if (item.kind !== 'meeting') return null
  return <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
    <span className={item.meeting_status === 'cancelled' ? 'text-red-700 dark:text-red-300' : 'text-slate-600 dark:text-slate-400'}>{item.meeting_status ? meetingLabels[item.meeting_status] : 'Встреча'}</span>
    {item.is_recurring && <span className="inline-flex items-center gap-1"><Repeat aria-hidden="true" className="h-3 w-3" />Серия встреч</span>}
  </span>
}

export function ImportedMailPanel({ onUnreadCountChange }: { onUnreadCountChange: (count: number | null) => void }) {
  const [params, setParams] = useSearchParams()
  const setParamsRef = useRef(setParams)
  setParamsRef.current = setParams
  const kindParam = params.get('mail_kind')
  const kind: ImportedMailKind | undefined = kindParam === 'mail' || kindParam === 'meeting' ? kindParam : undefined
  const unreadOnly = params.get('mail_unread') === 'true'
  const rawOffset = Number(params.get('mail_offset') ?? 0)
  const offset = Number.isSafeInteger(rawOffset) && rawOffset >= 0 && rawOffset <= 2_147_483_647 ? Math.floor(rawOffset / PAGE_SIZE) * PAGE_SIZE : 0
  const selectedId = params.get('mail_item') || null
  const [list, setList] = useState<ImportedMailList | null>(null)
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [detail, setDetail] = useState<ImportedMailItem | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [readError, setReadError] = useState('')
  const [readBusy, setReadBusy] = useState(false)
  const [reload, setReload] = useState(0)
  const [detailReload, setDetailReload] = useState(0)
  const [countError, setCountError] = useState(false)
  const [downloads, setDownloads] = useState<Record<string, { pending: boolean; error?: string; complete?: boolean }>>({})
  const pendingDownloads = useRef(new Set<string>())
  const downloadUrls = useRef(new Map<string, number>())
  const mutation = useRef(false)
  const mounted = useRef(true)
  const selection = useRef(selectedId)
  selection.current = selectedId
  const detailRequest = useRef(0)
  const heading = useRef<HTMLHeadingElement>(null)
  const listHeading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    mounted.current = true
    const urls = downloadUrls.current
    return () => {
      mounted.current = false
      detailRequest.current += 1
      urls.forEach((timer, url) => { window.clearTimeout(timer); URL.revokeObjectURL(url) })
      urls.clear()
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setListError('')
    void mailImport.items({ kind, unreadOnly, offset, limit: PAGE_SIZE }).then(result => {
      if (cancelled) return
      if (offset > 0 && offset >= result.total) {
        // Keep the last valid page after a read removes its final unread item.
        setParamsRef.current(current => {
          const next = new URLSearchParams(current)
          const lastOffset = Math.floor(Math.max(0, result.total - 1) / PAGE_SIZE) * PAGE_SIZE
          if (lastOffset) next.set('mail_offset', String(lastOffset))
          else next.delete('mail_offset')
          return next
        }, { replace: true })
      } else {
        setList(result)
      }
    }).catch(() => {
      if (!cancelled) setListError('Не удалось загрузить почту и встречи. Повторите загрузку.')
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [kind, unreadOnly, offset, reload])

  useEffect(() => {
    let cancelled = false
    setCountError(false)
    onUnreadCountChange(null)
    // This count is independent of list filters and the Direct/Important summary.
    void mailImport.items({ limit: 1 }).then(result => {
      if (!cancelled) onUnreadCountChange(result.unread_count)
    }).catch(() => {
      if (!cancelled) { onUnreadCountChange(null); setCountError(true) }
    })
    return () => { cancelled = true }
  }, [reload, onUnreadCountChange])

  useEffect(() => {
    const request = ++detailRequest.current
    setDetail(null)
    setDetailError('')
    setReadError('')
    setDownloads({})
    if (!selectedId) { setDetailLoading(false); return }
    setDetailLoading(true)
    heading.current?.focus()
    void mailImport.item(selectedId).then(result => {
      if (!mounted.current || request !== detailRequest.current) return
      if (result.id !== selectedId) throw new Error('Unexpected item')
      setDetail(result)
    }).catch(() => {
      if (mounted.current && request === detailRequest.current) setDetailError('Не удалось открыть запись. Повторите загрузку.')
    }).finally(() => {
      if (mounted.current && request === detailRequest.current) setDetailLoading(false)
    })
    return () => { detailRequest.current += 1 }
  }, [selectedId, detailReload])

  const updateParams = (changes: Record<string, string | null>) => {
    setParams(current => {
      const next = new URLSearchParams(current)
      for (const [name, value] of Object.entries(changes)) {
        if (value === null) next.delete(name)
        else next.set(name, value)
      }
      return next
    })
  }

  const toggleRead = async () => {
    if (!detail || detail.id !== selectedId || mutation.current) return
    const currentId = detail.id
    const request = detailRequest.current
    mutation.current = true
    setReadBusy(true)
    setReadError('')
    try {
      const result = await mailImport.setRead(currentId, !detail.is_read)
      if (!mounted.current) return
      if (result.id !== currentId) throw new Error('Unexpected item')
      if (selection.current === currentId && detailRequest.current === request) setDetail(result)
      setReload(current => current + 1)
    } catch {
      if (mounted.current && selection.current === currentId && detailRequest.current === request) setReadError('Не удалось изменить статус DPMS. Повторите действие.')
    } finally {
      mutation.current = false
      if (mounted.current) setReadBusy(false)
    }
  }

  const refresh = () => { setReload(current => current + 1); setDetailReload(current => current + 1) }
  const currentDetail = detail?.id === selectedId ? detail : null
  const attachments = currentDetail?.attachments ?? []

  const download = async (attachment: ImportedMailAttachment) => {
    if (!currentDetail || attachment.byte_length > MAX_FILE_BYTES) return
    const itemId = currentDetail.id
    const request = detailRequest.current
    const downloadId = `${itemId}/${attachment.id}`
    if (pendingDownloads.current.has(downloadId)) return
    pendingDownloads.current.add(downloadId)
    setDownloads(current => ({ ...current, [attachment.id]: { pending: true } }))
    const current = () => mounted.current && selection.current === itemId && detailRequest.current === request
    const fail = (message: string) => {
      if (current()) setDownloads(previous => ({ ...previous, [attachment.id]: { pending: false, error: message } }))
    }
    try {
      const blob = await mailImport.attachment(itemId, attachment.id)
      if (!current()) return
      if (blob.size !== attachment.byte_length || blob.size > MAX_FILE_BYTES) {
        fail('Размер вложения не совпадает. Файл не скачан.')
        return
      }
      const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
      const sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
      if (!current()) return
      if (sha256 !== attachment.sha256.toLowerCase()) {
        fail('Контрольная сумма вложения не совпадает. Файл не скачан.')
        return
      }
      // Never open imported content inline, even when its declared MIME is HTML.
      const url = URL.createObjectURL(new Blob([blob], { type: 'application/octet-stream' }))
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = downloadName(attachment.filename)
      document.body.appendChild(anchor)
      try {
        anchor.click()
      } finally {
        anchor.remove()
        const timer = window.setTimeout(() => {
          URL.revokeObjectURL(url)
          downloadUrls.current.delete(url)
        }, 1000)
        downloadUrls.current.set(url, timer)
      }
      if (current()) setDownloads(previous => ({ ...previous, [attachment.id]: { pending: false, complete: true } }))
    } catch (error) {
      fail(error instanceof ApiError && (error.status === 403 || error.status === 404)
        ? 'Нет доступа к вложению или файл недоступен.'
        : error instanceof ApiError && error.status === 413
          ? 'Превышен лимит размера вложения. Файл не скачан.'
          : 'Не удалось скачать вложение. Повторите загрузку.')
    } finally {
      pendingDownloads.current.delete(downloadId)
    }
  }

  return <section role="tabpanel" id="imported-mail-panel" aria-label="Почта и встречи" className="min-w-0 text-slate-900 dark:text-slate-100">
    <div className="flex flex-wrap items-end gap-3 border-b border-slate-200 pb-3 dark:border-slate-700">
      <label className="min-w-0 text-sm">Тип записи
        <select aria-label="Тип записи" value={kind || 'all'} disabled={readBusy} onChange={event => updateParams({ mail_kind: event.target.value === 'all' ? null : event.target.value, mail_offset: null, mail_item: null })} className="mt-1 block min-h-11 max-w-full rounded-md border border-slate-300 bg-white px-3 text-base dark:border-slate-600 dark:bg-slate-900">
          <option value="all">Все записи</option><option value="mail">Письма</option><option value="meeting">Встречи</option>
        </select>
      </label>
      <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={unreadOnly} disabled={readBusy} onChange={event => updateParams({ mail_unread: event.target.checked ? 'true' : null, mail_offset: null, mail_item: null })} className="h-4 w-4" />Непрочитанные в DPMS</label>
      <button type="button" className={`${iconClass} ml-auto`} title="Обновить почту и встречи" aria-label="Обновить почту и встречи" disabled={loading || detailLoading || readBusy} onClick={refresh}><RefreshCw aria-hidden="true" className="h-4 w-4" /></button>
    </div>
    {countError && <p role="status" className="py-2 text-sm text-amber-800 dark:text-amber-300">Счётчик непрочитанных недоступен.<button type="button" className={`${actionClass} ml-2`} onClick={() => setReload(current => current + 1)} disabled={loading || readBusy}>Повторить</button></p>}
    <div className="min-w-0 lg:grid lg:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.2fr)]">
      <div className={cn('min-w-0 border-slate-200 lg:border-r dark:border-slate-700', selectedId && 'hidden lg:block')}>
        <h2 ref={listHeading} tabIndex={-1} className="py-3 text-sm font-semibold outline-none">Входящие Outlook</h2>
        {loading ? <p role="status" className="py-5 text-sm">Загрузка записей…</p> : listError ? <div role="alert" className="py-4 text-sm text-red-600 dark:text-red-400"><p>{listError}</p><button type="button" className={`${actionClass} mt-2`} onClick={() => setReload(current => current + 1)}>Повторить загрузку</button></div> : list?.items.length ? <ul aria-label="Импортированные записи" className="divide-y divide-slate-200 dark:divide-slate-700">
          {list.items.map(item => <li key={item.id}>
            <button type="button" aria-current={selectedId === item.id ? 'true' : undefined} disabled={readBusy} onClick={() => updateParams({ mail_item: item.id })} className={cn('flex w-full min-w-0 gap-3 px-2 py-3 text-left hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-50 dark:hover:bg-slate-800', selectedId === item.id && 'bg-primary/10')}>
              {item.kind === 'meeting' ? <CalendarDays aria-hidden="true" className="mt-1 h-4 w-4 shrink-0" /> : <Mail aria-hidden="true" className="mt-1 h-4 w-4 shrink-0" />}
              <span className="min-w-0 flex-1 space-y-1 break-words [overflow-wrap:anywhere]">
                <span className={cn('block text-sm', !item.is_read && 'font-semibold')}>{item.subject || '(Без темы)'}</span>
                <span className="block text-xs text-slate-600 dark:text-slate-400">{item.sender_name || item.sender_address || 'Отправитель не указан'}</span>
                <span className="block text-xs tabular-nums text-slate-500 dark:text-slate-400">{date(item.received_at)}</span>
                <span className="block text-xs">{item.is_read ? 'Прочитано в DPMS' : 'Не прочитано в DPMS'}</span>
                <MeetingState item={item} />
              </span>
            </button>
          </li>)}
        </ul> : <div className="py-6 text-sm text-slate-600 dark:text-slate-400"><p>{kind || unreadOnly ? 'Нет записей по выбранным фильтрам.' : 'Импортированных писем и встреч пока нет.'}</p><Link to="/settings" className="mt-2 inline-flex min-h-11 items-center text-primary underline">Подключения Outlook</Link></div>}
        <nav aria-label="Страницы импортированной почты" className="flex items-center justify-between gap-2 border-t border-slate-200 py-3 lg:pr-3 dark:border-slate-700">
          <button type="button" className={iconClass} title="Предыдущая страница" aria-label="Предыдущая страница" disabled={loading || readBusy || offset === 0} onClick={() => updateParams({ mail_offset: offset === PAGE_SIZE ? null : String(offset - PAGE_SIZE), mail_item: null })}><ChevronLeft aria-hidden="true" className="h-4 w-4" /></button>
          <span className="text-center text-xs tabular-nums" role="status">{loading || listError || !list ? '…' : `Страница ${offset / PAGE_SIZE + 1} из ${Math.max(1, Math.ceil(list.total / PAGE_SIZE))} · ${list.total} записей`}</span>
          <button type="button" className={iconClass} title="Следующая страница" aria-label="Следующая страница" disabled={loading || readBusy || Boolean(listError) || !list || offset + PAGE_SIZE >= list.total} onClick={() => updateParams({ mail_offset: String(offset + PAGE_SIZE), mail_item: null })}><ChevronRight aria-hidden="true" className="h-4 w-4" /></button>
        </nav>
      </div>
      <div className={cn('min-w-0 py-3 lg:pl-5', !selectedId && 'hidden lg:block')}>
        {selectedId ? <>
          <button type="button" className={actionClass} onClick={() => { updateParams({ mail_item: null }); window.requestAnimationFrame(() => listHeading.current?.focus()) }}><ArrowLeft aria-hidden="true" className="h-4 w-4" />К списку</button>
          <h2 ref={heading} tabIndex={-1} className="mt-4 break-words text-lg font-semibold outline-none [overflow-wrap:anywhere]">{currentDetail?.subject || (currentDetail ? '(Без темы)' : 'Запись Outlook')}</h2>
          {detailLoading ? <p role="status" className="py-4 text-sm">Загрузка записи…</p> : detailError ? <div role="alert" className="py-4 text-sm text-red-600 dark:text-red-400"><p>{detailError}</p><button type="button" className={`${actionClass} mt-2`} onClick={() => setDetailReload(current => current + 1)}>Повторить открытие</button></div> : currentDetail && <article aria-label="Содержимое записи" className="mt-3 min-w-0 space-y-4 break-words [overflow-wrap:anywhere]">
            <MeetingState item={currentDetail} />
            <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
              <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Отправитель</dt><dd>{currentDetail.sender_name || 'Не указан'}{currentDetail.sender_address && <span className="block">{currentDetail.sender_address}</span>}</dd></div>
              <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Источник</dt><dd>Outlook Inbox · {currentDetail.mailbox_label || 'Почтовый ящик'}</dd></div>
              <div className="min-w-0 sm:col-span-2"><dt className="text-slate-500 dark:text-slate-400">Кому</dt><dd>{currentDetail.to_recipients || 'Не указано'}</dd></div>
              {currentDetail.cc_recipients && <div className="min-w-0 sm:col-span-2"><dt className="text-slate-500 dark:text-slate-400">Копия</dt><dd>{currentDetail.cc_recipients}</dd></div>}
              <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Получено</dt><dd className="tabular-nums">{date(currentDetail.received_at)}</dd></div>
              <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Изменено в Outlook</dt><dd className="tabular-nums">{date(currentDetail.source_modified_at)}</dd></div>
              <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Обновлено в DPMS</dt><dd className="tabular-nums">{date(currentDetail.updated_at)}</dd></div>
              {currentDetail.kind === 'meeting' && <>
                <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Время встречи{currentDetail.all_day ? ' · Весь день' : ''}</dt><dd className="tabular-nums">{currentDetail.starts_at && currentDetail.ends_at ? `${date(currentDetail.starts_at, currentDetail.all_day)} – ${date(currentDetail.ends_at, currentDetail.all_day)}` : 'Не указано'}</dd></div>
                <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Место</dt><dd>{currentDetail.location || 'Не указано'}</dd></div>
              </>}
              <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Прочтение в Outlook</dt><dd>{currentDetail.source_is_read ? 'Прочитано в Outlook' : 'Не прочитано в Outlook'}</dd></div>
              <div className="min-w-0"><dt className="text-slate-500 dark:text-slate-400">Прочтение в DPMS</dt><dd>{currentDetail.is_read ? 'Прочитано в DPMS' : 'Не прочитано в DPMS'}</dd></div>
            </dl>
            <button type="button" className={actionClass} disabled={readBusy} onClick={() => void toggleRead()}><MailCheck aria-hidden="true" className="h-4 w-4 shrink-0" />{readBusy ? 'Сохранение…' : currentDetail.is_read ? 'Отметить непрочитанным в DPMS' : 'Отметить прочитанным в DPMS'}</button>
            {readError && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{readError}</p>}
            <div className="border-t border-slate-200 pt-4 dark:border-slate-700">
              <h3 className="mb-2 text-sm font-medium">Текст</h3>
              {currentDetail.body_text === null ? <p className="text-sm text-slate-500 dark:text-slate-400">Текст не передан.</p> : currentDetail.body_text === '' ? <p className="text-sm text-slate-500 dark:text-slate-400">Пустой текст.</p> : <p data-testid="imported-mail-body" className="whitespace-pre-wrap break-words text-sm leading-relaxed [overflow-wrap:anywhere]">{currentDetail.body_text}</p>}
            </div>
            <section aria-label="Вложения" className="border-t border-slate-200 pt-4 dark:border-slate-700">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-medium"><Paperclip aria-hidden="true" className="h-4 w-4" />Вложения · {attachments.length}</h3>
              {attachments.reduce((sum, attachment) => sum + attachment.byte_length, 0) > MAX_MESSAGE_BYTES && <p role="alert" className="mb-3 flex items-start gap-2 text-sm text-amber-800 dark:text-amber-300"><AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />Превышен лимит 20 МиБ вложений на письмо. Полнота передачи не подтверждена.</p>}
              {attachments.length === 0 ? <p className="text-sm text-slate-500 dark:text-slate-400">Вложения не переданы.</p> : <ul className="divide-y divide-slate-200 dark:divide-slate-700">
                {attachments.map(attachment => {
                  const state = downloads[attachment.id]
                  const oversized = attachment.byte_length > MAX_FILE_BYTES
                  return <li key={attachment.id} className="min-w-0 py-2">
                    <div className="flex min-w-0 items-start gap-2">
                      <Paperclip aria-hidden="true" className="mt-3 h-4 w-4 shrink-0" />
                      <div className="min-w-0 flex-1 text-sm"><p className="break-words [overflow-wrap:anywhere]">{attachment.filename || 'Без имени'}</p><p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{fileSize(attachment.byte_length)}{attachment.is_inline ? ' · Встроенное вложение' : ''}</p></div>
                      <button type="button" className={iconClass} title={`Скачать ${attachment.filename}`} aria-label={`Скачать ${attachment.filename}`} disabled={state?.pending || oversized} onClick={() => void download(attachment)}>{state?.pending ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Download aria-hidden="true" className="h-4 w-4" />}</button>
                    </div>
                    {oversized && <p role="alert" className="mt-1 text-sm text-amber-800 dark:text-amber-300">Файл превышает лимит 10 МиБ. Передача не подтверждена.</p>}
                    {state?.pending && <p role="status" className="mt-1 text-xs">Загрузка вложения…</p>}
                    {state?.complete && <p role="status" className="mt-1 text-xs">Файл передан браузеру.</p>}
                    {state?.error && <p role="alert" className="mt-1 text-sm text-red-600 dark:text-red-400">{state.error}</p>}
                  </li>
                })}
              </ul>}
            </section>
          </article>}
        </> : <p className="py-6 text-sm text-slate-500 dark:text-slate-400">Запись не выбрана.</p>}
      </div>
    </div>
  </section>
}

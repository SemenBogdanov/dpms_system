import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { AlertTriangle, Check, Copy, Loader2, Monitor, Plus, RefreshCw, Unplug, X } from 'lucide-react'
import { mailImport, type MailImportDevice, type MailPairing } from '@/api/mailImport'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'

const actionClass = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800'
const iconClass = `${actionClass} h-11 w-11 shrink-0 p-2`
const statusLabels = { pending: 'Ожидает привязки', active: 'Активно', expired: 'Срок истёк', revoked: 'Отозвано' }
const sourceLabels = { cached: 'Локальный кэш Outlook', online: 'Outlook в сети', offline: 'Outlook не в сети' }

function date(value: string | null) {
  return value ? new Date(value).toLocaleString('ru-RU') : 'Ещё не было'
}

function dataScope(includeBody: boolean, includeAttachments: boolean) {
  if (includeBody && includeAttachments) return 'Метаданные, текст и вложения'
  if (includeBody) return 'Метаданные и текст'
  return includeAttachments ? 'Метаданные и вложения' : 'Только метаданные'
}

export function OutlookConnectorSettingsPanel() {
  const [devices, setDevices] = useState<MailImportDevice[]>([])
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [name, setName] = useState('')
  const [includeBody, setIncludeBody] = useState(true)
  const [includeAttachments, setIncludeAttachments] = useState(true)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')
  const [pairing, setPairing] = useState<MailPairing | null>(null)
  const [notice, setNotice] = useState('')
  const [copyState, setCopyState] = useState<'idle' | 'busy' | 'copied' | 'failed'>('idle')
  const [revokeTarget, setRevokeTarget] = useState<MailImportDevice | null>(null)
  const [revoking, setRevoking] = useState(false)
  const [revokeError, setRevokeError] = useState('')
  const [now, setNow] = useState(Date.now)
  const request = useRef(0)
  const listInFlight = useRef<number | null>(null)
  const reloadButton = useRef<HTMLButtonElement>(null)
  const mounted = useRef(true)
  const mutation = useRef(false)
  const pairingRef = useRef(pairing)
  pairingRef.current = pairing
  const modalRef = useProtectedModal<HTMLDivElement>(Boolean(revokeTarget), {
    onEscape: () => { if (!mutation.current) setRevokeTarget(null) },
  })

  const reload = useCallback(async (silent = false) => {
    if (mutation.current || listInFlight.current !== null) return
    const current = ++request.current
    listInFlight.current = current
    if (!silent) setLoading(true)
    setListError('')
    try {
      const next = await mailImport.devices()
      if (!mounted.current || current !== request.current) return
      setDevices(next)
      const pending = pairingRef.current
      if (pending && next.find(device => device.id === pending.device.id)?.status !== 'pending') {
        setPairing(null)
        setNotice('Код больше не доступен. Состояние подключения обновлено.')
      }
    } catch {
      if (mounted.current && current === request.current) setListError('Не удалось загрузить подключения. Повторите загрузку.')
    } finally {
      if (listInFlight.current === current) listInFlight.current = null
      if (mounted.current && current === request.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    void reload()
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => {
      mounted.current = false
      request.current += 1
      listInFlight.current = null
      window.clearInterval(timer)
    }
  }, [reload])

  useEffect(() => {
    if (!pairing) return
    if (Date.parse(pairing.expires_at) <= now) {
      setPairing(null)
      setNotice('Срок кода истёк. Для привязки создайте новое подключение.')
    }
  }, [now, pairing])

  useEffect(() => {
    if (!pairing) return
    const timer = window.setInterval(() => void reload(true), 5000)
    return () => window.clearInterval(timer)
  }, [pairing, reload])

  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (mutation.current || pairing) return
    if (!name.trim()) {
      setCreateError('Укажите название устройства.')
      return
    }
    mutation.current = true
    request.current += 1
    setLoading(false)
    setCreating(true)
    setCreateError('')
    setNotice('')
    try {
      const result = await mailImport.createDevice(name.trim(), includeBody, includeAttachments)
      if (!mounted.current) return
      setDevices(current => [result.device, ...current.filter(device => device.id !== result.device.id)])
      setPairing(result)
      setCopyState('idle')
      setName('')
    } catch {
      if (mounted.current) setCreateError('Не удалось создать подключение. Обновите список перед повтором: запрос мог быть принят.')
    } finally {
      mutation.current = false
      if (mounted.current) setCreating(false)
    }
  }

  const copy = async () => {
    const current = pairing
    if (!current || Date.parse(current.expires_at) <= Date.now() || copyState === 'busy') return
    setCopyState('busy')
    try {
      await navigator.clipboard.writeText(current.pairing_code)
      if (mounted.current && pairingRef.current === current) setCopyState('copied')
    } catch {
      if (mounted.current && pairingRef.current === current) setCopyState('failed')
    }
  }

  const revoke = async () => {
    if (!revokeTarget || mutation.current) return
    mutation.current = true
    request.current += 1
    setLoading(false)
    setRevoking(true)
    setRevokeError('')
    try {
      const result = await mailImport.revokeDevice(revokeTarget.id)
      if (!mounted.current) return
      setDevices(current => current.map(device => device.id === result.id ? result : device))
      if (pairingRef.current?.device.id === result.id) setPairing(null)
      setRevokeTarget(null)
      setNotice('Подключение отозвано. Импортированные записи сохранены.')
      window.requestAnimationFrame(() => reloadButton.current?.focus())
    } catch {
      if (mounted.current) setRevokeError('Не удалось отозвать подключение. Повторите запрос.')
    } finally {
      mutation.current = false
      if (mounted.current) setRevoking(false)
    }
  }

  return (
    <section aria-labelledby="outlook-settings-title" className="min-w-0 border-y border-slate-200 py-5 text-slate-900 dark:border-slate-700 dark:text-slate-100">
      <header className="flex items-center justify-between gap-3">
        <h2 id="outlook-settings-title" className="flex items-center gap-2 text-lg font-semibold"><Monitor aria-hidden="true" className="h-5 w-5 shrink-0" />Outlook Inbox</h2>
        <button ref={reloadButton} type="button" className={iconClass} title="Обновить подключения" aria-label="Обновить подключения" disabled={loading || creating || revoking} onClick={() => void reload()}>
          <RefreshCw aria-hidden="true" className="h-4 w-4" />
        </button>
      </header>
      <form onSubmit={create} className="mt-4 flex flex-wrap items-end gap-3">
        <label className="min-w-0 flex-1 basis-64 text-sm font-medium">
          Название устройства
          <input name="outlook-device-name" autoComplete="off" value={name} maxLength={120} required disabled={creating || revoking || Boolean(pairing)} onChange={event => setName(event.target.value)} className="mt-1 min-h-11 w-full rounded-md border border-slate-300 bg-white px-3 text-base focus-visible:outline-primary dark:border-slate-600 dark:bg-slate-900" />
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="checkbox" name="outlook-include-body" checked={includeBody} disabled={creating || revoking || Boolean(pairing)} onChange={event => setIncludeBody(event.target.checked)} className="h-4 w-4" />
          Передавать текст писем
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input type="checkbox" name="outlook-include-attachments" checked={includeAttachments} disabled={creating || revoking || Boolean(pairing)} onChange={event => setIncludeAttachments(event.target.checked)} className="h-4 w-4" />
          Передавать вложения
        </label>
        <button type="submit" disabled={creating || revoking || Boolean(pairing)} className={`${actionClass} bg-primary text-primary-foreground hover:bg-primary/90 dark:hover:bg-primary/90`}>
          {creating ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Plus aria-hidden="true" className="h-4 w-4" />}
          {creating ? 'Создание…' : 'Создать подключение'}
        </button>
      </form>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">{dataScope(includeBody, includeAttachments)}.</p>
      {includeAttachments && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">До 10 МиБ на файл, до 20 МиБ вложений на письмо. Пропуски означают неполную передачу.</p>}
      {createError && <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">{createError}</p>}
      {pairing && Date.parse(pairing.expires_at) > now && (
        <div className="mt-4 border-l-2 border-primary pl-3" aria-label="Привязка Outlook">
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-medium">Одноразовый код привязки</h3>
            <button type="button" title="Скрыть код" aria-label="Скрыть код" className={iconClass} onClick={() => { setPairing(null); setNotice('Код скрыт. Повторно показать его нельзя.') }}><X aria-hidden="true" className="h-4 w-4" /></button>
          </div>
          <div className="mt-2 flex min-w-0 items-center gap-2">
            <code className="min-w-0 flex-1 select-all break-all rounded bg-slate-100 p-2 text-sm dark:bg-slate-800" data-testid="outlook-pairing-code">{pairing.pairing_code}</code>
            <button type="button" className={iconClass} title="Копировать код" aria-label="Копировать код" disabled={copyState === 'busy'} onClick={() => void copy()}>
              {copyState === 'copied' ? <Check aria-hidden="true" className="h-4 w-4" /> : <Copy aria-hidden="true" className="h-4 w-4" />}
            </button>
          </div>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">Действует до {date(pairing.expires_at)}. Одно использование; после закрытия не показывается.</p>
          {copyState === 'copied' && <p role="status" className="mt-1 text-sm">Код скопирован.</p>}
          {copyState === 'failed' && <p role="alert" className="mt-1 text-sm text-red-600 dark:text-red-400">Не удалось скопировать. Выделите код и скопируйте вручную.</p>}
        </div>
      )}
      <p role="status" className="mt-2 text-sm">{notice}</p>
      {listError && <div role="alert" className="my-3 flex flex-wrap items-center gap-3 text-sm text-red-600 dark:text-red-400">{listError}<button type="button" className={actionClass} disabled={loading || creating || revoking} onClick={() => void reload()}>Повторить загрузку</button></div>}
      {loading && <p role="status" className="py-4 text-sm">Загрузка подключений…</p>}
      {!loading && !listError && devices.length === 0 && <p className="py-4 text-sm text-slate-500 dark:text-slate-400">Подключений Outlook пока нет.</p>}
      <ul aria-label="Устройства Outlook" aria-busy={loading} className="mt-3 divide-y divide-slate-200 dark:divide-slate-700">
        {devices.map(device => {
          const status = device.status !== 'revoked' && device.expires_at && Date.parse(device.expires_at) <= now ? 'expired' : device.status
          return <li key={device.id} className="flex min-w-0 items-start justify-between gap-3 py-3">
            <div className="min-w-0 flex-1 break-words [overflow-wrap:anywhere]">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1"><h3 className="text-sm font-semibold">{device.name}</h3><span className="text-xs text-slate-500 dark:text-slate-400">{statusLabels[status]}</span></div>
              <p className="mt-1 text-sm">{dataScope(device.include_body, device.include_attachments)}{device.mailbox_label ? ` · ${device.mailbox_label}` : ''}</p>
              <dl className="mt-1 grid gap-x-4 gap-y-1 text-xs text-slate-600 sm:grid-cols-2 dark:text-slate-400">
                <div><dt className="inline">Последняя доставка: </dt><dd className="inline tabular-nums">{date(device.last_sync_at)}</dd></div>
                <div><dt className="inline">Источник: </dt><dd className="inline">{device.source_state ? sourceLabels[device.source_state] : 'Ещё не подключён'}</dd></div>
                <div><dt className="inline">Создано: </dt><dd className="inline tabular-nums">{date(device.created_at)}</dd></div>
                {device.expires_at && <div><dt className="inline">Срок действия: </dt><dd className="inline tabular-nums">{date(device.expires_at)}</dd></div>}
              </dl>
              {(device.last_scan_complete === false || device.last_skipped_items > 0) && <p className="mt-2 flex items-start gap-2 text-sm text-amber-800 dark:text-amber-300"><AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" /><span>Неполное сканирование. Пропущено записей: {device.last_skipped_items}.</span></p>}
              {device.last_sync_at && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Свежесть Exchange не подтверждена.{device.last_scan_complete === null ? ' Полнота сканирования неизвестна.' : ''}</p>}
            </div>
            {status !== 'revoked' && <button type="button" className={iconClass} title={`Отозвать ${device.name}`} aria-label={`Отозвать ${device.name}`} disabled={loading || creating || revoking} onClick={event => { event.currentTarget.focus(); setRevokeError(''); setRevokeTarget(device) }}><Unplug aria-hidden="true" className="h-4 w-4" /></button>}
          </li>
        })}
      </ul>
      {revokeTarget && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onPointerDown={preventBackdropDismiss}>
        <div ref={modalRef} role="dialog" aria-modal="true" aria-labelledby="outlook-revoke-title" aria-describedby="outlook-revoke-description" className="max-h-[90dvh] w-full max-w-md overflow-y-auto rounded-lg bg-white p-5 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
          <h3 id="outlook-revoke-title" className="text-lg font-semibold">Отозвать подключение?</h3>
          <p id="outlook-revoke-description" className="mt-3 break-words text-sm [overflow-wrap:anywhere]">«{revokeTarget.name}» больше не сможет передавать данные. Уже импортированные письма и встречи сохранятся.</p>
          {revokeError && <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">{revokeError}</p>}
          <div className="mt-5 flex flex-wrap justify-end gap-2">
            <button type="button" className={actionClass} disabled={revoking} onClick={() => setRevokeTarget(null)}>Отмена</button>
            <button type="button" className={`${actionClass} text-red-600 dark:text-red-400`} disabled={revoking} onClick={() => void revoke()}><Unplug aria-hidden="true" className="h-4 w-4" />{revoking ? 'Отзыв…' : 'Отозвать подключение'}</button>
          </div>
        </div>
      </div>}
    </section>
  )
}

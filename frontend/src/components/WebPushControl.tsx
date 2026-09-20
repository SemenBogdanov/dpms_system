import { useEffect, useState } from 'react'
import { Bell, BellOff, Loader2 } from 'lucide-react'
import { api } from '@/api/client'

type PushConfig = { available: boolean; public_key: string | null }
type PushState = 'loading' | 'unsupported' | 'install' | 'unavailable' | 'error' | 'denied' | 'off' | 'on'

function installed(): boolean {
  return window.matchMedia('(display-mode: standalone)').matches
    || (navigator as Navigator & { standalone?: boolean }).standalone === true
}

function appleMobile(): boolean {
  return /iPhone|iPad|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

function applicationKey(value: string): Uint8Array {
  const binary = atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4))
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes
}

function sameKey(subscription: PushSubscription, expected: Uint8Array): boolean {
  const current = subscription.options.applicationServerKey
  if (!current) return false
  const bytes = new Uint8Array(current)
  return bytes.length === expected.length && bytes.every((byte, index) => byte === expected[index])
}

export function WebPushControl() {
  const [config, setConfig] = useState<PushConfig | null>(null)
  const [state, setState] = useState<PushState>('loading')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!appleMobile()) return
    let active = true
    async function load() {
      try {
        const next = await api.get<PushConfig>('/api/web-push/config')
        if (!active) return
        setConfig(next)
        if (!next.available) return setState('unavailable')
        if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return setState('unsupported')
        if (!installed()) return setState('install')
        if (Notification.permission === 'denied') return setState('denied')
        const registration = await navigator.serviceWorker.getRegistration()
        let subscription = await registration?.pushManager.getSubscription()
        if (!active) return
        if (subscription && Notification.permission === 'granted') {
          if (next.public_key && sameKey(subscription, applicationKey(next.public_key))) {
            await api.post('/api/web-push/subscriptions', subscription.toJSON())
            if (active) setState('on')
          } else {
            await api.delete('/api/web-push/subscriptions', subscription.toJSON())
            await subscription.unsubscribe()
            subscription = null
            if (active) setState('off')
          }
        } else setState('off')
      } catch {
        if (active) {
          setState('error')
        }
      }
    }
    void load()
    return () => { active = false }
  }, [])

  async function enable() {
    if (!config?.public_key || busy) return
    setBusy(true)
    setError('')
    try {
      // iOS requires the permission request to originate from this button press.
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        setState(permission === 'denied' ? 'denied' : 'off')
        return
      }
      const registration = await navigator.serviceWorker.register('/push-sw.js', { scope: '/' })
      const key = applicationKey(config.public_key)
      let subscription = await registration.pushManager.getSubscription()
      if (subscription && !sameKey(subscription, key)) {
        await api.delete('/api/web-push/subscriptions', subscription.toJSON())
        await subscription.unsubscribe()
        subscription = null
      }
      subscription = subscription || await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key })
      await api.post('/api/web-push/subscriptions', subscription.toJSON())
      setState('on')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось включить уведомления')
    } finally {
      setBusy(false)
    }
  }

  async function disable() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const registration = await navigator.serviceWorker.getRegistration()
      const subscription = await registration?.pushManager.getSubscription()
      if (subscription) {
        await api.delete('/api/web-push/subscriptions', subscription.toJSON())
        await subscription.unsubscribe()
      }
      setState('off')
    } catch {
      setError('Не удалось отключить уведомления. Повторите действие.')
    } finally {
      setBusy(false)
    }
  }

  if (!appleMobile() || state === 'loading') return null
  const help = {
    unavailable: 'Уведомления пока не настроены на сервере.',
    error: 'Не удалось проверить уведомления. Обновите страницу.',
    unsupported: 'Этот браузер не поддерживает push-уведомления.',
    install: 'Откройте DPMS с ярлыка на экране «Домой».',
    denied: 'Разрешите уведомления для DPMS в настройках iPhone.',
    off: 'Уведомления на iPhone',
    on: 'Уведомления включены',
  }[state]

  return (
    <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2 text-sm">
      <div className="flex items-center gap-2 text-slate-600">
        {state === 'on' ? <Bell className="h-4 w-4 text-emerald-600" /> : <BellOff className="h-4 w-4" />}
        <span>{help}</span>
      </div>
      {(state === 'off' || state === 'on') && (
        <button type="button" onClick={state === 'on' ? disable : enable} disabled={busy}
          title={state === 'on' ? 'Отключить уведомления' : 'Включить уведомления'}
          aria-label={state === 'on' ? 'Отключить уведомления' : 'Включить уведомления'}
          className="inline-flex min-h-10 items-center gap-2 rounded-md border border-slate-200 px-3 text-sm font-medium hover:bg-slate-50 disabled:opacity-50">
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          {state === 'on' ? <BellOff className="h-4 w-4" /> : <><Bell className="h-4 w-4" />Включить</>}
        </button>
      )}
      {error && <p className="w-full text-sm text-rose-700" role="alert">{error}</p>}
    </div>
  )
}

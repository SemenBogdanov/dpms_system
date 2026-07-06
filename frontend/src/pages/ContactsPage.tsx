import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, Send, UserCheck, UserPlus, Users, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type { Contact } from '@/api/types'

function contactName(contact: Contact): string {
  return contact.direction === 'incoming' ? contact.requester_name : contact.recipient_name
}

function contactEmail(contact: Contact): string {
  return contact.direction === 'incoming' ? contact.requester_email : contact.recipient_email
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function ContactsPage() {
  const [contacts, setContacts] = useState<Contact[]>([])
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const loadContacts = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.get<Contact[]>('/api/contacts')
      setContacts(data)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки контактов')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadContacts()
  }, [loadContacts])

  const acceptedContacts = useMemo(
    () => contacts.filter((contact) => contact.status === 'accepted'),
    [contacts]
  )
  const incomingRequests = useMemo(
    () => contacts.filter((contact) => contact.status === 'pending' && contact.direction === 'incoming'),
    [contacts]
  )
  const outgoingRequests = useMemo(
    () => contacts.filter((contact) => contact.status === 'pending' && contact.direction === 'outgoing'),
    [contacts]
  )

  const sendRequest = async () => {
    if (!email.trim()) {
      toast.error('Введите email')
      return
    }
    setBusy(true)
    try {
      await api.post<Contact>('/api/contacts', { email })
      setEmail('')
      await loadContacts()
      toast.success('Заявка отправлена')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка отправки заявки')
    } finally {
      setBusy(false)
    }
  }

  const respond = async (contact: Contact, action: 'accept' | 'reject') => {
    setBusy(true)
    try {
      await api.patch<Contact>(`/api/contacts/${contact.id}/${action}`, {})
      await loadContacts()
      toast.success(action === 'accept' ? 'Контакт добавлен' : 'Заявка отклонена')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка обработки заявки')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Контакты</h1>
          <p className="mt-1 text-sm text-slate-500">Общие связи для заметок, задач и будущей совместной работы</p>
        </div>
        <div className="grid grid-cols-3 overflow-hidden rounded-lg border border-slate-200 bg-white text-center text-xs shadow-sm">
          <div className="px-3 py-2">
            <div className="font-semibold text-slate-900">{acceptedContacts.length}</div>
            <div className="text-slate-400">контакты</div>
          </div>
          <div className="border-l border-slate-200 px-3 py-2">
            <div className="font-semibold text-primary">{incomingRequests.length}</div>
            <div className="text-slate-400">входящие</div>
          </div>
          <div className="border-l border-slate-200 px-3 py-2">
            <div className="font-semibold text-slate-700">{outgoingRequests.length}</div>
            <div className="text-slate-400">ожидают</div>
          </div>
        </div>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <UserPlus className="h-4 w-4 text-primary" />
          Добавить контакт
        </div>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="min-h-11 min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
            placeholder="email пользователя"
          />
          <button
            type="button"
            onClick={sendRequest}
            disabled={busy || !email.trim()}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
            Отправить заявку
          </button>
        </div>
      </section>

      {loading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">Загрузка...</div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
              <Users className="h-4 w-4 text-primary" />
              Входящие
            </div>
            <div className="mt-3 space-y-2">
              {incomingRequests.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-300 p-3 text-sm text-slate-500">
                  Нет входящих заявок.
                </div>
              ) : (
                incomingRequests.map((contact) => (
                  <div key={contact.id} className="rounded-lg border border-primary/20 bg-primary/5 p-3">
                    <div className="truncate text-sm font-medium text-slate-800">{contactName(contact)}</div>
                    <div className="truncate text-xs text-slate-500">{contactEmail(contact)}</div>
                    <div className="mt-1 text-xs text-slate-400">{formatDate(contact.created_at)}</div>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={() => respond(contact, 'accept')}
                        disabled={busy}
                        className="inline-flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-xs font-medium text-primary-foreground disabled:opacity-50"
                      >
                        <Check className="h-3 w-3" />
                        Принять
                      </button>
                      <button
                        type="button"
                        onClick={() => respond(contact, 'reject')}
                        disabled={busy}
                        className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                      >
                        <X className="h-3 w-3" />
                        Отклонить
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
              <UserCheck className="h-4 w-4 text-primary" />
              Мои контакты
            </div>
            <div className="mt-3 space-y-2">
              {acceptedContacts.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-300 p-3 text-sm text-slate-500">
                  Принятых контактов пока нет.
                </div>
              ) : (
                acceptedContacts.map((contact) => (
                  <div key={contact.id} className="rounded-lg bg-slate-50 px-3 py-2">
                    <div className="truncate text-sm font-medium text-slate-800">{contactName(contact)}</div>
                    <div className="truncate text-xs text-slate-500">{contactEmail(contact)}</div>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
              <Send className="h-4 w-4 text-primary" />
              Ожидают ответа
            </div>
            <div className="mt-3 space-y-2">
              {outgoingRequests.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-300 p-3 text-sm text-slate-500">
                  Нет отправленных заявок.
                </div>
              ) : (
                outgoingRequests.map((contact) => (
                  <div key={contact.id} className="rounded-lg bg-slate-50 px-3 py-2">
                    <div className="truncate text-sm font-medium text-slate-800">{contactName(contact)}</div>
                    <div className="truncate text-xs text-slate-500">{contactEmail(contact)}</div>
                    <div className="mt-1 text-xs text-slate-400">Отправлено {formatDate(contact.created_at)}</div>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { Pencil, Plus, RefreshCw, Save } from 'lucide-react'
import { auditCalendar, type CalendarAdminState, type CalendarMember, type CalendarRole } from '@/api/auditCalendar'
import { ApiError } from '@/api/client'
import { MAX_DATE, MIN_DATE, calendarRoles, errorText, moscowToday } from '@/lib/auditCalendar'
import { useCalendarMutation } from '@/lib/auditCalendarHooks'
import { CalendarModal } from './CalendarModal'
import './audit-calendar.css'

export function AuditCalendarAdminPanel() {
  const [state, setState] = useState<CalendarAdminState | null>(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<CalendarMember | 'new' | 'setup' | null>(null)
  const refresh = useCallback(async () => {
    try { const result = await auditCalendar.admin(); setState(result); setError(''); return result }
    catch (e) { setError(errorText(e)); if (e instanceof ApiError && e.status === 403) { setState(null); setEditing(null) }; throw e }
  }, [])
  useEffect(() => { void refresh().catch(() => undefined) }, [refresh])
  useEffect(() => {
    const revoke = () => { setState(null); setEditing(null); setError('Доступ администратора отозван.') }
    window.addEventListener('audit-calendar:access-revoked', revoke)
    return () => window.removeEventListener('audit-calendar:access-revoked', revoke)
  }, [])
  return <section className="ac ac-admin" aria-label="Администрирование календаря аудита"><header className="ac-section-head"><h2>Календарь аудита</h2><button type="button" className="ac-icon" aria-label="Обновить участников календаря" title="Обновить участников календаря" onClick={() => void refresh().catch(() => undefined)}><RefreshCw size={16} /></button></header>
    {error && <p className="ac-error" role="alert">{error}</p>}{!state && !error && <p role="status">Загрузка контура…</p>}
    {state && <>{state.scope ? <><p>{state.scope.name} · {state.scope.timezone} · версия {state.scope.version}</p><div className="ac-actions"><button type="button" onClick={() => setEditing('new')}><Plus size={16} />Участник контура</button></div><div className="ac-table-wrap"><table><thead><tr><th>Сотрудник</th><th>Код</th><th>Роль</th><th>Помощник</th><th>Участие</th><th><span className="sr-only">Действия</span></th></tr></thead><tbody>{state.members.map(m => <tr key={m.user_id}><td>{m.full_name}</td><td>{m.code}</td><td>{calendarRoles[m.role]}</td><td>{m.can_manage ? 'Да' : 'Нет'}</td><td>{m.active ? 'Активно' : 'Отключено'}</td><td><button type="button" className="ac-icon" title={`Изменить участие ${m.full_name}`} aria-label={`Изменить участие ${m.full_name}`} onClick={() => setEditing(m)}><Pencil size={16} /></button></td></tr>)}</tbody></table></div></> : <><p className="ac-empty">Контур календаря ещё не создан.</p><button type="button" className="ac-primary" onClick={() => setEditing('setup')}><Plus size={16} />Создать контур</button></>}
      <p className="ac-muted">Допуск к разделу выдаётся в карточке пользователя. Участие и полномочие помощника назначаются отдельно, в том числе администратору.</p>
      {editing && <AdminEditor state={state} editing={editing} onClose={() => setEditing(null)} onRefresh={refresh} />}
    </>}
  </section>
}

function AdminEditor({ state, editing, onClose, onRefresh: refresh }: { state: CalendarAdminState; editing: CalendarMember | 'new' | 'setup'; onClose: () => void; onRefresh: () => Promise<CalendarAdminState> }) {
  const existing = typeof editing === 'object' ? editing : undefined
  const [user, setUser] = useState(existing?.user_id || '')
  const [code, setCode] = useState(existing?.code || '')
  const [role, setRole] = useState<CalendarRole>(existing?.role || 'observer')
  const [manage, setManage] = useState(existing?.can_manage || false)
  const [active, setActive] = useState(existing?.active ?? true)
  const [name, setName] = useState('Календарь аудита')
  const [baseline, setBaseline] = useState(moscowToday())
  const [dirty, setDirty] = useState(false)
  const [draftVersion, setDraftVersion] = useState(state.scope?.version || 0)
  const mutation = useCalendarMutation()
  const onRefresh = async () => { const result = await refresh(); setDraftVersion(result.scope?.version || 0); return result }
  const selected = state.users.find(u => u.id === user)
  return <CalendarModal title={editing === 'setup' ? 'Создание контура' : 'Участие в календаре'} dirty={dirty} busy={mutation.busy} onClose={onClose}><form className="ac-form" onChange={() => setDirty(true)} onSubmit={async e => {
    e.preventDefault()
    if (editing !== 'setup' && active && (!selected?.audit_calendar_enabled || !selected.is_active)) { mutation.setError('Сначала выдайте активному пользователю допуск к разделу в его карточке.'); return }
    const body = editing === 'setup' ? { name, baseline } : { user_id: user, code, role, can_manage: manage, active }
    const result = await mutation.run(body, draftVersion, (request_id, expected_version) => editing === 'setup' ? auditCalendar.setup({ request_id, name, baseline }) : auditCalendar.member({ request_id, expected_version, user_id: user, code, role, can_manage: manage, active }))
    if (result) { onClose(); await onRefresh().catch(() => undefined) }
  }}><fieldset disabled={mutation.busy}>{editing === 'setup' ? <><label>Название<input required maxLength={160} value={name} onChange={e => setName(e.target.value)} /></label><label>Начало накопления<input type="date" required min={MIN_DATE} max={MAX_DATE} value={baseline} onChange={e => setBaseline(e.target.value)} /></label><p className="ac-warning">Будет создан единственный контур Europe/Moscow с начальной нормой 6. Участие администратора не выдаётся автоматически.</p></> : <><label>Учётная запись<select required disabled={!!existing} value={user} onChange={e => setUser(e.target.value)}><option value="">Выберите пользователя</option>{state.users.map(u => <option key={u.id} value={u.id}>{u.full_name}{!u.audit_calendar_enabled ? ' · без допуска' : ''}{!u.is_active ? ' · неактивен' : ''}</option>)}</select></label><div className="ac-form-grid"><label>Код<input required maxLength={40} value={code} onChange={e => setCode(e.target.value)} /></label><label>Роль<select value={role} onChange={e => setRole(e.target.value as CalendarRole)}>{Object.entries(calendarRoles).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div><label className="ac-check"><input type="checkbox" checked={manage} onChange={e => setManage(e.target.checked)} />Помощник управления расписанием</label><label className="ac-check"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} />Активное участие</label>{selected && !selected.audit_calendar_enabled && <p className="ac-warning">Допуск к разделу не выдан. Активное участие нельзя сохранить до выдачи допуска.</p>}</>}</fieldset>{mutation.error && <p className="ac-error" role="alert">{mutation.error}</p>}{mutation.stale && <button type="button" onClick={async () => { try { await onRefresh(); mutation.rebase() } catch (e) { mutation.setError(errorText(e)) } }}>Перечитать, сохранив ввод</button>}<button type="submit" className="ac-primary" disabled={mutation.busy || mutation.stale}><Save size={16} />{mutation.busy ? 'Сохранение…' : 'Сохранить'}</button></form></CalendarModal>
}

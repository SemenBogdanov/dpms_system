import { useId, useState } from 'react'
import { Archive, Pencil, Plus, Users } from 'lucide-react'
import type { CalendarAbsence, CalendarGroup, CalendarScope, CalendarState } from '@/api/auditCalendar'
import { MAX_DATE, calendarRoles, calendarTargetScopes, numberLabel, periodError, validDate } from '@/lib/auditCalendar'
import { CalendarCommandForm } from './CalendarCommandForm'

export type CalendarAction = { kind: 'norm'; groupId?: string } | { kind: 'group'; group?: CalendarGroup } | { kind: 'absence'; user: string } | { kind: 'end-absence'; absence: CalendarAbsence } | { kind: 'archive' }

function effectiveNorm(state: CalendarState, groupId: string | null, date = state.scope.today) {
  return state.norms.filter(n => n.group_id === groupId && n.effective_from <= date)
    .sort((a, b) => b.effective_from.localeCompare(a.effective_from) || b.recorded_at.localeCompare(a.recorded_at))[0]
}

function GroupNorm({ state, groupId, onAction }: { state: CalendarState; groupId: string; onAction: (action: CalendarAction) => void }) {
  const group = state.groups.find(g => g.id === groupId)
  const norm = effectiveNorm(state, groupId)
  return <div className="ac-actions"><span>{norm ? `${numberLabel(norm.value)} / 10 будней` : 'Не задана'}</span>
    {state.actor.can_manage && !state.scope.archived && group && !group.archived && !group.legacy && <button className="ac-icon" type="button" title={`Изменить норму ${group.code}`} aria-label={`Изменить норму ${group.code}`} onClick={() => onAction({ kind: 'norm', groupId })}><Pencil size={16} /></button>}
  </div>
}
export function CalendarManagement({ state, onAction }: { state: CalendarState; onAction: (action: CalendarAction) => void }) {
  const { stats } = state
  return <section aria-label="Управление расписанием"><header className="ac-section-head"><h2>Управление расписанием</h2><div className="ac-actions">{state.actor.can_manage && <button type="button" disabled={state.scope.archived} onClick={() => onAction({ kind: 'norm' })}><Pencil size={16} />Изменить норму</button>}{state.actor.can_archive && <button type="button" onClick={() => onAction({ kind: 'archive' })}><Archive size={16} />{state.scope.archived ? 'Вернуть из архива' : 'Архивировать контур'}</button>}</div></header>
    <div className="ac-summary-band"><div><small>Недобор на {stats.through || '—'}</small><strong>{numberLabel(stats.backlog)}</strong></div><div><small>Начало накопления</small><strong>{state.scope.baseline}</strong></div><div><small>Область цели</small><strong>{calendarTargetScopes[stats.target_scope]}</strong></div></div>
    {!state.scope.history_complete && <p className="ac-warning">История неполна. Недобор рассчитан по внесённым данным и не доказывает, что остальные встречи не состоялись.</p>}
    <p className="ac-muted">Командная цель и квоты групп независимы. Отсутствия не уменьшают норматив. Пн–Пт, без производственных праздников.</p>
    <h3>Нарастающий итог по двухнедельным периодам</h3><div className="ac-table-wrap"><table><thead><tr><th>Период</th><th>Цель</th><th>Проведено</th><th>Баланс</th><th>Накопленный недобор</th></tr></thead><tbody>{stats.fortnights.map(p => <tr key={p.from}><td>{p.from} — {p.to}</td><td>{numberLabel(p.target)}</td><td>{p.completed}</td><td>{numberLabel(p.balance)}</td><td>{numberLabel(p.cumulative_backlog)}</td></tr>)}</tbody></table></div>
    <h3>Группы</h3><div className="ac-table-wrap"><table><thead><tr><th>Группа</th><th>Норма на сегодня</th><th>Цель</th><th>Проведено</th><th>Баланс</th><th>Недобор</th></tr></thead><tbody>{stats.groups.map(g => <tr key={g.group_id}><th>{g.code}</th><td><GroupNorm state={state} groupId={g.group_id} onAction={onAction} /></td><td>{numberLabel(g.target)}</td><td>{g.completed}</td><td>{numberLabel(g.balance)}</td><td>{numberLabel(g.backlog)}</td></tr>)}</tbody></table></div>
    <NormHistory state={state} />
    <h3>Отсутствия</h3><AbsenceList state={state} onAction={onAction} />
  </section>
}
export function NormHistory({ state }: { state: CalendarState }) {
  return <><h3>История норм</h3><div className="ac-table-wrap"><table><thead><tr><th>Действует с</th><th>Область</th><th>Норма</th><th>Основание</th></tr></thead><tbody>{[...state.norms].sort((a, b) => b.effective_from.localeCompare(a.effective_from)).map(n => <tr key={n.id}><td>{n.effective_from}{n.effective_from > state.scope.today && <small>Запланировано</small>}</td><td>{n.group_id ? state.groups.find(g => g.id === n.group_id)?.code || n.group_id : 'Команда'}</td><td>{numberLabel(n.value)} / {n.group_id ? '10 будней' : 'будний день'}</td><td>{n.reason}</td></tr>)}</tbody></table></div></>
}
export function AbsenceList({ state, onAction }: { state: CalendarState; onAction: (action: CalendarAction) => void }) {
  return state.absences.length ? <div className="ac-table-wrap"><table><thead><tr><th>Участник</th><th>С / по включительно</th><th>Причина</th><th>Статус</th><th><span className="sr-only">Действия</span></th></tr></thead><tbody>{state.absences.map(a => <tr key={a.id}><td>{state.members.find(m => m.user_id === a.user_id)?.full_name || a.user_id}</td><td>{a.start_date} — {a.end_date}</td><td>{a.reason}</td><td>{a.status === 'active' ? 'Действует' : 'Завершено'}</td><td>{!state.scope.archived && (state.actor.can_manage || a.user_id === state.actor.user_id) && a.status === 'active' && a.end_date >= state.scope.today && <button type="button" onClick={() => onAction({ kind: 'end-absence', absence: a })}>Завершить с сегодня</button>}</td></tr>)}</tbody></table></div> : <p className="ac-empty">Отсутствий в периоде нет.</p>
}
export function CalendarDirectories({ state, onAction }: { state: CalendarState; onAction: (action: CalendarAction) => void }) {
  return <section aria-label="Справочники"><header className="ac-section-head"><h2>Справочники</h2>{state.actor.can_manage && !state.scope.archived && <button type="button" onClick={() => onAction({ kind: 'group' })}><Plus size={16} />Группа</button>}</header>
    <h3>Составы групп</h3><div className="ac-table-wrap"><table><thead><tr><th>Группа</th><th>Название</th><th>Норма на сегодня</th><th>История состава</th><th>Статус</th><th><span className="sr-only">Действия</span></th></tr></thead><tbody>{state.groups.map(g => <tr key={g.id}><th>{g.code}</th><td>{g.label}</td><td><GroupNorm state={state} groupId={g.id} onAction={onAction} /></td><td>{g.versions.map(v => <div key={v.id}>{v.effective_from}: {state.members.find(m => m.user_id === v.auditor_id)?.code || '—'} + {state.members.find(m => m.user_id === v.tech_id)?.code || '—'}</div>)}{!g.versions.length && 'Состав не установлен'}</td><td>{g.archived ? 'Архив' : g.legacy ? 'Историческая' : 'Действует'}</td><td>{state.actor.can_manage && !state.scope.archived && !g.legacy && <button className="ac-icon" type="button" title={`Изменить ${g.code}`} aria-label={`Изменить ${g.code}`} onClick={() => onAction({ kind: 'group', group: g })}><Pencil size={16} /></button>}</td></tr>)}</tbody></table></div>
    {!state.groups.length && <p className="ac-empty">Групп пока нет.</p>}
    <h3><Users size={17} /> Участники контура</h3><div className="ac-table-wrap"><table><thead><tr><th>Код</th><th>Сотрудник</th><th>Роль</th><th>Полномочие</th><th>Статус</th></tr></thead><tbody>{state.members.map(m => <tr key={m.user_id}><th>{m.code}</th><td>{m.full_name}</td><td>{calendarRoles[m.role]}</td><td>{m.can_manage ? 'Помощник' : 'Сотрудник'}</td><td>{m.active ? 'Активен' : 'Отключён'}</td></tr>)}</tbody></table></div><NormHistory state={state} />
  </section>
}

export function CalendarActionEditor({ action, state, onClose, onRefresh }: { action: CalendarAction; state: CalendarState; onClose: () => void; onRefresh: () => Promise<unknown> }) {
  const reasonId = useId()
  const existing = action.kind === 'group' ? action.group : undefined
  const composition = existing?.versions.filter(v => v.effective_from <= state.scope.today).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]
  const normMinDate = state.scope.today > state.scope.baseline ? state.scope.today : state.scope.baseline
  const [from, setFrom] = useState(action.kind === 'norm' ? normMinDate : state.scope.today)
  const [to, setTo] = useState(state.scope.today)
  const [reason, setReason] = useState('')
  const [group, setGroup] = useState(action.kind === 'norm' ? action.groupId || '' : '')
  const normAt = (id: string) => effectiveNorm(state, id || null, from)?.value ?? 0
  const [value, setValue] = useState(() => normAt(group))
  const [code, setCode] = useState(existing?.code || '')
  const [label, setLabel] = useState(existing?.label || '')
  const [auditor, setAuditor] = useState(composition?.auditor_id || '')
  const [tech, setTech] = useState(composition?.tech_id || '')
  const [archived, setArchived] = useState(existing?.archived || false)
  const [archiveTarget] = useState(!state.scope.archived)
  const validateNorm = () => {
    if (!state.actor.can_manage || state.scope.archived) return 'Изменение нормы доступно только помощнику действующего контура.'
    if (group && !state.groups.some(g => g.id === group && !g.legacy && !g.archived)) return 'Выберите действующую современную группу.'
    if (!validDate(from) || from < normMinDate) return 'Изменение нормы не может пересчитывать прошлые даты или начинаться раньше контура.'
    if (!reason.trim()) return 'Укажите основание.'
    if (!Number.isInteger(value) || value < 0 || value > 1000) return 'Укажите целую норму от 0 до 1000.'
    return ''
  }
  const title = { norm: 'Изменить норму', group: existing ? 'Версия состава группы' : 'Новая группа', absence: 'Период отсутствия', 'end-absence': 'Завершить отсутствие', archive: state.scope.archived ? 'Вернуть контур из архива' : 'Архивировать контур' }[action.kind]
  return <CalendarCommandForm title={title} version={state.scope.version} onClose={onClose} onRefresh={onRefresh} validate={() => action.kind === 'norm' ? validateNorm() : action.kind === 'archive' ? !state.actor.can_archive ? 'Архивирование доступно только администратору.' : state.scope.archived === archiveTarget ? 'Состояние архива уже изменилось. Закройте форму и проверьте контур.' : !reason.trim() ? 'Укажите основание.' : '' : action.kind === 'absence' ? periodError(from, to) : ''} command={() => {
    switch (action.kind) {
      case 'norm': return { operation: 'norm.set', payload: { group_id: group || null, effective_from: from, value, reason: reason.trim() } }
      case 'group': return { operation: 'group.save', payload: { ...(existing && { id: existing.id }), code, label, archived, effective_from: from, ...(auditor && { auditor_id: auditor }), ...(tech && { tech_id: tech }), reason } }
      case 'absence': return { operation: 'absence.add', payload: { user_id: action.user, start_date: from, end_date: to, reason } }
      case 'end-absence': return { operation: 'absence.end', payload: { id: action.absence.id, reason } }
      case 'archive': return { operation: 'scope.archive', payload: { archived: archiveTarget, reason: reason.trim() } }
    }
  }}>
    {action.kind === 'norm' && <><label>Область нормы<select value={group} onChange={e => { setGroup(e.target.value); setValue(normAt(e.target.value)) }}><option value="">Команда · на будний день</option>{state.groups.filter(g => !g.legacy && !g.archived).map(g => <option key={g.id} value={g.id}>{g.code} · на 10 будней</option>)}</select></label><label>{group ? 'Встреч на 10 будней' : 'Встреч на будний день'}<input required type="number" min={0} max={1000} step={1} value={value} onChange={e => setValue(Number(e.target.value))} /></label><p className="ac-warning">Прошлые нормы и более поздние изменения сохранятся. Норма группы не меняет цель команды.</p></>}
    {action.kind === 'group' && <><div className="ac-form-grid"><label>Код<input required maxLength={40} autoComplete="off" value={code} onChange={e => setCode(e.target.value)} /></label><label>Название<input required maxLength={160} autoComplete="off" value={label} onChange={e => setLabel(e.target.value)} /></label></div><div className="ac-form-grid">{(['auditor', 'tech'] as const).map(role => <label key={role}>{calendarRoles[role]}<select required value={role === 'auditor' ? auditor : tech} onChange={e => role === 'auditor' ? setAuditor(e.target.value) : setTech(e.target.value)}><option value="">Выберите участника</option>{state.members.filter(m => m.active && m.role === role).map(m => <option key={m.user_id} value={m.user_id}>{m.code} · {m.full_name}</option>)}</select></label>)}</div>{existing && <label className="ac-check"><input type="checkbox" checked={archived} onChange={e => setArchived(e.target.checked)} />Архивная группа</label>}</>}
    {['norm', 'group', 'absence'].includes(action.kind) && <label>{action.kind === 'absence' ? 'С, включительно' : 'Действует с'}<input type="date" min={action.kind === 'norm' ? normMinDate : state.scope.today} max={MAX_DATE} value={from} required onChange={e => setFrom(e.target.value)} /></label>}
    {action.kind === 'absence' && <><label>По, включительно<input type="date" min={from} max={MAX_DATE} required value={to} onChange={e => setTo(e.target.value)} /></label><p className="ac-warning">Назначение участника на весь период будет заблокировано. Существующие встречи и цель сохранятся.</p></>}
    {action.kind === 'end-absence' && <p className="ac-warning">Прошедшая часть {action.absence.start_date}–{action.absence.end_date} сохранится. Будущая часть будет завершена с сегодня.</p>}
    {action.kind === 'archive' && <p className="ac-warning">{state.scope.archived ? 'Участники снова смогут изменять расписание по своим полномочиям.' : 'Изменения расписания будут заблокированы. Вся история сохранится.'}</p>}
    <div className="ac-field"><label htmlFor={reasonId}>Основание</label><textarea id={reasonId} required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></div>
  </CalendarCommandForm>
}

export function CalendarArchiveEditor({ scope, onClose, onRefresh }: { scope: CalendarScope; onClose: () => void; onRefresh: () => Promise<unknown> }) {
  const reasonId = useId()
  const [reason, setReason] = useState('')
  const [archived] = useState(!scope.archived)
  return <CalendarCommandForm title={archived ? 'Архивировать контур' : 'Вернуть контур из архива'} version={scope.version} onClose={onClose} onRefresh={onRefresh} validate={() => !reason.trim() ? 'Укажите основание.' : scope.archived === archived ? 'Состояние архива уже изменилось. Закройте форму и проверьте контур.' : ''} command={() => ({ operation: 'scope.archive', payload: { archived, reason: reason.trim() } })}>
    <p className="ac-warning">{archived ? 'Изменения расписания будут заблокированы. Вся история сохранится.' : 'Участники снова смогут изменять расписание по своим полномочиям.'}</p>
    <div className="ac-field"><label htmlFor={reasonId}>Основание</label><textarea id={reasonId} required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></div>
  </CalendarCommandForm>
}

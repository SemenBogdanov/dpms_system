import { useEffect, useState } from 'react'
import { Check, Plus, RefreshCw, Upload, X } from 'lucide-react'
import { auditCalendar, type CalendarImport, type CalendarPlan, type CalendarRole, type CalendarState } from '@/api/auditCalendar'
import { addDays, allSlots, calendarRoles, errorText, MIN_DATE, timeLabel } from '@/lib/auditCalendar'
import { useCalendarDraftGuard, useCalendarMutation } from '@/lib/auditCalendarHooks'
import { CalendarCommandForm } from './CalendarCommandForm'

export function CalendarImports({ state, onRefresh }: { state: CalendarState; onRefresh: () => Promise<unknown> }) {
  const [batches, setBatches] = useState<CalendarImport[]>([])
  const [source, setSource] = useState<unknown>(null)
  const [fileName, setFileName] = useState('')
  const [mapping, setMapping] = useState<{ source: string; user: string }[]>([])
  const [preview, setPreview] = useState<CalendarImport | null>(null)
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [notice, setNotice] = useState('')
  const [draftVersion, setDraftVersion] = useState(state.scope.version)
  const [bootstrap, setBootstrap] = useState(false)
  const [groupMapping, setGroupMapping] = useState<{ code: string; auditor_id: string; tech_id: string }[]>([])
  const mutation = useCalendarMutation()
  useCalendarDraftGuard(source !== null)
  useEffect(() => {
    let live = true
    auditCalendar.imports().then(result => { if (live) setBatches(Array.isArray(result) ? result : result.items) }).catch(e => { if (live) setNotice(errorText(e)) })
    return () => { live = false }
  }, [])
  async function readFile(file: File | undefined) {
    if (!file) return
    try {
      if (file.size > 8 * 1024 * 1024) throw new Error('Размер JSON не должен превышать 8 МБ.')
      const data: unknown = JSON.parse(await file.text())
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Нужен JSON-объект V5.')
      setSource(data); setDraftVersion(state.scope.version); setFileName(file.name); setMapping([]); setGroupMapping([]); setBootstrap(false); setPreview(null); setConfirmed(false); setNotice('')
    } catch (e) { mutation.setError(errorText(e)) }
  }
  async function makePreview() {
    const chosen = mapping.filter(m => m.source || m.user)
    if (chosen.some(m => !m.source.trim() || !m.user) || new Set(chosen.map(m => m.source.trim())).size !== chosen.length) { mutation.setError('Заполните уникальный код источника и учётную запись в каждой строке.'); return }
    if (bootstrap && (groupMapping.some(g => !g.code.trim() || !g.auditor_id || !g.tech_id || g.code === 'G21' || g.auditor_id === g.tech_id) || new Set(groupMapping.map(g => g.code.trim())).size !== groupMapping.length)) { mutation.setError('Укажите уникальные группы с явным составом А+Т. G21 не получает выдуманный состав.'); return }
    const body = { source, mapping: Object.fromEntries(chosen.map(m => [m.source.trim(), m.user])), bootstrap_history: bootstrap, group_mapping: bootstrap ? Object.fromEntries(groupMapping.map(g => [g.code.trim(), { auditor_id: g.auditor_id, tech_id: g.tech_id }])) : {} }
    const result = await mutation.run(body, draftVersion, (request_id, expected_version) => auditCalendar.preview({ ...body, request_id, expected_version }))
    if (result) { setPreview(result.value); setDraftVersion(result.value.version); setConfirmed(false); await onRefresh().catch(() => undefined) }
  }
  async function apply() {
    if (!preview || !confirmed || !reason.trim()) return
    const body = { confirm: true as const, reason }
    const result = await mutation.run({ batch: preview.id, ...body }, preview.version, (request_id, expected_version) => auditCalendar.applyImport(preview.id, { ...body, request_id, expected_version }))
    if (result) {
      setSource(null); setPreview(null); setMapping([]); setReason(''); setConfirmed(false); setFileName(''); setNotice('Импорт подтверждён сервером.')
      try { await onRefresh(); const result = await auditCalendar.imports(); setBatches(Array.isArray(result) ? result : result.items) } catch (e) { setNotice(`Импорт сохранён. ${errorText(e)}`) }
    }
  }
  return <section aria-label="Импорт источника"><header className="ac-section-head"><h2>Импорт источника</h2><Upload size={20} /></header>
    <div className="ac-import-form"><label>JSON V5<input type="file" accept=".json,application/json" disabled={mutation.busy || state.scope.archived} onChange={e => void readFile(e.target.files?.[0])} /></label>{fileName && <p>{fileName}</p>}
      {source !== null && <><h3>Сопоставление учётных записей</h3>{mapping.map((row, index) => <div className="ac-mapping-row" key={index}><label>Код в источнике<input autoComplete="off" disabled={mutation.busy} value={row.source} onChange={e => { setMapping(list => list.map((m, i) => i === index ? { ...m, source: e.target.value } : m)); setPreview(null) }} /></label><label>Сотрудник DPMS<select disabled={mutation.busy} value={row.user} onChange={e => { setMapping(list => list.map((m, i) => i === index ? { ...m, user: e.target.value } : m)); setPreview(null) }}><option value="">Выберите явно</option>{state.members.filter(m => m.active).map(m => <option key={m.user_id} value={m.user_id}>{m.full_name} · {m.code}</option>)}</select></label><button className="ac-icon" type="button" disabled={mutation.busy} title="Удалить сопоставление" aria-label="Удалить сопоставление" onClick={() => { setMapping(list => list.filter((_, i) => i !== index)); setPreview(null) }}><X size={16} /></button></div>)}<div className="ac-actions"><button type="button" disabled={mutation.busy} onClick={() => { setMapping(rows => [...rows, { source: '', user: '' }]); setPreview(null) }}><Plus size={16} />Сопоставление</button><button type="button" className="ac-primary" disabled={mutation.busy || mutation.stale} onClick={() => void makePreview()}>Предварительный просмотр</button><button type="button" disabled={mutation.busy} onClick={() => { setSource(null); setPreview(null); setMapping([]); setFileName(''); mutation.setError('') }}>Отменить загрузку</button></div></>}
      {source !== null && <><label className="ac-check"><input type="checkbox" disabled={mutation.busy} checked={bootstrap} onChange={e => { setBootstrap(e.target.checked); setPreview(null) }} />Первичное восстановление истории в пустом контуре</label>{bootstrap && <><p className="ac-warning">Сервер проверит пустоту контура. Будут восстановлены baseline и исторические нормы источника. Составы новых групп задаются явно; G21 остаётся с неизвестным составом.</p>{groupMapping.map((row, index) => <div className="ac-form-grid" key={index}><label>Код группы<input disabled={mutation.busy} maxLength={40} value={row.code} onChange={e => { setGroupMapping(list => list.map((g, i) => i === index ? { ...g, code: e.target.value } : g)); setPreview(null) }} /></label>{(['auditor_id', 'tech_id'] as const).map(key => <label key={key}>{key === 'auditor_id' ? 'Аудитор группы' : 'Техспециалист группы'}<select disabled={mutation.busy} value={row[key]} onChange={e => { setGroupMapping(list => list.map((g, i) => i === index ? { ...g, [key]: e.target.value } : g)); setPreview(null) }}><option value="">Выберите явно</option>{state.members.filter(m => m.active && m.role === (key === 'auditor_id' ? 'auditor' : 'tech')).map(m => <option key={m.user_id} value={m.user_id}>{m.full_name}</option>)}</select></label>)}<button type="button" disabled={mutation.busy} onClick={() => { setGroupMapping(list => list.filter((_, i) => i !== index)); setPreview(null) }}>Удалить состав</button></div>)}<button type="button" disabled={mutation.busy} onClick={() => { setGroupMapping(list => [...list, { code: '', auditor_id: '', tech_id: '' }]); setPreview(null) }}><Plus size={16} />Состав группы</button></>}</>}
    </div>
    {mutation.error && <p role="alert" className="ac-error">{mutation.error}</p>}{mutation.stale && <button type="button" onClick={async () => { try { const refreshed = await onRefresh() as CalendarState; setDraftVersion(refreshed.scope.version); mutation.rebase(); setPreview(null) } catch (e) { mutation.setError(errorText(e)) } }}><RefreshCw size={16} />Перечитать данные и повторить preview</button>}{notice && <p role="status">{notice}</p>}
    {preview && <div className="ac-import-preview"><h3>Preview · {preview.status}</h3><dl className="ac-details"><dt>Пакет</dt><dd>{preview.id}</dd><dt>SHA-256</dt><dd>{preview.source_sha256}</dd></dl><pre>{JSON.stringify(preview.summary, null, 2)}</pre>{preview.mapping_required?.length > 0 && <div className="ac-warning"><strong>Требуется сопоставление</strong><pre>{JSON.stringify(preview.mapping_required, null, 2)}</pre></div>}{preview.issues?.length > 0 && <div className="ac-warning"><strong>Замечания</strong><pre>{JSON.stringify(preview.issues, null, 2)}</pre></div>}<details><summary>Строки источника ({preview.rows?.length || 0})</summary><pre>{JSON.stringify(preview.rows, null, 2)}</pre></details><label>Основание переноса<textarea disabled={mutation.busy} required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label><label className="ac-check"><input type="checkbox" disabled={mutation.busy} checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Подтверждаю источник, горизонт истории и сопоставление</label><p className="ac-warning">Применение добавит сведения в общий контур. Оригинал источника и история будут сохранены.</p><button type="button" className="ac-primary" disabled={mutation.busy || mutation.stale || !confirmed || !reason.trim() || !!preview.mapping_required?.length || !!preview.issues?.length || state.scope.archived} onClick={() => void apply()}><Check size={16} />Применить импорт</button></div>}
    <h3>Пакеты импорта</h3>{batches.length ? <div className="ac-table-wrap"><table><thead><tr><th>Пакет</th><th>Статус</th><th>Контрольная сумма</th></tr></thead><tbody>{batches.map(b => <tr key={b.id}><td>{b.id}</td><td>{b.status}</td><td>{b.source_sha256}</td></tr>)}</tbody></table></div> : <p className="ac-empty">Импортированных пакетов нет.</p>}
  </section>
}

export function CalendarRestoreEditor({ plan, state, onClose, onRefresh }: { plan: CalendarPlan; state: CalendarState; onClose: () => void; onRefresh: () => Promise<unknown> }) {
  const [date, setDate] = useState(plan.date)
  const [start, setStart] = useState(plan.start)
  const [duration, setDuration] = useState(plan.duration)
  const [activity, setActivity] = useState(plan.activity)
  const [speaker, setSpeaker] = useState(plan.speaker_id || '')
  const [unknown, setUnknown] = useState(false)
  const [participants, setParticipants] = useState<{ user_id: string; role: CalendarRole }[]>([])
  const [reason, setReason] = useState('')
  const [evidence, setEvidence] = useState('')
  const [outcome, setOutcome] = useState<'completed' | 'cancelled'>('completed')
  const [confirm, setConfirm] = useState(false)
  return <CalendarCommandForm title="Подтверждённый исторический факт" version={state.scope.version} onClose={onClose} onRefresh={onRefresh} validate={() => !confirm ? 'Подтвердите источник и состав.' : !unknown && !participants.length ? 'Укажите реальный состав или явно отметьте неизвестный.' : start + duration > 1440 ? 'Встреча не может переходить через полночь.' : ''} command={() => ({ operation: 'fact.restore', payload: { source_row_id: plan.source_id!, date, start, duration, activity, speaker_id: speaker || null, outcome, reason, evidence, composition_unknown: unknown, participants: unknown ? [] : participants, confirm: true } })}>
    <p className="ac-warning">Группа и горизонт проверяются по исходной строке. Современный состав не подставляется. Факт будет неизменяемым.</p><p className="ac-muted">Источник: {plan.source_id}</p><div className="ac-form-grid"><label>Фактическая дата<input type="date" min={MIN_DATE} max={addDays(state.scope.today, -1)} required value={date} onChange={e => setDate(e.target.value)} /></label><label>Начало<select value={start} onChange={e => setStart(Number(e.target.value))}>{allSlots.map(t => <option key={t} value={t}>{timeLabel(t)}</option>)}</select></label><label>Длительность<input type="number" min={30} step={30} max={1440 - start} required value={duration} onChange={e => setDuration(Number(e.target.value))} /></label></div>
    <label>Активность<input required maxLength={120} value={activity} onChange={e => setActivity(e.target.value)} /></label><label>Докладчик<select value={speaker} onChange={e => setSpeaker(e.target.value)}><option value="">Не установлен</option>{plan.speaker_id && !state.members.some(m => m.user_id === plan.speaker_id) && <option value={plan.speaker_id} disabled>{plan.speaker_id} · сохранён в плане</option>}{state.members.map(m => <option key={m.user_id} value={m.user_id} disabled={!m.active}>{m.full_name}{!m.active ? ' · нет активного допуска' : ''}</option>)}</select></label><label className="ac-check"><input type="checkbox" checked={unknown} onChange={e => setUnknown(e.target.checked)} />Состав не установлен</label>
    {!unknown && <fieldset><legend>Фактический состав</legend>{state.members.map(m => <div className="ac-participant" key={m.user_id}><label className="ac-check"><input type="checkbox" checked={participants.some(p => p.user_id === m.user_id)} onChange={e => setParticipants(list => e.target.checked ? [...list, { user_id: m.user_id, role: m.role }] : list.filter(p => p.user_id !== m.user_id))} />{m.full_name}</label>{participants.some(p => p.user_id === m.user_id) && <select aria-label={`Роль ${m.full_name}`} value={participants.find(p => p.user_id === m.user_id)!.role} onChange={e => setParticipants(list => list.map(p => p.user_id === m.user_id ? { ...p, role: e.target.value as CalendarRole } : p))}>{Object.entries(calendarRoles).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select>}</div>)}</fieldset>}
    <label>Результат<select value={outcome} onChange={e => setOutcome(e.target.value as 'completed' | 'cancelled')}><option value="completed">Проведено</option><option value="cancelled">Отменено</option></select></label><label>Основание<textarea required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label><label>Документ / подтверждение<textarea required maxLength={2000} value={evidence} onChange={e => setEvidence(e.target.value)} /></label><label className="ac-check"><input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)} />Подтверждаю источник и фактические сведения</label>
  </CalendarCommandForm>
}

import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { auditCalendar, type CalendarHistory as HistoryData } from '@/api/auditCalendar'
import { errorText } from '@/lib/auditCalendar'

export function CalendarHistory() {
  const [data, setData] = useState<HistoryData | null>(null)
  const [error, setError] = useState('')
  const [limit, setLimit] = useState(100)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let live = true
    setError('')
    auditCalendar.history(limit).then(result => { if (live) setData(result) }).catch(e => { if (live) setError(errorText(e)) })
    return () => { live = false }
  }, [limit, retry])
  return <section aria-label="Журнал изменений"><header className="ac-section-head"><h2>Журнал изменений</h2><button type="button" className="ac-icon" title="Обновить журнал" aria-label="Обновить журнал" onClick={() => setRetry(r => r + 1)}><RefreshCw size={16} /></button></header>{error && <p className="ac-error" role="alert">{error}</p>}{!data && !error && <p role="status">Загрузка журнала…</p>}{data && <><p className="ac-muted">Показано {data.items.length} из {data.total}</p><div className="ac-table-wrap"><table><thead><tr><th>Москва</th><th>Действие</th><th>Сотрудник</th><th>Подробности</th></tr></thead><tbody>{data.items.map(item => <tr key={item.id}><td>{new Date(item.occurred_at).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })}</td><td>{item.action}</td><td>{item.actor_name}</td><td>{typeof item.detail === 'string' ? item.detail : <details><summary>Данные изменения</summary><pre>{JSON.stringify(item.detail, null, 2)}</pre></details>}</td></tr>)}</tbody></table></div>{!data.items.length && <p className="ac-empty">Изменений пока нет.</p>}{data.items.length < data.total && limit < 1000 && <button type="button" onClick={() => setLimit(n => Math.min(1000, n + 100))}>Показать ещё</button>}</>}</section>
}

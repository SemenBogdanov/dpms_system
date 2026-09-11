import { ChevronDown } from 'lucide-react'
import type { AuditAtomProvenance as Origin } from '@/api/types'

const labels: Record<Origin['kind'], string> = {
  historical_import: 'Историческая загрузка',
  manual_register: 'Ручной реестр',
  manual: 'Вручную',
  ai: 'ИИ',
  unknown: 'Источник не указан',
}

function formatSkillVersion(version: string) {
  return version.startsWith('sha256-') ? `SHA ${version.slice(7, 19)}` : `v${version}`
}

function dateLabel(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ru-RU')
}

export function AuditAtomProvenance({ origins, compact = false }: { origins: Origin[]; compact?: boolean }) {
  const sources: Origin[] = origins.length ? origins : [{ kind: 'unknown' }]
  const content = (
    <ul className="min-w-0 space-y-2 text-xs">
      {sources.map((origin, index) => (
        <li key={`${origin.id ?? origin.registry_item_id ?? origin.kind}-${index}`} className="min-w-0 break-words [overflow-wrap:anywhere]">
          <div className="font-medium text-foreground">{labels[origin.kind] ?? labels.unknown}</div>
          <div className="space-y-0.5 text-muted-foreground">
            {origin.provider_name || origin.model_name ? <p>{origin.provider_name ?? 'Провайдер не указан'} · {origin.model_name ?? 'Модель не указана'}{origin.provider_config_version != null ? ` · конфигурация v${origin.provider_config_version}` : ''}</p> : null}
            {origin.skill_name || origin.skill_slug || origin.skill_version_id ? <p>Методика: {origin.skill_name ?? origin.skill_slug ?? origin.skill_version_id}{origin.skill_version ? ` · ${formatSkillVersion(origin.skill_version)}` : ''}</p> : null}
            {origin.document_id || origin.document_sha256 || origin.document_created_at ? <p title={origin.document_sha256 ?? undefined}>Документ{origin.document_created_at ? ` · ${dateLabel(origin.document_created_at)}` : ''}{origin.document_sha256 ? ` · SHA ${origin.document_sha256.slice(0, 12)}` : ''}</p> : null}
            {origin.source_register_created_at ? <p>Дата реестра: {dateLabel(origin.source_register_created_at)}</p> : null}
            {origin.historical_effective_at ? <p>Историческая дата: {dateLabel(origin.historical_effective_at)}</p> : null}
            {origin.source_sheet || origin.source_row != null ? <p>{origin.source_sheet ?? 'Реестр'}{origin.source_row != null ? ` · строка ${origin.source_row}` : ''}</p> : null}
            {origin.actor_name ? <p>{origin.actor_name}</p> : null}
            {origin.occurred_at || origin.created_at ? <p>{dateLabel((origin.occurred_at ?? origin.created_at)!)}</p> : null}
            {origin.imported_at ? <p>Импорт: {dateLabel(origin.imported_at)}</p> : null}
            {origin.skill_sha256 || origin.document_sha256 || origin.document_version || origin.source_sha256 || origin.document_id || origin.source_register_id || origin.registry_id ? (
              <details>
                <summary className="min-h-11 cursor-pointer py-3 text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">Идентификаторы и SHA-256</summary>
                {origin.skill_sha256 ? <p>SHA методики: <span className="font-mono">{origin.skill_sha256}</span></p> : null}
                {origin.document_sha256 ? <p>SHA документа: <span className="font-mono">{origin.document_sha256}</span></p> : null}
                {origin.source_sha256 ? <p>SHA источника: <span className="font-mono">{origin.source_sha256}</span></p> : null}
                {origin.document_id ? <p>Документ: {origin.document_id}</p> : null}
                {origin.document_version ? <p>Версия документа: {origin.document_version}</p> : null}
                {origin.source_register_id || origin.registry_id ? <p>Реестр: {origin.source_register_id ?? origin.registry_id}</p> : null}
                {origin.registry_item_id ? <p>Элемент: {origin.registry_item_id}</p> : null}
              </details>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  )

  if (!compact) return <section aria-label="Происхождение атома" className="min-w-0 border-t border-border py-3"><h4 className="mb-2 text-xs font-semibold text-foreground">Источник · {sources.length}</h4>{content}</section>

  return (
    <details className="group/origin min-w-0 text-xs">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded text-foreground hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" title="Все источники атома">
        <span className="min-w-0 flex-1 space-y-2 break-words">
          {sources.map((origin, index) => <span key={index} className="block">
            {origin.kind === 'ai' ? <>
              <span className="block font-medium">ИИ · {origin.provider_name ?? 'Провайдер не указан'} · {origin.model_name ?? 'Модель не указана'}</span>
              <span className="block text-muted-foreground">{origin.skill_name ?? origin.skill_slug ?? 'Методика не указана'}{origin.skill_version ? ` · ${formatSkillVersion(origin.skill_version)}` : ''}</span>
            </> : <>
              <span className="block font-medium">{labels[origin.kind] ?? labels.unknown}</span>
              {origin.source_sheet || origin.source_row != null ? <span className="block text-muted-foreground">{origin.source_sheet}{origin.source_row != null ? ` · строка ${origin.source_row}` : ''}</span> : null}
            </>}
          </span>)}
          {sources.length > 1 ? <span className="block text-muted-foreground">Источников: {sources.length}</span> : null}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 group-open/origin:rotate-180" aria-hidden="true" />
      </summary>
      <div className="min-w-0 border-t border-border pt-2">{content}</div>
    </details>
  )
}

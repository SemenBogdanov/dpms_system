import type { CatalogItem, TeamSummary } from '@/api/types'

/** Экспорт Team Summary в CSV с BOM для корректной кириллицы в Excel. */
export function exportTeamCSV(summary: TeamSummary): void {
  const rows = Object.values(summary.by_league).flat()
  const header =
    'ФИО,Лига,Эффективный план,Полный план,Факт (Main),% Выполнения,Карма,В работе (Q),Статус\n'
  const body = rows
    .map((r) =>
      [
        r.full_name,
        r.league,
        Number(r.effective_mpw).toFixed(1),
        r.mpw,
        Number(r.earned).toFixed(1),
        Number(r.percent).toFixed(1),
        Number(r.karma).toFixed(1),
        Number(r.in_progress_q).toFixed(1),
        r.is_at_risk ? 'Отстаёт' : 'OK',
      ]
        .map(csvCell)
        .join(',')
    )
    .join('\n')
  const blob = new Blob(['\ufeff' + header + body], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `dpms-team-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function csvCell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? '' : String(value)
  const safeText = /^[=+\-@\t\r]/.test(text.trimStart()) ? `'${text}` : text
  return `"${safeText.replace(/"/g, '""')}"`
}

function downloadCSV(filename: string, rows: string[]): void {
  const blob = new Blob(['\ufeff' + rows.join('\n') + '\n'], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** CSV-шаблон для пакетного импорта задач. Разделитель `;` удобен для Excel с русской локалью. */
export function exportTaskImportTemplate(): void {
  downloadCSV('dpms-task-import-template.csv', [
    'title;catalog_item_id;catalog_item_name;quantity;description;priority;due_date;tags',
  ])
}

/** Справочник активных операций, чтобы менеджер мог скопировать catalog_item_id в шаблон. */
export function exportTaskImportCatalog(catalog: CatalogItem[]): void {
  const rows = [
    'sort_order;catalog_item_id;catalog_item_name;category;complexity;base_cost_q;min_league',
    ...catalog
      .filter((item) => item.is_active)
      .sort((a, b) => (a.sort_order ?? 100) - (b.sort_order ?? 100) || a.name.localeCompare(b.name, 'ru'))
      .map((item) =>
        [
          csvCell(item.sort_order ?? 100),
          csvCell(item.id),
          csvCell(item.name),
          csvCell(item.category),
          csvCell(item.complexity),
          csvCell(Number(item.base_cost_q).toFixed(1)),
          csvCell(item.min_league),
        ].join(';')
      ),
  ]
  downloadCSV('dpms-active-catalog.csv', rows)
}

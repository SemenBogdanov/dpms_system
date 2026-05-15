import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent, ReactElement } from 'react'
import { Check, FileText, Pencil, Plus, Search, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type {
  KnowledgeArticle,
  KnowledgeArticleCreate,
  KnowledgeArticleUpdate,
  KnowledgeStatus,
} from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/utils'

type SectionOption = {
  id: string
  label: string
}

type KnowledgeFormState = {
  slug: string
  title: string
  summary: string
  section: string
  body: string
  status: KnowledgeStatus
  sort_order: string
}

const SECTION_OPTIONS: SectionOption[] = [
  { id: 'start', label: 'Начать здесь' },
  { id: 'tasks', label: 'Задачи' },
  { id: 'rules', label: 'Правила' },
  { id: 'general', label: 'Общее' },
]

const EMPTY_FORM: KnowledgeFormState = {
  slug: '',
  title: '',
  summary: '',
  section: 'general',
  body: '',
  status: 'draft',
  sort_order: '100',
}

const statusLabel: Record<KnowledgeStatus, string> = {
  draft: 'Черновик',
  published: 'Опубликована',
}

function sectionLabel(section: string): string {
  return SECTION_OPTIONS.find((item) => item.id === section)?.label ?? section
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date)
}

function renderKnowledgeBody(body: string): ReactElement[] {
  const nodes: ReactElement[] = []
  let paragraph: string[] = []
  let unordered: string[] = []
  let ordered: string[] = []

  const flushParagraph = () => {
    if (!paragraph.length) return
    nodes.push(
      <p key={`p-${nodes.length}`} className="text-sm leading-7 text-slate-700">
        {paragraph.join(' ')}
      </p>
    )
    paragraph = []
  }

  const flushUnordered = () => {
    if (!unordered.length) return
    nodes.push(
      <ul key={`ul-${nodes.length}`} className="list-disc space-y-1 pl-5 text-sm leading-7 text-slate-700">
        {unordered.map((item, index) => (
          <li key={`${item}-${index}`}>{item}</li>
        ))}
      </ul>
    )
    unordered = []
  }

  const flushOrdered = () => {
    if (!ordered.length) return
    nodes.push(
      <ol key={`ol-${nodes.length}`} className="list-decimal space-y-1 pl-5 text-sm leading-7 text-slate-700">
        {ordered.map((item, index) => (
          <li key={`${item}-${index}`}>{item}</li>
        ))}
      </ol>
    )
    ordered = []
  }

  const flushLists = () => {
    flushUnordered()
    flushOrdered()
  }

  body.split(/\r?\n/).forEach((rawLine) => {
    const line = rawLine.trim()
    if (!line) {
      flushParagraph()
      flushLists()
      return
    }
    if (line.startsWith('## ')) {
      flushParagraph()
      flushLists()
      nodes.push(
        <h2 key={`h-${nodes.length}`} className="pt-3 text-base font-semibold text-slate-900">
          {line.replace(/^##\s+/, '')}
        </h2>
      )
      return
    }
    if (line.startsWith('- ')) {
      flushParagraph()
      flushOrdered()
      unordered.push(line.slice(2).trim())
      return
    }
    const orderedMatch = line.match(/^\d+\.\s+(.+)$/)
    if (orderedMatch) {
      flushParagraph()
      flushUnordered()
      ordered.push(orderedMatch[1])
      return
    }
    flushLists()
    paragraph.push(line)
  })

  flushParagraph()
  flushLists()
  return nodes
}

export function KnowledgePage() {
  const { user } = useAuth()
  const isManager = user?.role === 'admin' || user?.role === 'teamlead'
  const [articles, setArticles] = useState<KnowledgeArticle[]>([])
  const [selectedSlug, setSelectedSlug] = useState('')
  const [sectionFilter, setSectionFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState<'all' | KnowledgeStatus>('all')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editorArticle, setEditorArticle] = useState<KnowledgeArticle | null>(null)
  const [form, setForm] = useState<KnowledgeFormState>(EMPTY_FORM)

  const loadArticles = useCallback(() => {
    const params: Record<string, string> = {}
    if (sectionFilter !== 'all') params.section = sectionFilter
    if (isManager && statusFilter !== 'all') params.status = statusFilter
    if (search.trim()) params.search = search.trim()
    setLoading(true)
    setError(null)
    api
      .get<KnowledgeArticle[]>('/api/knowledge', params)
      .then(setArticles)
      .catch((e) => {
        setError(e instanceof Error ? e.message : 'Ошибка загрузки базы знаний')
        setArticles([])
      })
      .finally(() => setLoading(false))
  }, [isManager, search, sectionFilter, statusFilter])

  useEffect(() => {
    loadArticles()
  }, [loadArticles])

  useEffect(() => {
    if (!articles.length) {
      setSelectedSlug('')
      return
    }
    if (articles.some((article) => article.slug === selectedSlug)) return
    const startArticle = articles.find((article) => article.section === 'start')
    setSelectedSlug(startArticle?.slug ?? articles[0].slug)
  }, [articles, selectedSlug])

  const selectedArticle = useMemo(
    () => articles.find((article) => article.slug === selectedSlug) ?? articles[0] ?? null,
    [articles, selectedSlug]
  )

  const pinnedArticles = useMemo(
    () => articles.filter((article) => article.section === 'start').slice(0, 3),
    [articles]
  )

  const availableSections = useMemo(() => {
    const known = new Set(SECTION_OPTIONS.map((section) => section.id))
    articles.forEach((article) => known.add(article.section))
    return Array.from(known)
  }, [articles])

  const openEditor = (article: KnowledgeArticle | null) => {
    setEditorArticle(article)
    setForm(
      article
        ? {
            slug: article.slug,
            title: article.title,
            summary: article.summary,
            section: article.section,
            body: article.body,
            status: article.status,
            sort_order: String(article.sort_order),
          }
        : EMPTY_FORM
    )
    setEditorOpen(true)
  }

  const closeEditor = () => {
    setEditorOpen(false)
    setEditorArticle(null)
    setForm(EMPTY_FORM)
  }

  const handleSave = (event: FormEvent) => {
    event.preventDefault()
    const title = form.title.trim()
    const body = form.body.trim()
    const sortOrder = Number.parseInt(form.sort_order, 10)
    if (!title || !body || Number.isNaN(sortOrder)) {
      toast.error('Заполните название, текст и порядок')
      return
    }

    setSaving(true)
    const payload: KnowledgeArticleCreate = {
      slug: form.slug.trim() || null,
      title,
      summary: form.summary.trim(),
      section: form.section.trim() || 'general',
      body,
      status: form.status,
      sort_order: sortOrder,
    }
    const request = editorArticle
      ? api.patch<KnowledgeArticle>(`/api/knowledge/${editorArticle.id}`, payload as KnowledgeArticleUpdate)
      : api.post<KnowledgeArticle>('/api/knowledge', payload)

    request
      .then((article) => {
        toast.success(editorArticle ? 'Статья обновлена' : 'Статья создана')
        setSelectedSlug(article.slug)
        closeEditor()
        loadArticles()
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка сохранения'))
      .finally(() => setSaving(false))
  }

  const publishArticle = (article: KnowledgeArticle) => {
    setSaving(true)
    api
      .patch<KnowledgeArticle>(`/api/knowledge/${article.id}`, { status: 'published' })
      .then((updated) => {
        toast.success('Статья опубликована')
        setSelectedSlug(updated.slug)
        loadArticles()
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка публикации'))
      .finally(() => setSaving(false))
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">База знаний</h1>
          <p className="mt-1 text-sm text-slate-500">Операционные правила и входной бриф команды</p>
        </div>
        {isManager && (
          <button
            type="button"
            onClick={() => openEditor(null)}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            disabled={saving}
          >
            <Plus className="h-4 w-4" />
            Добавить статью
          </button>
        )}
      </div>

      {pinnedArticles.length > 0 && (
        <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" aria-labelledby="knowledge-start-title">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="knowledge-start-title" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Начать здесь
            </h2>
            <span className="text-xs text-slate-400">{pinnedArticles.length} материал</span>
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {pinnedArticles.map((article) => (
              <button
                key={article.id}
                type="button"
                onClick={() => setSelectedSlug(article.slug)}
                className={cn(
                  'rounded-lg border p-3 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-primary/40',
                  selectedSlug === article.slug
                    ? 'border-primary/50 bg-accent-lighter text-slate-900'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50'
                )}
              >
                <span className="block text-sm font-medium">{article.title}</span>
                <span className="mt-1 line-clamp-2 block text-xs leading-5 text-slate-500">{article.summary}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="rounded-lg border border-slate-200 bg-white shadow-sm" aria-label="Список статей">
          <div className="space-y-3 border-b border-slate-200 p-4">
            <label className="relative block">
              <span className="sr-only">Поиск по базе знаний</span>
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Поиск"
                className="w-full rounded-md border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </label>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-1">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">Раздел</span>
                <select
                  value={sectionFilter}
                  onChange={(e) => setSectionFilter(e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                >
                  <option value="all">Все разделы</option>
                  {availableSections.map((section) => (
                    <option key={section} value={section}>
                      {sectionLabel(section)}
                    </option>
                  ))}
                </select>
              </label>
              {isManager && (
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">Статус</span>
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value as 'all' | KnowledgeStatus)}
                    className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                  >
                    <option value="all">Все статусы</option>
                    <option value="published">Опубликованные</option>
                    <option value="draft">Черновики</option>
                  </select>
                </label>
              )}
            </div>
          </div>

          <div className="max-h-[calc(100vh-290px)] min-h-[280px] overflow-y-auto p-2">
            {loading && <p className="p-3 text-sm text-slate-500">Загрузка...</p>}
            {error && <p className="p-3 text-sm text-red-600">{error}</p>}
            {!loading && !error && articles.length === 0 && (
              <p className="p-3 text-sm text-slate-500">Материалы не найдены</p>
            )}
            {articles.map((article) => (
              <button
                key={article.id}
                type="button"
                onClick={() => setSelectedSlug(article.slug)}
                className={cn(
                  'mb-2 w-full rounded-lg border p-3 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-primary/40',
                  selectedArticle?.id === article.id
                    ? 'border-primary/50 bg-accent-lighter'
                    : 'border-transparent hover:border-slate-200 hover:bg-slate-50'
                )}
              >
                <span className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-slate-900">{article.title}</span>
                  {isManager && (
                    <span
                      className={cn(
                        'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium',
                        article.status === 'published'
                          ? 'bg-emerald-50 text-emerald-700'
                          : 'bg-amber-50 text-amber-700'
                      )}
                    >
                      {statusLabel[article.status]}
                    </span>
                  )}
                </span>
                <span className="mt-1 block text-xs text-slate-500">{sectionLabel(article.section)}</span>
                <span className="mt-2 line-clamp-2 block text-xs leading-5 text-slate-500">{article.summary}</span>
              </button>
            ))}
          </div>
        </aside>

        <section className="min-h-[520px] rounded-lg border border-slate-200 bg-white shadow-sm" aria-live="polite">
          {selectedArticle ? (
            <article className="flex h-full flex-col">
              <header className="border-b border-slate-200 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">
                        <FileText className="h-3.5 w-3.5" />
                        {sectionLabel(selectedArticle.section)}
                      </span>
                      {isManager && (
                        <span
                          className={cn(
                            'rounded-full px-2 py-1 text-xs font-medium',
                            selectedArticle.status === 'published'
                              ? 'bg-emerald-50 text-emerald-700'
                              : 'bg-amber-50 text-amber-700'
                          )}
                        >
                          {statusLabel[selectedArticle.status]}
                        </span>
                      )}
                    </div>
                    <h2 className="text-xl font-semibold text-slate-900">{selectedArticle.title}</h2>
                    {selectedArticle.summary && (
                      <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">{selectedArticle.summary}</p>
                    )}
                  </div>
                  {isManager && (
                    <div className="flex shrink-0 flex-wrap gap-2">
                      {selectedArticle.status === 'draft' && (
                        <button
                          type="button"
                          onClick={() => publishArticle(selectedArticle)}
                          disabled={saving}
                          className="inline-flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
                        >
                          <Check className="h-4 w-4" />
                          Опубликовать
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => openEditor(selectedArticle)}
                        className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                      >
                        <Pencil className="h-4 w-4" />
                        Редактировать
                      </button>
                    </div>
                  )}
                </div>
              </header>
              <div className="flex-1 space-y-4 p-5">{renderKnowledgeBody(selectedArticle.body)}</div>
              <footer className="border-t border-slate-200 px-5 py-3 text-xs text-slate-400">
                Обновлено: {formatDate(selectedArticle.updated_at)}
              </footer>
            </article>
          ) : (
            <div className="flex h-full min-h-[520px] items-center justify-center p-6 text-sm text-slate-500">
              Выберите материал
            </div>
          )}
        </section>
      </div>

      {editorOpen && isManager && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="knowledge-editor-title"
          onKeyDown={(e) => e.key === 'Escape' && closeEditor()}
        >
          <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h2 id="knowledge-editor-title" className="text-lg font-semibold text-slate-900">
                {editorArticle ? 'Редактировать статью' : 'Новая статья'}
              </h2>
              <button
                type="button"
                onClick={closeEditor}
                className="rounded-md p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                aria-label="Закрыть"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleSave} className="space-y-4 p-5">
              <div className="grid gap-4 md:grid-cols-[1fr_180px]">
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Название</span>
                  <input
                    type="text"
                    value={form.title}
                    onChange={(e) => setForm((current) => ({ ...current, title: e.target.value }))}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                    required
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Порядок</span>
                  <input
                    type="number"
                    value={form.sort_order}
                    onChange={(e) => setForm((current) => ({ ...current, sort_order: e.target.value }))}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                    required
                  />
                </label>
              </div>
              <div className="grid gap-4 md:grid-cols-3">
                <label className="block md:col-span-1">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Раздел</span>
                  <input
                    list="knowledge-section-options"
                    value={form.section}
                    onChange={(e) => setForm((current) => ({ ...current, section: e.target.value }))}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                    required
                  />
                  <datalist id="knowledge-section-options">
                    {SECTION_OPTIONS.map((section) => (
                      <option key={section.id} value={section.id}>{section.label}</option>
                    ))}
                  </datalist>
                </label>
                <label className="block md:col-span-1">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Статус</span>
                  <select
                    value={form.status}
                    onChange={(e) => setForm((current) => ({ ...current, status: e.target.value as KnowledgeStatus }))}
                    className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                  >
                    <option value="draft">Черновик</option>
                    <option value="published">Опубликована</option>
                  </select>
                </label>
                <label className="block md:col-span-1">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Slug</span>
                  <input
                    type="text"
                    value={form.slug}
                    onChange={(e) => setForm((current) => ({ ...current, slug: e.target.value }))}
                    className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                </label>
              </div>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700">Краткое описание</span>
                <textarea
                  value={form.summary}
                  onChange={(e) => setForm((current) => ({ ...current, summary: e.target.value }))}
                  rows={2}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700">Текст</span>
                <textarea
                  value={form.body}
                  onChange={(e) => setForm((current) => ({ ...current, body: e.target.value }))}
                  rows={14}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm leading-6 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                  required
                />
              </label>
              <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
                <button
                  type="button"
                  onClick={closeEditor}
                  className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Отмена
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {saving ? 'Сохранение...' : 'Сохранить'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

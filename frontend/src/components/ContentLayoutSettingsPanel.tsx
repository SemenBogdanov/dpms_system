import { useEffect, useId, useRef, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import type { User } from '@/api/types'
import { useContentLayoutPreferences } from '@/hooks/useContentLayoutPreferences'
import {
  DEFAULT_CONTENT_LAYOUT_PREFERENCE,
  MAX_CONTENT_MARGIN,
  getContentLayoutSections,
  type ContentLayoutPreference,
} from '@/lib/contentLayout'

type ContentLayoutSettingsRowProps = {
  section: ReturnType<typeof getContentLayoutSections>[number]
  preference: ContentLayoutPreference | undefined
  setPreference: (id: string, value: ContentLayoutPreference) => boolean
  resetPreference: (id: string) => boolean
}

type SaveFeedback = {
  message: string
  temporaryOnly: boolean
}

function ContentLayoutSettingsRow({
  section,
  preference,
  setPreference,
  resetPreference,
}: ContentLayoutSettingsRowProps) {
  const rowId = useId()
  const sectionLabelId = `${rowId}-section`
  const marginInputId = `${rowId}-margin`
  const errorId = `${rowId}-error`
  const feedbackId = `${rowId}-feedback`
  const defaultStateId = `${rowId}-default`
  const isDefault = preference === undefined
  const { fullWidth, marginPercent } = preference ?? DEFAULT_CONTENT_LAYOUT_PREFERENCE
  const [marginDraft, setMarginDraft] = useState(() => String(marginPercent))
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<SaveFeedback | null>(null)
  const marginDirtyRef = useRef(false)
  const fullWidthRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (fullWidthRef.current) fullWidthRef.current.indeterminate = isDefault
  }, [isDefault])

  useEffect(() => {
    setMarginDraft(String(marginPercent))
    marginDirtyRef.current = false
    setError(null)
  }, [fullWidth, marginPercent, isDefault])

  const reportResult = (durable: boolean, successMessage: string, adjustment?: string) => {
    const result = durable ? successMessage : 'Применено только в этой вкладке'
    setFeedback({
      message: adjustment ? `${adjustment}. ${result}` : result,
      temporaryOnly: !durable,
    })
  }

  const changeFullWidth = (checked: boolean) => {
    const nextPreference = {
      fullWidth: checked,
      marginPercent: checked ? marginPercent : DEFAULT_CONTENT_LAYOUT_PREFERENCE.marginPercent,
    }
    const durable = setPreference(section.id, nextPreference)
    setMarginDraft(String(nextPreference.marginPercent))
    marginDirtyRef.current = false
    setError(null)
    reportResult(durable, 'Сохранено')
  }

  const commitMargin = (input: HTMLInputElement) => {
    if (fullWidth || !marginDirtyRef.current) return

    const value = input.valueAsNumber
    if (!input.value.trim() || !Number.isFinite(value)) {
      setError(`Введите число от 0 до ${MAX_CONTENT_MARGIN}.`)
      return
    }

    const normalized = Math.round(Math.min(MAX_CONTENT_MARGIN, Math.max(0, value)) * 10) / 10
    const adjustment = value < 0 || value > MAX_CONTENT_MARGIN
      ? `Отступы ограничены до ${normalized}%`
      : normalized !== value
        ? `Отступы округлены до ${normalized}%`
        : undefined
    const durable = setPreference(section.id, { fullWidth: false, marginPercent: normalized })
    setMarginDraft(String(normalized))
    marginDirtyRef.current = false
    setError(null)
    reportResult(durable, 'Сохранено', adjustment)
  }

  const reset = () => {
    const durable = resetPreference(section.id)
    setMarginDraft(String(DEFAULT_CONTENT_LAYOUT_PREFERENCE.marginPercent))
    marginDirtyRef.current = false
    setError(null)
    reportResult(durable, 'Восстановлено по умолчанию')
  }

  return (
    <div
      role="group"
      aria-labelledby={sectionLabelId}
      className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2.75rem] items-center gap-x-3 gap-y-2 py-3 sm:grid-cols-[minmax(0,1fr)_10rem_9rem_2.75rem]"
    >
      <div className="col-span-3 min-w-0 sm:col-span-1">
        <h3 id={sectionLabelId} className="break-words text-sm font-medium text-slate-900 [overflow-wrap:anywhere] dark:text-slate-100">
          {section.label}
        </h3>
        {isDefault && (
          <p id={defaultStateId} className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">По умолчанию</p>
        )}
      </div>

      <label className="flex min-h-11 min-w-0 cursor-pointer items-center gap-2 self-end text-sm text-slate-700 dark:text-slate-200">
        <input
          ref={fullWidthRef}
          type="checkbox"
          name={`content-width-${section.id}`}
          checked={!isDefault && fullWidth}
          aria-describedby={isDefault ? defaultStateId : undefined}
          onChange={(event) => changeFullWidth(event.currentTarget.checked)}
          className="h-4 w-4 shrink-0 rounded accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-900"
        />
        <span>
          Во весь экран<span className="sr-only">: {section.label}</span>
        </span>
      </label>

      <div className="min-w-0 self-end">
        <label htmlFor={marginInputId} className="mb-1 block text-xs text-slate-500 dark:text-slate-400">
          Отступы<span className="sr-only"> с каждой стороны, в процентах: {section.label}</span>
        </label>
        <div className="flex min-w-0 items-center gap-1.5">
          <input
            id={marginInputId}
            type="number"
            name={`content-margin-${section.id}`}
            autoComplete="off"
            inputMode="decimal"
            step={0.1}
            min={0}
            max={MAX_CONTENT_MARGIN}
            disabled={fullWidth}
            value={marginDraft}
            aria-invalid={Boolean(error)}
            aria-describedby={[error ? errorId : '', feedback ? feedbackId : ''].filter(Boolean).join(' ') || undefined}
            onChange={(event) => {
              marginDirtyRef.current = true
              setMarginDraft(event.currentTarget.value)
              setError(null)
              setFeedback((current) => current?.temporaryOnly ? current : null)
            }}
            onBlur={(event) => commitMargin(event.currentTarget)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                event.preventDefault()
                commitMargin(event.currentTarget)
              }
            }}
            className={`h-11 min-w-0 w-full rounded-md border bg-white px-2 text-base tabular-nums text-slate-900 outline-none focus:border-primary focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 sm:text-sm dark:bg-slate-900 dark:text-slate-100 dark:disabled:bg-slate-800 dark:disabled:text-slate-400 ${error ? 'border-rose-500 dark:border-rose-400' : 'border-slate-300 dark:border-slate-600'}`}
          />
          <span aria-hidden="true" className="shrink-0 text-sm text-slate-500 dark:text-slate-400">%</span>
        </div>
      </div>

      <button
        type="button"
        onClick={reset}
        disabled={isDefault}
        aria-label={`Сбросить настройки раздела: ${section.label}`}
        title={`Сбросить настройки раздела: ${section.label}`}
        className="inline-flex h-11 w-11 items-center justify-center self-end rounded-md text-slate-500 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-300 dark:hover:bg-slate-800"
      >
        <RotateCcw aria-hidden="true" className="h-4 w-4" />
      </button>

      {error && (
        <p id={errorId} role="alert" className="col-span-3 min-w-0 text-xs text-rose-600 [overflow-wrap:anywhere] sm:col-span-4 dark:text-rose-400">
          {error}
        </p>
      )}
      <p
        id={feedbackId}
        role="status"
        aria-atomic="true"
        className={`col-span-3 min-w-0 text-xs [overflow-wrap:anywhere] sm:col-span-4 ${feedback ? '' : 'sr-only'} ${feedback?.temporaryOnly ? 'text-amber-700 dark:text-amber-300' : 'text-slate-500 dark:text-slate-400'}`}
      >
        {feedback?.message}
      </p>
    </div>
  )
}

export function ContentLayoutSettingsPanel({ user }: { user: User }) {
  const headingId = useId()
  const { preferences, setPreference, resetPreference } = useContentLayoutPreferences(user.id)
  const sections = getContentLayoutSections(user)

  return (
    <section aria-labelledby={headingId} className="min-w-0 w-full">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id={headingId} className="font-semibold text-slate-900 dark:text-slate-100">Визуализация</h2>
        <span className="text-xs text-slate-500 dark:text-slate-400">Этот браузер</span>
      </div>
      <div className="divide-y divide-slate-200 border-y border-slate-200 dark:divide-slate-700 dark:border-slate-700">
        {sections.map((section) => (
          <ContentLayoutSettingsRow
            key={`${user.id}:${section.id}`}
            section={section}
            preference={preferences[section.id]}
            setPreference={setPreference}
            resetPreference={resetPreference}
          />
        ))}
      </div>
    </section>
  )
}

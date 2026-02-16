interface ProactiveBlockProps {
  onShowProactive: () => void
  loading?: boolean
}

/** Блок при пустой основной очереди: предложение посмотреть проактивные задачи. */
export function ProactiveBlock({ onShowProactive, loading }: ProactiveBlockProps) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
      <h2 className="text-lg font-semibold text-slate-900">✅ Очередь задач пуста!</h2>
      <p className="mt-2 text-slate-600">
        Доступные проактивные направления: техдолг, документация, исследование, менторинг.
      </p>
      <button
        type="button"
        onClick={onShowProactive}
        disabled={loading}
        className="mt-4 rounded-lg bg-violet-100 px-4 py-2 text-sm font-medium text-violet-800 hover:bg-violet-200 disabled:opacity-50"
      >
        {loading ? '...' : 'Показать проактивные задачи'}
      </button>
    </div>
  )
}

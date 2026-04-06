interface ProactiveBlockProps {
  onShowProactive: () => void
  loading?: boolean
}

export function ProactiveBlock({ onShowProactive, loading }: ProactiveBlockProps) {
  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-8 text-center">
      <h2 className="text-lg font-semibold text-gray-700">Очередь задач пуста</h2>
      <p className="mt-2 text-gray-400">
        Доступные проактивные направления: техдолг, документация, исследование, менторинг.
      </p>
      <button
        type="button"
        onClick={onShowProactive}
        disabled={loading}
        className="mt-4 rounded-xl bg-accent px-5 py-2 text-sm font-medium text-white hover:bg-accent-dark disabled:opacity-50 transition-colors"
      >
        {loading ? '...' : 'Показать проактивные задачи'}
      </button>
    </div>
  )
}

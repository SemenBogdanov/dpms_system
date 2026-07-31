import { RefreshCw, WifiOff } from 'lucide-react'

type AuthConnectionErrorProps = {
  message: string
  onRetry: () => void
}

export function AuthConnectionError({ message, onRetry }: AuthConnectionErrorProps) {
  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-background p-4">
      <section className="w-full max-w-md border border-border bg-surface p-5 shadow-sm">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-100 text-amber-700">
            <WifiOff className="h-5 w-5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-foreground">Нет связи с системой</h1>
            <p className="mt-1 text-sm leading-5 text-muted-foreground">{message}</p>
          </div>
        </div>

        <button
          type="button"
          onClick={onRetry}
          className="mt-5 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Повторить подключение
        </button>

        <a
          href="/mobile-probe.html"
          className="mt-3 block min-h-11 py-3 text-center text-sm font-medium text-primary hover:underline"
        >
          Проверить доступность сервера
        </a>
      </section>
    </div>
  )
}

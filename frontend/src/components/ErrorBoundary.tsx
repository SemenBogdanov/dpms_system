import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

/** Глобальный Error Boundary: при ошибке рендеринга показываем карточку вместо белого экрана. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('ErrorBoundary caught:', error, errorInfo)
  }

  render(): ReactNode {
    if (this.state.hasError && this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-slate-100 p-6">
          <div className="w-full max-w-md rounded-xl border border-red-200 bg-white p-6 shadow-lg">
            <h1 className="text-lg font-semibold text-red-800">Что-то пошло не так</h1>
            <p className="mt-2 text-slate-600">
              Попробуйте обновить страницу. Если ошибка повторяется — обратитесь в поддержку.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              Обновить страницу
            </button>
            <details className="mt-4 text-left">
              <summary className="cursor-pointer text-sm text-slate-500">Подробности (для отладки)</summary>
              <pre className="mt-2 overflow-auto rounded bg-slate-100 p-2 text-xs text-red-700">
                {this.state.error.message}
                {'\n'}
                {this.state.error.stack}
              </pre>
            </details>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

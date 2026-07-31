import { useEffect, useRef, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'

const focusableSelector = [
  '[autofocus]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'a[href]',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function useProtectedModal<T extends HTMLElement>(): RefObject<T> {
  const panelRef = useRef<T>(null)

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    const scrollOwner = document.querySelector<HTMLElement>('.app-main')
    const previousScrollOwnerOverflow = scrollOwner?.style.overflow
    document.body.style.overflow = 'hidden'
    if (scrollOwner) scrollOwner.style.overflow = 'hidden'

    const focusFrame = window.requestAnimationFrame(() => {
      const panel = panelRef.current
      const coarsePointer = window.matchMedia('(pointer: coarse)').matches
      const preferred = coarsePointer ? null : panel?.querySelector<HTMLElement>('[autofocus]')
      const first = panel?.querySelector<HTMLElement>(focusableSelector)
      ;(preferred || first || panel)?.focus()
    })

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        return
      }
      if (event.key !== 'Tab' || !panelRef.current) return

      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(focusableSelector),
      ).filter((element) => element.offsetParent !== null)
      if (focusable.length === 0) {
        event.preventDefault()
        panelRef.current.focus()
        return
      }

      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
      if (scrollOwner) scrollOwner.style.overflow = previousScrollOwnerOverflow || ''
      previousFocus?.focus()
    }
  }, [])

  return panelRef
}

export function preventBackdropDismiss(event: ReactPointerEvent<HTMLElement>) {
  if (event.target === event.currentTarget) event.preventDefault()
}

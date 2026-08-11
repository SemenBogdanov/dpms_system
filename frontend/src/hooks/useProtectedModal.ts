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

export function useProtectedModal<T extends HTMLElement>(active = true): RefObject<T> {
  const panelRef = useRef<T>(null)

  useEffect(() => {
    if (!active) return

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

      const currentIndex = focusable.indexOf(document.activeElement as HTMLElement)
      const nextIndex = event.shiftKey
        ? (currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1)
        : (currentIndex < 0 || currentIndex === focusable.length - 1 ? 0 : currentIndex + 1)
      event.preventDefault()
      focusable[nextIndex].focus()
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
      if (scrollOwner) scrollOwner.style.overflow = previousScrollOwnerOverflow || ''
      previousFocus?.focus()
    }
  }, [active])

  return panelRef
}

export function preventBackdropDismiss(event: ReactPointerEvent<HTMLElement>) {
  if (event.target === event.currentTarget) event.preventDefault()
}

import { useEffect, useRef, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'

const focusableSelector = [
  '[autofocus]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'a[href]',
  'summary',
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

const panels: HTMLElement[] = []
const inertBefore = new Map<HTMLElement, boolean>()
let unlockScroll: (() => void) | undefined

function topPanel() {
  const leaves = panels.filter((panel) => !panels.some((other) => panel !== other && panel.contains(other)))
  return leaves[leaves.length - 1]
}

function isolateTopPanel() {
  inertBefore.forEach((inert, element) => { element.inert = inert })
  inertBefore.clear()
  let child = topPanel()
  while (child?.parentElement) {
    for (const sibling of Array.from(child.parentElement.children)) {
      if (sibling === child || !(sibling instanceof HTMLElement)) continue
      inertBefore.set(sibling, sibling.inert)
      sibling.inert = true
    }
    child = child.parentElement
    if (child === document.body) break
  }
}

function availableFocus(element: Element | null, panel: HTMLElement): element is HTMLElement {
  if (!(element instanceof HTMLElement) || !panel.contains(element)) return false
  if (element.matches(':disabled') || element.closest('[inert]')) return false
  if (!element.getClientRects().length || ['hidden', 'collapse'].includes(getComputedStyle(element).visibility)) return false
  let parent = element.parentElement
  while (parent && parent !== panel) {
    if (parent instanceof HTMLDetailsElement && !parent.open && !parent.querySelector('summary')?.contains(element)) return false
    parent = parent.parentElement
  }
  return true
}

function focusableElements(panel: HTMLElement) {
  return Array.from(panel.querySelectorAll<HTMLElement>(focusableSelector))
    .filter((element) => element.tabIndex >= 0 && availableFocus(element, panel))
}

export function useProtectedModal<T extends HTMLElement>(active = true, options?: { onEscape?: () => void }): RefObject<T> {
  const panelRef = useRef<T>(null)
  const escapeRef = useRef(options?.onEscape)
  escapeRef.current = options?.onEscape

  useEffect(() => {
    const panel = panelRef.current
    if (!active || !panel) return

    const previousFocus = document.activeElement as HTMLElement | null
    const previousTabIndex = panel.getAttribute('tabindex')
    if (previousTabIndex === null) panel.tabIndex = -1
    if (panels.length === 0) {
      const previousOverflow = document.body.style.overflow
      const scrollOwner = document.querySelector<HTMLElement>('.app-main')
      const previousScrollOwnerOverflow = scrollOwner?.style.overflow
      document.body.style.overflow = 'hidden'
      if (scrollOwner) scrollOwner.style.overflow = 'hidden'
      unlockScroll = () => {
        document.body.style.overflow = previousOverflow
        if (scrollOwner) scrollOwner.style.overflow = previousScrollOwnerOverflow || ''
      }
    }
    panels.push(panel)
    isolateTopPanel()

    let tabTarget: HTMLElement | undefined
    let tabTimer: number | undefined
    const restoreFocus = () => {
      if (topPanel() !== panel || !panel.isConnected || availableFocus(document.activeElement, panel)) return
      const target = availableFocus(tabTarget ?? null, panel) ? tabTarget : focusableElements(panel)[0]
      ;(target || panel).focus()
    }
    const finishTab = () => {
      window.clearTimeout(tabTimer)
      tabTimer = undefined
      restoreFocus()
      tabTarget = undefined
    }

    const focusFrame = window.requestAnimationFrame(() => {
      if (topPanel() !== panel) return
      // Do not steal focus if the user already entered the dialog before this frame.
      if (availableFocus(document.activeElement, panel)) return
      const coarsePointer = window.matchMedia('(pointer: coarse)').matches
      const focusable = focusableElements(panel)
      const preferred = coarsePointer ? null : focusable.find((element) => element.hasAttribute('autofocus'))
      const first = focusable[0]
      ;(preferred || first || panel)?.focus()
    })

    const handleKeyDown = (event: KeyboardEvent) => {
      if (topPanel() !== panel) return
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        escapeRef.current?.()
        return
      }
      if (event.key !== 'Tab' || !panelRef.current) return
      window.clearTimeout(tabTimer)
      tabTarget = undefined

      const focusable = focusableElements(panel)
      if (focusable.length === 0) {
        event.preventDefault()
        panelRef.current.focus()
        return
      }

      const currentIndex = focusable.indexOf(document.activeElement as HTMLElement)
      // Preserve native Tab behavior except when wrapping at the boundaries.
      if (currentIndex >= 0 && (event.shiftKey ? currentIndex > 0 : currentIndex < focusable.length - 1)) {
        tabTarget = focusable[currentIndex + (event.shiftKey ? -1 : 1)]
        // WebKit can skip buttons and land on body without emitting focusin.
        tabTimer = window.setTimeout(finishTab, 0)
        return
      }
      event.preventDefault()
      focusable[event.shiftKey ? focusable.length - 1 : 0].focus()
    }

    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.key === 'Tab') finishTab()
    }
    // Disabling a focused fieldset or removing its control need not emit focusin.
    const observer = new MutationObserver(restoreFocus)
    observer.observe(panel, {
      subtree: true, childList: true, attributes: true,
      attributeFilter: ['disabled', 'hidden', 'inert', 'style', 'class', 'open', 'tabindex'],
    })
    document.addEventListener('keydown', handleKeyDown, true)
    document.addEventListener('keyup', handleKeyUp, true)
    document.addEventListener('focusin', restoreFocus)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      window.clearTimeout(tabTimer)
      observer.disconnect()
      document.removeEventListener('keydown', handleKeyDown, true)
      document.removeEventListener('keyup', handleKeyUp, true)
      document.removeEventListener('focusin', restoreFocus)
      panels.splice(panels.indexOf(panel), 1)
      isolateTopPanel()
      if (panels.length === 0) {
        unlockScroll?.()
        unlockScroll = undefined
      }
      if (previousTabIndex === null && panel.getAttribute('tabindex') === '-1') panel.removeAttribute('tabindex')
      if (previousFocus?.isConnected && !previousFocus.closest('[inert]')) previousFocus.focus()
    }
  }, [active])

  return panelRef
}

export function preventBackdropDismiss(event: ReactPointerEvent<HTMLElement>) {
  if (event.target === event.currentTarget) event.preventDefault()
}

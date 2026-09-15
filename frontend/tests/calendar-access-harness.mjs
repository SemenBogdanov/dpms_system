import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import * as React from 'react'

const require = createRequire(import.meta.url)

export function loadSource(path, overrides = {}, globals = {}) {
  const source = readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
    },
    fileName: fileURLToPath(new URL(`../${path}`, import.meta.url)),
  }).outputText
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', ...Object.keys(globals), compiled)(
    (id) => {
      if (Object.hasOwn(overrides, id)) return overrides[id]
      if (!['react', 'react/jsx-runtime', 'lucide-react'].includes(id)) {
        throw new Error(`Unmocked dependency: ${id}`)
      }
      return require(id)
    }, mod, mod.exports, ...Object.values(globals),
  )
  return mod.exports
}

// Deterministic hook boundary: exercise component callbacks without DOM, ports,
// real storage, or network. Rendering/effect flushing is explicit in each test.
export function hookHarness() {
  const slots = []
  let cursor = 0
  let pending = []
  const changed = (before, after) => !before || !after
    || before.length !== after.length || after.some((value, i) => !Object.is(value, before[i]))
  const hooks = {
    ...React,
    useState(initial) {
      const i = cursor++
      slots[i] ??= { value: typeof initial === 'function' ? initial() : initial }
      return [slots[i].value, (next) => {
        slots[i].value = typeof next === 'function' ? next(slots[i].value) : next
      }]
    },
    useRef(initial) {
      const i = cursor++
      slots[i] ??= { current: initial }
      return slots[i]
    },
    useMemo(factory, deps) {
      const i = cursor++
      if (changed(slots[i]?.deps, deps)) slots[i] = { value: factory(), deps }
      return slots[i].value
    },
    useCallback(callback, deps) { return hooks.useMemo(() => callback, deps) },
    useEffect(effect, deps) {
      const i = cursor++
      if (changed(slots[i]?.deps, deps)) {
        pending.push(() => {
          slots[i]?.cleanup?.()
          slots[i] = { deps, cleanup: effect() }
        })
      }
    },
  }
  return {
    hooks,
    render(component, props = {}) { cursor = 0; return component(props) },
    flushEffects() { const effects = pending; pending = []; effects.forEach((effect) => effect()) },
    unmount() { slots.forEach((slot) => slot.cleanup?.()) },
  }
}

export function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  if (!tree || typeof tree !== 'object') return []
  return [tree, ...nodes(tree.props?.children)]
}

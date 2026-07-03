try {
  sessionStorage.setItem('dpms-stale-module-reload', String(Date.now()))
} catch (error) {
  // ignore storage failures
}

const staleModuleFallback = new Proxy(function staleModuleFallback() {}, {
  apply() {
    return undefined
  },
  construct() {
    return {}
  },
  get(_target, prop) {
    if (prop === 'then') return undefined
    if (prop === Symbol.toStringTag) return 'DPMSStaleModuleFallback'
    return staleModuleFallback
  },
})

setTimeout(() => {
  window.location.reload()
}, 0)

export default staleModuleFallback
export {
  staleModuleFallback as A,
  staleModuleFallback as B,
  staleModuleFallback as C,
  staleModuleFallback as D,
  staleModuleFallback as E,
  staleModuleFallback as F,
  staleModuleFallback as G,
  staleModuleFallback as H,
  staleModuleFallback as I,
  staleModuleFallback as J,
  staleModuleFallback as K,
  staleModuleFallback as L,
  staleModuleFallback as M,
  staleModuleFallback as N,
  staleModuleFallback as O,
  staleModuleFallback as P,
  staleModuleFallback as Q,
  staleModuleFallback as R,
  staleModuleFallback as S,
  staleModuleFallback as T,
  staleModuleFallback as U,
  staleModuleFallback as V,
  staleModuleFallback as W,
  staleModuleFallback as X,
  staleModuleFallback as Y,
  staleModuleFallback as Z,
  staleModuleFallback as a,
  staleModuleFallback as b,
  staleModuleFallback as c,
  staleModuleFallback as d,
  staleModuleFallback as e,
  staleModuleFallback as f,
  staleModuleFallback as g,
  staleModuleFallback as h,
  staleModuleFallback as i,
  staleModuleFallback as j,
  staleModuleFallback as k,
  staleModuleFallback as l,
  staleModuleFallback as m,
  staleModuleFallback as n,
  staleModuleFallback as o,
  staleModuleFallback as p,
  staleModuleFallback as q,
  staleModuleFallback as r,
  staleModuleFallback as s,
  staleModuleFallback as t,
  staleModuleFallback as u,
  staleModuleFallback as v,
  staleModuleFallback as w,
  staleModuleFallback as x,
  staleModuleFallback as y,
  staleModuleFallback as z,
}

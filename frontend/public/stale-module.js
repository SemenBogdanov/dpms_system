try {
  sessionStorage.setItem('dpms-stale-module-reload', String(Date.now()))
} catch (error) {
  // ignore storage failures
}
window.location.reload()
export {}

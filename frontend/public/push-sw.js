/* Push-only worker. DPMS deliberately does not cache authenticated pages. */
self.addEventListener('push', (event) => {
  let payload = {}
  try {
    payload = event.data ? event.data.json() : {}
  } catch (_) {
    payload = {}
  }
  const kind = payload.title === 'Важное событие' ? 'Важное событие' : 'Новое сообщение'
  const path = typeof payload.path === 'string' && /^\/messages(?:\/|\?|$)/.test(payload.path)
    ? payload.path : '/messages'
  event.waitUntil(self.registration.showNotification(kind, {
    body: 'Откройте Простосделал.рф, чтобы посмотреть.',
    icon: '/push-icon.png',
    tag: typeof payload.tag === 'string' ? payload.tag : kind,
    data: { path },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const path = event.notification.data?.path || '/messages'
  const url = new URL(path, self.location.origin).href
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin) {
        await client.navigate(url)
        return client.focus()
      }
    }
    return self.clients.openWindow(url)
  })())
})

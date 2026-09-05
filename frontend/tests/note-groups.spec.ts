import { expect, test, type Page } from '@playwright/test'

const owner = '11111111-1111-4111-8111-111111111111'
const groupId = '22222222-2222-4222-8222-222222222222'
const noteId = '33333333-3333-4333-8333-333333333333'
const projectId = '44444444-4444-4444-8444-444444444444'
const recipientId = '55555555-5555-4555-8555-555555555555'
const batchId = '66666666-6666-4666-8666-666666666666'
const note = { id: noteId, owner_id: owner, title: 'Проверка договора', body: 'Текст заметки для группировки', tags: [], status: 'draft', revision: 1, group_id: null as string | null, created_at: '2026-09-05T00:00:00Z', updated_at: '2026-09-05T00:00:00Z' }
const user = { id: owner, full_name: 'Проверка заметок', email: 'note-groups@example.invalid', role: 'executor', league: 'A', is_active: true, task_workspace_enabled: true,
  feedback_enabled: false, audit_enabled: false, competency_development_enabled: false, competency_constructor_enabled: false,
  needs_password_change: false, sidebar_menu_order: null, mpw: 0, wip_limit: 5, quality_score: 100, wallet_main: 0, wallet_karma: 0 }

async function fixture(page: Page) {
  let groups = [{ id: groupId, title: 'Рабочие материалы', position: 0, collapsed: false, archived: false, revision: 1, note_count: 0 }]
  const notes = [{ ...note }]
  const writes: { path: string; body: Record<string, unknown> }[] = []
  let links: object[] = []
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'note-groups-fixture'))
  await page.routeWebSocket('**/api/**', socket => {
    socket.onMessage(() => socket.send(JSON.stringify({ type: 'ready', note_id: noteId, revision: 1 })))
  })
  await page.route('**/api/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname, method = req.method()
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (method !== 'GET') writes.push({ path, body: req.postData() ? req.postDataJSON() : {} })
    if (path === '/api/auth/me') return respond(user)
    if (path === '/api/messages/summary') return respond({ direct_count: 0, important_count: 0 })
    if (path === '/api/quick-notes/shared') return respond([{ share: { id: recipientId, owner_name: 'Коллега' }, note: { ...note, id: recipientId, title: 'Входящая заметка' } }])
    if (path === '/api/quick-notes') return respond(notes.filter(item => url.searchParams.has('group_id') ? item.group_id === url.searchParams.get('group_id') : url.searchParams.has('ungrouped') ? !item.group_id : true))
    if (path === `/api/quick-notes/${noteId}`) return respond(notes[0])
    if (path === '/api/note-groups/targets') return respond([{ target_type: 'entity', target_id: projectId, title: 'Проект запуска' }])
    if (path === '/api/note-groups/share/recipients') return respond([{ id: recipientId, name: 'Принятый контакт' }])
    if (path === '/api/note-groups/share/preview') return respond({ id: batchId, expires_at: '2099-01-01T00:00:00Z', policy: 'accepted_contacts', existing_share_count: 0, new_share_count: 1,
      notes: [{ ...note, excerpt: note.body, comment_count: 2, files: [{ id: 'file', name: 'Описание.txt', size: 10 }] }], recipients: [{ id: recipientId, name: 'Принятый контакт' }] })
    if (path === `/api/note-groups/share/${batchId}/apply`) return respond({ changed_share_count: 1 })
    if (path === '/api/note-groups/move') { notes[0].group_id = req.postDataJSON().group_id; groups[0].note_count = notes[0].group_id ? 1 : 0; return respond({ moved: 1 }) }
    if (path === '/api/note-groups/order') return respond(groups)
    if (path === '/api/note-groups') {
      if (method === 'POST') groups.push({ ...groups[0], id: 'new-group', title: req.postDataJSON().title })
      return respond(groups)
    }
    if (path === `/api/note-groups/${groupId}`) {
      if (method === 'DELETE') { groups = groups.filter(group => group.id !== groupId); notes[0].group_id = null; return respond({ notes_preserved: true }) }
      if (method === 'PATCH') { groups[0] = { ...groups[0], ...req.postDataJSON(), revision: groups[0].revision + 1 }; return respond(groups[0]) }
    }
    if (path.includes('/sources/') && path.endsWith('/links')) {
      if (method === 'POST') links = [{ ...req.postDataJSON(), id: 'link', title: 'Проект запуска', origin: 'direct', can_remove: true, inherited: false }]
      return respond(links)
    }
    return respond([])
  })
  return writes
}

async function noOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
}

test('group form keeps draft on Escape and backdrop, rename archive delete keeps notes', async ({ page }, info) => {
  const writes = await fixture(page)
  await page.goto('/quick-notes')
  await page.getByRole('button', { name: 'Настроить группу: Рабочие материалы' }).click()
  const dialog = page.getByRole('dialog', { name: 'Настройки группы' })
  await dialog.getByLabel('Название группы').fill('Материалы для запуска с длинным названием и проверкой переноса')
  await page.keyboard.press('Escape')
  await expect(dialog.getByLabel('Название группы')).toHaveValue('Материалы для запуска с длинным названием и проверкой переноса')
  await page.mouse.click(2, 2)
  await expect(dialog).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('protected-group.png'), fullPage: true })
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog).toBeHidden()
  await page.getByRole('button', { name: /^Настроить группу: Материалы/ }).click()
  await dialog.getByRole('button', { name: 'Архивировать', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Восстановить', exact: true })).toBeVisible()
  page.once('dialog', prompt => prompt.accept())
  await dialog.getByRole('button', { name: 'Удалить группу', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('link', { name: note.title, exact: true })).toBeVisible()
  expect(writes.some(write => write.path === `/api/quick-notes/${noteId}`)).toBeFalsy()
})

test('bulk move and explicit preview apply retain selected notes and incoming view is read only', async ({ page }, info) => {
  const writes = await fixture(page)
  await page.goto('/quick-notes')
  await page.getByRole('checkbox', { name: `Выбрать заметку: ${note.title}` }).check()
  await page.getByRole('combobox', { name: 'Перенести в группу', exact: true }).selectOption(groupId)
  await page.getByRole('button', { name: 'Перенести', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: `Выбрать заметку: ${note.title}` })).not.toBeChecked()
  await page.getByRole('button', { name: 'Без группы', exact: true }).click()
  await expect(page.getByRole('link', { name: note.title, exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: /^Рабочие материалы/ }).click()
  await page.getByRole('checkbox', { name: `Выбрать заметку: ${note.title}` }).check()
  await page.getByRole('button', { name: 'Открыть доступ', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Открыть доступ' })
  await dialog.getByRole('checkbox', { name: 'Принятый контакт' }).check()
  await dialog.getByRole('button', { name: 'Проверить доступ', exact: true }).click()
  await expect(dialog.getByText('Предпросмотр доступа', { exact: true })).toBeVisible()
  expect(writes.filter(write => write.path.endsWith('/apply'))).toHaveLength(0)
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('share-preview.png'), fullPage: true })
  await dialog.getByRole('checkbox', { name: /^Открыть выбранным/ }).check()
  await dialog.getByRole('button', { name: 'Открыть доступ', exact: true }).click()
  await expect(dialog).toBeHidden()
  expect(writes.filter(write => write.path.endsWith('/apply'))).toHaveLength(1)
  await page.getByRole('button', { name: 'Доступные мне', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Входящая заметка' })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: /^Выбрать заметку/ })).toHaveCount(0)
})

test('individual note context uses unified endpoint and responsive widths', async ({ page }, info) => {
  const writes = await fixture(page)
  await page.goto(`/quick-notes/${noteId}`)
  await page.getByLabel('Проект, цель или своя задача').selectOption(`entity:${projectId}`)
  await page.getByRole('button', { name: 'Добавить связь', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Проект запуска' })).toBeVisible()
  expect(writes.filter(write => write.path === `/api/note-groups/sources/note/${noteId}/links`)).toHaveLength(1)
  for (const width of [320, 1024, 1920]) {
    await page.setViewportSize({ width, height: 900 })
    await noOverflow(page)
  }
  for (const theme of ['Темная тема', 'Розовая тема']) {
    await page.getByRole('button', { name: theme, exact: true }).click()
    await noOverflow(page)
    await page.screenshot({ path: info.outputPath(`note-links-${theme === 'Темная тема' ? 'dark' : 'pink'}.png`), fullPage: true })
  }
  await page.screenshot({ path: info.outputPath('note-links.png'), fullPage: true })
})

test('stale preview returns to recipients without applying or closing the form', async ({ page }) => {
  await fixture(page)
  await page.route(`**/api/note-groups/share/${batchId}/apply`, route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'Заметки изменились. Проверьте доступ заново' }) }))
  await page.goto('/quick-notes')
  await page.getByRole('checkbox', { name: `Выбрать заметку: ${note.title}` }).check()
  await page.getByRole('button', { name: 'Открыть доступ', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Открыть доступ' })
  await dialog.getByRole('checkbox', { name: 'Принятый контакт' }).check()
  await dialog.getByRole('button', { name: 'Проверить доступ' }).click()
  await dialog.getByRole('checkbox', { name: /^Открыть выбранным/ }).check()
  await dialog.getByRole('button', { name: 'Открыть доступ', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Заметки изменились')
  await expect(dialog.getByRole('checkbox', { name: 'Принятый контакт' })).toBeChecked()
  await expect(dialog.getByRole('button', { name: 'Проверить доступ' })).toBeVisible()
})

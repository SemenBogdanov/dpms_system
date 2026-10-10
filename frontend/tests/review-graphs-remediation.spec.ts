import { expect, test, type Page } from '@playwright/test'
import {
  documentFixture, graphFixture, installGraphFixture, readWorkspace, workspaceFrame,
} from './review-graphs-remediation-helpers'

test.use({ serviceWorkers: 'block' })

async function openManager(page: Page) {
  await page.goto('/graphs')
  const frame = workspaceFrame(page)
  await expect(frame.locator('.app')).toBeVisible()
  await frame.locator('#graphManagerButton').click()
  await expect(frame.locator('#graphsDialog')).toBeVisible()
  return frame
}

async function reopenManager(page: Page) {
  const frame = workspaceFrame(page)
  await frame.getByRole('button', { name: 'Закрыть список графов' }).click()
  await frame.locator('#graphManagerButton').click()
}

test('R07: loading and 503 are not empty; retry does not publish local graphs', async ({ page }) => {
  const mock = await installGraphFixture(page)
  const frame = await openManager(page)
  const first = await mock.list(0)
  await expect(frame.getByText('Загружаем список снимков…')).toBeVisible()
  await expect(frame.getByText('Облачных снимков пока нет.')).toHaveCount(0)
  await first.reply(503, { detail: 'Синтетическая недоступность' })
  await expect(frame.locator('#graphsDialog [role="alert"]')).toContainText('Синтетическая недоступность')
  await expect(frame.getByText('Облачных снимков пока нет.')).toHaveCount(0)
  await frame.getByRole('button', { name: 'Повторить загрузку снимков' }).click()
  await (await mock.list(1)).reply(200, [])
  await expect(frame.getByText('Облачных снимков пока нет.')).toBeVisible()
  expect(mock.unexpectedWrites).toEqual([])
  expect(mock.deletes).toHaveLength(0)
})

test('R07: failed refresh marks cached snapshots stale and retry recovers', async ({ page }) => {
  const mock = await installGraphFixture(page)
  const frame = await openManager(page)
  await (await mock.list(0)).reply(200, [documentFixture('a')])
  await expect(frame.locator('[data-server-graph-id="a"]')).toBeVisible()
  await frame.getByRole('button', { name: 'Обновить список снимков' }).click()
  await (await mock.list(1)).reply(503, { detail: 'Обновление недоступно' })
  await expect(frame.locator('#graphsDialog [role="alert"]')).toContainText('Показан ранее загруженный список')
  await expect(frame.locator('[data-server-graph-id="a"]')).toBeVisible()
  await frame.getByRole('button', { name: 'Повторить загрузку снимков' }).click()
  await (await mock.list(2)).reply(200, [documentFixture('b')])
  await expect(frame.locator('[data-server-graph-id="b"]')).toBeVisible()
  await expect(frame.locator('[data-server-graph-id="a"]')).toHaveCount(0)
  await expect(frame.locator('#graphsDialog [role="alert"]')).toHaveCount(0)
  expect(mock.unexpectedWrites).toEqual([])
})

for (const status of [200, 503]) {
  test(`R07: old ${status} cannot replace newer list or clear its loading state`, async ({ page }) => {
    const mock = await installGraphFixture(page)
    const frame = await openManager(page)
    const old = await mock.list(0)
    await reopenManager(page)
    const current = await mock.list(1)
    await old.reply(status, status === 200 ? [documentFixture('old')] : { detail: 'Старая ошибка' })
    await mock.responses(1)
    await expect(frame.getByText('Загружаем список снимков…')).toBeVisible()
    await expect(frame.locator('[data-server-graphs-refresh]')).toBeDisabled()
    await expect(frame.locator('[data-server-graph-id="old"]')).toHaveCount(0)
    await expect(frame.locator('#graphsDialog [role="alert"]')).toHaveCount(0)
    await current.reply(200, [documentFixture('current')])
    await expect(frame.locator('[data-server-graph-id="current"]')).toBeVisible()

    await frame.locator('[data-server-graphs-refresh]').click()
    const late = await mock.list(2)
    await reopenManager(page)
    await (await mock.list(3)).reply(200, [documentFixture('latest')])
    await expect(frame.locator('[data-server-graph-id="latest"]')).toBeVisible()
    await late.reply(status, status === 200 ? [] : { detail: 'Поздняя ошибка' })
    await mock.responses(4)
    await expect(frame.locator('[data-server-graph-id="latest"]')).toBeVisible()
    await expect(frame.locator('#graphsDialog [role="alert"]')).toHaveCount(0)
    await expect(frame.getByText('Облачных снимков пока нет.')).toHaveCount(0)
  })
}

test('R07: timed-out bridge list is retryable and its late success is ignored', async ({ page }) => {
  const mock = await installGraphFixture(page, { bridgeTimeoutMs: 1500 })
  const frame = await openManager(page)
  const old = await mock.list(0)
  await expect(frame.locator('#graphsDialog [role="alert"]')).toContainText('Сервер не ответил вовремя')
  await expect(frame.getByText('Облачных снимков пока нет.')).toHaveCount(0)
  await frame.getByRole('button', { name: 'Повторить загрузку снимков' }).click()
  await (await mock.list(1)).reply(200, [])
  await expect(frame.getByText('Облачных снимков пока нет.')).toBeVisible()
  await old.reply(200, [documentFixture('late')])
  await mock.responses(2)
  await expect(frame.locator('[data-server-graph-id="late"]')).toHaveCount(0)
  expect(mock.unexpectedWrites).toEqual([])
})

for (const [width, height] of [[768, 500], [1024, 768], [1440, 1150], [390, 844], [320, 700]]) {
  test(`R11 / 2.11: 25 graphs leave create and close reachable at ${width}x${height}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height })
    const mock = await installGraphFixture(page, {
      local: Array.from({ length: 25 }, (_, index) => graphFixture(`local-${index}`, `Граф ${index + 1}`)),
    })
    const frame = await openManager(page)
    await (await mock.list(0)).reply(200, [])
    await expect(frame.locator('[data-graph-id]')).toHaveCount(25)
    const bounds = () => frame.locator('#graphsDialog').evaluate((dialog) => {
      const body = dialog.querySelector('#graphsDialogBody')!
      const create = dialog.querySelector('#createGraphButton')!.getBoundingClientRect()
      const close = dialog.querySelector('[data-close-dialog]')!.getBoundingClientRect()
      const rect = dialog.getBoundingClientRect()
      return {
        inside: create.top >= rect.top && create.bottom <= rect.bottom && close.top >= rect.top && close.bottom <= rect.bottom,
        viewport: rect.top >= 0 && rect.bottom <= innerHeight && rect.left >= 0 && rect.right <= innerWidth,
        scrollable: body.scrollHeight > body.clientHeight && getComputedStyle(body).overflowY === 'auto',
        dialogScroll: dialog.scrollTop,
      }
    })
    expect(await bounds()).toEqual({ inside: true, viewport: true, scrollable: true, dialogScroll: 0 })
    await frame.locator('#graphsDialogBody').evaluate((body) => { body.scrollTop = body.scrollHeight })
    expect(await bounds()).toEqual({ inside: true, viewport: true, scrollable: true, dialogScroll: 0 })
    await frame.locator('#createGraphButton').click({ trial: true })
    await frame.getByRole('button', { name: 'Закрыть список графов' }).click()
    await expect(frame.locator('#graphManagerButton')).toBeFocused()
    await frame.locator('#graphManagerButton').press('Enter')
    await (await mock.list(1)).reply(200, [])
    await expect(frame.getByText('Облачных снимков пока нет.')).toBeAttached()
    await frame.getByRole('button', { name: 'Закрыть список графов' }).focus()
    const inspectFocus = async () => ({
      host: await page.evaluate(() => ({
        tag: document.activeElement?.tagName, id: document.activeElement?.id, hasFocus: document.hasFocus(),
      })),
      frame: await frame.locator('body').evaluate(() => ({
        tag: document.activeElement?.tagName, id: document.activeElement?.id, hasFocus: document.hasFocus(),
        insideDialog: Boolean(document.activeElement?.closest('#graphsDialog')),
      })),
    })
    const focusTrace = [{ step: 'close', ...await inspectFocus() }]
    await page.keyboard.press('Shift+Tab')
    focusTrace.push({ step: 'shift-tab', ...await inspectFocus() })
    await expect(frame.locator('#createGraphButton')).toBeFocused()
    await page.keyboard.press('Tab')
    focusTrace.push({ step: 'tab-back', ...await inspectFocus() })
    await expect(frame.getByRole('button', { name: 'Закрыть список графов' })).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    focusTrace.push({ step: 'shift-tab-again', ...await inspectFocus() })
    await testInfo.attach('manager-native-focus', { body: JSON.stringify(focusTrace, null, 2), contentType: 'application/json' })
    expect(focusTrace.every((state) => state.host.tag === 'IFRAME' && state.frame.insideDialog)).toBe(true)
    await expect(frame.locator('#createGraphButton')).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(frame.locator('#graphsDialog')).not.toBeVisible()
    await expect(frame.locator('#graphTitle')).toHaveValue('Новый граф 26')
    expect((await readWorkspace(page)).graphs).toHaveLength(26)
    expect(mock.unexpectedWrites).toEqual([])
  })
}

test('A04: consecutive arrows and Shift+arrows preserve point identity and focus', async ({ page }) => {
  await installGraphFixture(page)
  await page.goto('/graphs')
  const frame = workspaceFrame(page)
  const edge = frame.locator('[data-edge-id="edge-a"]')
  await edge.focus()
  await page.keyboard.press('Enter')
  await expect(edge).toBeFocused()
  const point = edge.locator('[data-edge-point="0"]')
  await point.focus()
  await page.keyboard.press('ArrowRight')
  await expect(point).toBeFocused()
  await page.keyboard.press('ArrowRight')
  await expect(point).toHaveAttribute('cx', '164')
  await expect(point).toBeFocused()
  await page.keyboard.press('Shift+ArrowDown')
  await page.keyboard.press('Shift+ArrowDown')
  await expect(point).toHaveAttribute('cy', '40')
  await expect(point).toBeFocused()
  const stored = await readWorkspace(page)
  expect(stored.graphs[0].edges[0].points[0]).toEqual({ x: 164, y: 40 })
  await page.keyboard.press('Delete')
  await expect(point).toBeFocused()
  await expect(point).toHaveAttribute('cx', '250')
  await page.keyboard.press('ArrowRight')
  await expect(point).toHaveAttribute('cx', '252')
  await page.keyboard.press('Delete')
  await expect(point).toHaveCount(0)
  await expect(edge).toBeFocused()
})

test('A02: per-ID delete guard survives B completion; failed A can retry', async ({ page }) => {
  const remote = [documentFixture('a', 7), documentFixture('b', 11)]
  const mock = await installGraphFixture(page, { local: remote.map((item) => item.payload), remote })
  let confirmations = 0
  page.on('dialog', async (dialog) => { confirmations += 1; await dialog.accept() })
  const frame = await openManager(page)
  await (await mock.list(0)).reply(200, remote)
  const a = frame.locator('[data-server-graph-delete="a"]')
  const b = frame.locator('[data-server-graph-delete="b"]')
  await a.click()
  const deleteA = await mock.deletion(0)
  expect(deleteA.revision).toBe(7)
  await expect(a).toBeDisabled()
  await expect(frame.locator('[data-graph-publish="a"]')).toBeDisabled()
  // Exercise the synchronous guard even if an old/delegated event reaches a disabled control.
  await a.dispatchEvent('click')
  await b.click()
  const deleteB = await mock.deletion(1)
  expect(deleteB.revision).toBe(11)
  await deleteB.reply(200, { deleted: true, client_id: 'b' })
  await expect(b).toHaveCount(0)
  await expect(a).toBeDisabled()
  await a.dispatchEvent('click')
  expect(mock.deletes).toHaveLength(2)
  expect(confirmations).toBe(2)
  await deleteA.reply(503, { detail: 'Удаление A недоступно' })
  await expect(a).toBeEnabled()
  expect((await readWorkspace(page)).storage.a.revision).toBe(7)
  await a.focus()
  await page.keyboard.press('Enter')
  await (await mock.deletion(2)).reply(200, { deleted: true, client_id: 'a' })
  await expect(a).toHaveCount(0)
  expect((await readWorkspace(page)).storage.a.revision).toBeNull()
  expect(mock.unexpectedWrites).toEqual([])
})

for (const status of [200, 503]) {
  test(`A02: old delete ${status} preserves a new graph draft and active session`, async ({ page }) => {
    const remote = [documentFixture('a', 3)]
    const mock = await installGraphFixture(page, { local: [remote[0].payload], remote })
    page.on('dialog', (dialog) => dialog.accept())
    const frame = await openManager(page)
    await (await mock.list(0)).reply(200, remote)
    await frame.locator('[data-server-graph-delete="a"]').click()
    const pending = await mock.deletion(0)
    await frame.locator('#createGraphButton').click()
    const title = frame.locator('#graphTitle')
    await title.fill('Новый несвязанный черновик')
    await title.press('Enter')
    const before = await readWorkspace(page)
    await pending.reply(status, status === 200 ? { deleted: true, client_id: 'a' } : { detail: 'Старая ошибка A' })
    await mock.responses(2)
    await expect(title).toHaveValue('Новый несвязанный черновик')
    await expect(frame.locator('#graphsDialog')).not.toBeVisible()
    const after = await readWorkspace(page)
    expect(after.activeGraphId).toBe(before.activeGraphId)
    expect(after.graphs.find((graph) => graph.id === before.activeGraphId)).toEqual(
      before.graphs.find((graph) => graph.id === before.activeGraphId),
    )
    expect(after.storage[before.activeGraphId]).toEqual(before.storage[before.activeGraphId])
  })
}

test('A02: failed delete restores remote metadata without overwriting newer local edits', async ({ page }) => {
  const remote = [documentFixture('a', 4)]
  const mock = await installGraphFixture(page, { local: [remote[0].payload], remote })
  page.on('dialog', (dialog) => dialog.accept())
  const frame = await openManager(page)
  await (await mock.list(0)).reply(200, remote)
  await frame.locator('[data-server-graph-delete="a"]').click()
  const pending = await mock.deletion(0)
  await frame.getByRole('button', { name: 'Закрыть список графов' }).click()
  await frame.locator('#graphTitle').fill('Правки во время удаления')
  await frame.locator('#graphTitle').press('Enter')
  await pending.reply(503, { detail: 'Удаление не выполнено' })
  await mock.responses(2)
  const stored = await readWorkspace(page)
  expect(stored.graphs[0].title).toBe('Правки во время удаления')
  expect(stored.storage.a).toMatchObject({ revision: 4, publishState: 'changed' })
})

test('R07 / A02: list started before delete cannot resurrect a deleted snapshot', async ({ page }) => {
  const snapshot = documentFixture('a', 5)
  const mock = await installGraphFixture(page)
  page.on('dialog', (dialog) => dialog.accept())
  const frame = await openManager(page)
  await (await mock.list(0)).reply(200, [snapshot])
  await frame.locator('[data-server-graphs-refresh]').click()
  const staleList = await mock.list(1)
  await frame.locator('[data-server-graph-delete="a"]').click()
  await (await mock.deletion(0)).reply(200, { deleted: true, client_id: 'a' })
  await expect(frame.locator('[data-server-graph-id="a"]')).toHaveCount(0)
  await staleList.reply(200, [snapshot])
  await (await mock.list(2)).reply(200, [])
  await expect(frame.getByText('Облачных снимков пока нет.')).toBeVisible()
  await expect(frame.locator('[data-server-graph-id="a"]')).toHaveCount(0)
})

test('A02: delete completion cannot remove a newer observed revision of the same ID', async ({ page }) => {
  const mock = await installGraphFixture(page)
  page.on('dialog', (dialog) => dialog.accept())
  const frame = await openManager(page)
  await (await mock.list(0)).reply(200, [documentFixture('a', 1)])
  await frame.locator('[data-server-graph-delete="a"]').click()
  const pending = await mock.deletion(0)
  await frame.locator('[data-server-graphs-refresh]').click()
  await (await mock.list(1)).reply(200, [documentFixture('a', 2)])
  await expect(frame.locator('[data-server-graph-delete="a"]')).toHaveAttribute('data-server-revision', '2')
  await pending.reply(200, { deleted: true, client_id: 'a' })
  await mock.responses(3)
  await expect(frame.locator('[data-server-graph-delete="a"]')).toBeEnabled()
  await expect(frame.locator('[data-server-graph-delete="a"]')).toHaveAttribute('data-server-revision', '2')
})

test('A02: cancel releases the guard; 409 retry uses the fetched revision', async ({ page }) => {
  const mock = await installGraphFixture(page, { remote: [documentFixture('a', 8)] })
  const frame = await openManager(page)
  await (await mock.list(0)).reply(200, [documentFixture('a', 7)])
  const button = frame.locator('[data-server-graph-delete="a"]')
  page.once('dialog', (dialog) => dialog.dismiss())
  await button.click()
  await expect(button).toBeEnabled()
  expect(mock.deletes).toHaveLength(0)
  page.on('dialog', (dialog) => dialog.accept())
  await button.click()
  const first = await mock.deletion(0)
  expect(first.revision).toBe(7)
  await first.reply(409, { detail: { code: 'graph_revision_conflict', message: 'Снимок изменился' } })
  await expect(button).toBeEnabled()
  await expect(button).toHaveAttribute('data-server-revision', '8')
  await button.click()
  const retry = await mock.deletion(1)
  expect(retry.revision).toBe(8)
  await retry.reply(200, { deleted: true, client_id: 'a' })
  await expect(button).toHaveCount(0)
})

test('A02: failed cloud delete does not recreate locally deleted graph metadata', async ({ page }) => {
  const remote = [documentFixture('a', 4)]
  const mock = await installGraphFixture(page, { local: [remote[0].payload, graphFixture('b')], remote })
  page.on('dialog', (dialog) => dialog.accept())
  const frame = await openManager(page)
  await (await mock.list(0)).reply(200, remote)
  await frame.locator('[data-server-graph-delete="a"]').click()
  const pending = await mock.deletion(0)
  await frame.locator('[data-graph-delete="a"]').click()
  await pending.reply(503, { detail: 'Старая ошибка удалённого локально A' })
  await mock.responses(2)
  const stored = await readWorkspace(page)
  expect(stored.graphs.some((graph) => graph.id === 'a')).toBe(false)
  expect(stored.storage.a).toBeUndefined()
  expect(stored.activeGraphId).toBe('b')
})

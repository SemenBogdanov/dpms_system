import { expect, test } from '@playwright/test'
import {
  adminFixture, aiForm, assertModalGeometry, deferred, doubleActivate,
  historyFor, period, periodResult, providers, releaseResponse, staff, stamp,
} from './review-admin-integrations-helpers'

test.use({ serviceWorkers: 'block' })

for (const navigation of ['roundtrip', 'same-profile'] as const) {
  for (const outcome of ['success', 'error'] as const) {
    test(`UX01: AI save ${navigation} ${outcome} reconciles A without a falsely clean draft`, async ({ page }) => {
      const reply = deferred()
      const payloads: Array<{ display_name: string; model_name: string; expected_config_version: number }> = []
      let failing = outcome === 'error'
      const fixture = await adminFixture(page, async (route, url) => {
        if (url.pathname === '/api/admin/integrations/ai/providers' && route.request().method() === 'GET') {
          await route.fulfill({ json: { items: providers.map((provider) => ({ ...provider, last_test_status: 'ok', ready_for_use: true })), allowed_origins_configured: true, encryption_key_configured: true } })
          return true
        }
        if (url.pathname !== '/api/admin/integrations/ai/providers/profile-a' || route.request().method() !== 'PUT') return false
        const payload = route.request().postDataJSON()
        payloads.push({ display_name: payload.display_name, model_name: payload.model_name, expected_config_version: payload.expected_config_version })
        await reply.promise
        await route.fulfill(failing ? { status: 503, json: { detail: 'Сохранение A не выполнено' } } : {
          json: { ...providers[0], display_name: payload.display_name, model_name: payload.model_name, config_version: payload.expected_config_version + 1, last_test_status: 'ok', ready_for_use: true },
        })
        return true
      })
      const form = await aiForm(page)
      await form.getByLabel('Название', { exact: true }).fill('Изменённый A')
      await form.getByLabel('Модель', { exact: true }).fill('new-model-a')
      await form.getByRole('button', { name: 'Проверить и сохранить' }).click()
      await expect.poll(() => payloads.length).toBe(1)
      if (navigation === 'roundtrip') await page.getByRole('button', { name: /^Профиль B/ }).click()
      await page.getByRole('button', { name: /^Профиль A/ }).click()
      await expect(form.getByLabel('Название', { exact: true })).toBeDisabled()
      await releaseResponse(page, '/api/admin/integrations/ai/providers/profile-a', reply.resolve)
      await expect(form.getByLabel('Название', { exact: true })).toHaveValue('Изменённый A')
      await expect(form.getByLabel('Модель', { exact: true })).toHaveValue('new-model-a')
      await expect(form.getByRole('button', { name: 'Проверить и сохранить' })).toBeEnabled()
      if (outcome === 'error') {
        await expect(page.getByText('Сохранение A не выполнено', { exact: true })).toBeVisible()
        await expect(form.getByText('OK · активно', { exact: true })).toHaveCount(0)
        await expect(form.getByRole('button', { name: 'Повторить проверку' })).toBeDisabled()
      } else {
        await expect(form.getByText('OK · активно', { exact: true })).toBeVisible()
        await expect(form.getByRole('button', { name: 'Повторить проверку' })).toBeEnabled()
      }
      failing = false
      await form.getByRole('button', { name: 'Проверить и сохранить' }).click()
      await expect.poll(() => payloads.length).toBe(2)
      expect(payloads[1]).toEqual({ display_name: 'Изменённый A', model_name: 'new-model-a', expected_config_version: outcome === 'success' ? 4 : 3 })
      await expect(form.getByText('OK · активно', { exact: true })).toBeVisible()
      expect(fixture.unexpected).toEqual([])
    })

    test(`UX01: AI test ${navigation} ${outcome} reconciles selected A status`, async ({ page }) => {
      const reply = deferred()
      let calls = 0
      const fixture = await adminFixture(page, async (route, url) => {
        if (url.pathname === '/api/admin/integrations/ai/providers' && route.request().method() === 'GET') {
          await route.fulfill({ json: { items: providers.map((provider) => ({ ...provider, last_test_status: outcome === 'error' ? 'ok' : null, ready_for_use: outcome === 'error' })), allowed_origins_configured: true, encryption_key_configured: true } })
          return true
        }
        if (url.pathname !== '/api/admin/integrations/ai/providers/profile-a/test') return false
        calls += 1
        await reply.promise
        await route.fulfill(outcome === 'error' ? { status: 503, json: { detail: 'Проверка A не выполнена' } }
          : { json: { ok: true, model_name: 'model-a', tested_at: stamp, message: 'Проверен A' } })
        return true
      })
      const form = await aiForm(page)
      await form.getByRole('button', { name: 'Повторить проверку' }).click()
      await expect.poll(() => calls).toBe(1)
      if (navigation === 'roundtrip') await page.getByRole('button', { name: /^Профиль B/ }).click()
      await page.getByRole('button', { name: /^Профиль A/ }).click()
      await expect(form.getByRole('button', { name: 'Повторить проверку' })).toBeDisabled()
      await releaseResponse(page, '/api/admin/integrations/ai/providers/profile-a/test', reply.resolve)
      await expect(form.getByLabel('Название', { exact: true })).toHaveValue('Профиль A')
      await expect(form.getByRole('button', { name: 'Повторить проверку' })).toBeEnabled()
      await expect(form.getByText(outcome === 'error' ? 'Ошибка проверки' : 'OK · активно', { exact: true })).toBeVisible()
      if (outcome === 'error') await expect(form.getByText('OK · активно', { exact: true })).toHaveCount(0)
      expect(calls).toBe(1)
      expect(fixture.unexpected).toEqual([])
    })
  }
}

for (const outcome of ['success', 'error'] as const) {
  test(`R05/A02: late AI A ${outcome} cannot update B or clear B pending`, async ({ page }) => {
    const a = deferred()
    const b = deferred()
    const calls: string[] = []
    const fixture = await adminFixture(page, async (route, url) => {
      if (!url.pathname.endsWith('/test')) return false
      const id = url.pathname.split('/').at(-2)!
      calls.push(id)
      await (id === 'profile-a' ? a : b).promise
      await route.fulfill(id === 'profile-a' && outcome === 'error'
        ? { status: 503, json: { detail: 'Ошибка проверки A' } }
        : { json: { ok: true, model_name: id, tested_at: stamp, message: `Проверен ${id}` } })
      return true
    })
    const form = await aiForm(page)
    await doubleActivate(form.getByRole('button', { name: 'Повторить проверку' }))
    await expect.poll(() => calls.length).toBe(1)
    await expect(form.getByLabel('Модель', { exact: true })).toBeDisabled()
    await page.getByRole('button', { name: /^Профиль B/ }).click()
    await page.getByRole('button', { name: /^Профиль A/ }).click()
    await expect(form.getByRole('button', { name: 'Повторить проверку' })).toBeDisabled()
    await expect(form.getByRole('button', { name: 'Проверить и сохранить' })).toBeDisabled()
    await page.getByRole('button', { name: /^Профиль B/ }).click()
    await doubleActivate(form.getByRole('button', { name: 'Повторить проверку' }))
    await expect.poll(() => calls.length).toBe(2)
    await releaseResponse(page, '/api/admin/integrations/ai/providers/profile-a/test', a.resolve)
    await expect(page.getByRole('button', { name: /^Профиль A/ })).toBeEnabled()
    await expect(form.getByLabel('Название', { exact: true })).toHaveValue('Профиль B')
    await expect(form.getByText('Требуется проверка', { exact: true })).toBeVisible()
    await expect(form.getByRole('button', { name: 'Повторить проверку' })).toBeDisabled()
    await expect(form.getByText('OK · активно', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Ошибка проверки A', { exact: true })).toHaveCount(0)
    b.resolve()
    await expect(form.getByText('OK · активно', { exact: true })).toBeVisible()
    await expect(form.getByRole('button', { name: 'Повторить проверку' })).toBeEnabled()
    expect(calls).toEqual(['profile-a', 'profile-b'])
    expect(fixture.unexpected).toEqual([])
  })
}

for (const outcome of ['success', 'error'] as const) {
  test(`R05: AI save A ${outcome} preserves the new draft session`, async ({ page }) => {
    const reply = deferred()
    let saves = 0
    await adminFixture(page, async (route, url) => {
      if (url.pathname !== '/api/admin/integrations/ai/providers/profile-a' || route.request().method() !== 'PUT') return false
      saves += 1
      await reply.promise
      await route.fulfill(outcome === 'error'
        ? { status: 503, json: { detail: 'Старый отказ A' } }
        : { json: { ...providers[0], display_name: 'Сохранённый A', config_version: 4, ready_for_use: true } })
      return true
    })
    const form = await aiForm(page)
    await form.getByLabel('Название', { exact: true }).fill('Сохранённый A')
    await expect(form.getByRole('button', { name: 'Повторить проверку' })).toBeDisabled()
    await doubleActivate(form.getByRole('button', { name: 'Проверить и сохранить' }))
    await expect.poll(() => saves).toBe(1)
    await page.getByRole('button', { name: 'Новое подключение', exact: true }).click()
    await form.getByLabel('Название', { exact: true }).fill('Новый черновик B')
    await form.getByLabel('Модель', { exact: true }).fill('draft-model')
    await releaseResponse(page, '/api/admin/integrations/ai/providers/profile-a', reply.resolve)
    await expect(form.getByLabel('Название', { exact: true })).toHaveValue('Новый черновик B')
    await expect(form.getByLabel('Модель', { exact: true })).toHaveValue('draft-model')
    await expect(form.getByRole('button', { name: 'Проверить и создать' })).toBeEnabled()
    await expect(page.getByText('Старый отказ A', { exact: true })).toHaveCount(0)
    expect(saves).toBe(1)
  })
}

test('A02/R11: parallel quota decisions retain per-ID locks, preserve retry, and wrap long reasons', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 })
  const a = deferred()
  const b = deferred()
  const calls: string[] = []
  let failA = true
  await adminFixture(page, async (route, url) => {
    if (!url.pathname.endsWith('/decision')) return false
    const id = url.pathname.split('/').at(-2)!
    calls.push(id)
    await (id === 'quota-0' ? a : b).promise
    await route.fulfill(id === 'quota-0' && failA
      ? { status: 503, json: { detail: 'Решение A не сохранено' } }
      : { json: {} })
    return true
  })
  await page.goto('/admin/users')
  const panel = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Заявки на хранилище', exact: true }) })
  const articleA = panel.getByRole('article').filter({ hasText: 'Сотрудник A' })
  const articleB = panel.getByRole('article').filter({ hasText: 'Сотрудник B' })
  await articleA.getByLabel('Комментарий к решению').fill('Решение A')
  await articleB.getByLabel('Комментарий к решению').fill('Решение B')
  const bounds = await articleA.evaluate((element) => {
    const reason = element.querySelector('p.whitespace-pre-wrap')!
    return { article: element.getBoundingClientRect().right, reason: reason.getBoundingClientRect().right, scroll: reason.scrollWidth, width: reason.clientWidth, viewport: innerWidth }
  })
  expect(bounds.article).toBeLessThanOrEqual(bounds.viewport)
  expect(bounds.reason).toBeLessThanOrEqual(bounds.article)
  expect(bounds.scroll).toBeLessThanOrEqual(bounds.width + 1)
  await doubleActivate(articleA.getByRole('button', { name: 'Одобрить', exact: true }))
  await doubleActivate(articleB.getByRole('button', { name: 'Отклонить', exact: true }))
  await expect.poll(() => calls.length).toBe(2)
  b.resolve()
  await expect(articleB).toHaveCount(0)
  await expect(articleA.getByRole('button', { name: 'Одобрить', exact: true })).toBeDisabled()
  await expect(articleA.getByRole('button', { name: 'Отклонить', exact: true })).toBeDisabled()
  await expect(articleA.getByLabel('Комментарий к решению')).toBeDisabled()
  // A stale list snapshot must not resurrect already resolved B.
  await panel.getByRole('button', { name: 'Обновить', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Обновить', exact: true })).toBeEnabled()
  await expect(articleB).toHaveCount(0)
  a.resolve()
  await expect(articleA.getByRole('alert')).toHaveText('Решение A не сохранено')
  await expect(articleA.getByLabel('Комментарий к решению')).toHaveValue('Решение A')
  failA = false
  await articleA.getByRole('button', { name: 'Одобрить', exact: true }).click()
  await expect(articleA).toHaveCount(0)
  expect(calls).toEqual(['quota-0', 'quota-1', 'quota-0'])
})

test('A02: independent staff mutations do not release another user and allow retry after failure', async ({ page }) => {
  const a = deferred()
  const b = deferred()
  const calls: string[] = []
  let failA = true
  const users = staff.map((user) => ({ ...user }))
  await adminFixture(page, async (route, url) => {
    if (url.pathname === '/api/users/admin') { await route.fulfill({ json: users }); return true }
    if (route.request().method() !== 'PATCH' || !url.pathname.startsWith('/api/users/')) return false
    const id = url.pathname.split('/').at(-1)!
    calls.push(id)
    await (id === staff[0].id ? a : b).promise
    const failed = id === staff[0].id && failA
    if (!failed) users.find((user) => user.id === id)!.is_active = false
    await route.fulfill(failed ? { status: 503, json: { detail: 'Отказ A' } } : { json: {} })
    return true
  })
  page.on('dialog', (dialog) => dialog.accept())
  await page.goto('/admin/users')
  const actionA = page.getByRole('button', { name: 'Деактивировать Сотрудник A', exact: true }).filter({ visible: true })
  const actionB = page.getByRole('button', { name: 'Деактивировать Сотрудник B', exact: true }).filter({ visible: true })
  await doubleActivate(actionA)
  await doubleActivate(actionB)
  await expect.poll(() => calls.length).toBe(2)
  b.resolve()
  await expect(page.getByRole('button', { name: 'Восстановить Сотрудник B', exact: true }).filter({ visible: true })).toBeVisible()
  await expect(actionA).toBeDisabled()
  a.resolve()
  await expect(actionA).toBeEnabled()
  failA = false
  await actionA.click()
  await expect(page.getByRole('button', { name: 'Восстановить Сотрудник A', exact: true }).filter({ visible: true })).toBeVisible()
  expect(calls).toEqual([staff[0].id, staff[1].id, staff[0].id])
})

test('R07: period history failure is not empty and retry preserves rows after a refresh failure', async ({ page }) => {
  let failHistory = true
  await adminFixture(page, async (route, url) => {
    if (url.pathname === '/api/admin/period-history') {
      await route.fulfill(failHistory ? { status: 503, json: { detail: 'История временно недоступна' } } : { json: [period] })
      return true
    }
    if (url.pathname === '/api/admin/rollover-period') { await route.fulfill({ json: periodResult }); return true }
    return false
  })
  await page.goto('/admin/users')
  await expect(page.getByRole('alert').filter({ hasText: 'История временно недоступна' })).toBeVisible()
  await expect(page.getByText('Нет закрытых периодов', { exact: true })).toHaveCount(0)
  failHistory = false
  await page.getByRole('button', { name: 'Повторить загрузку истории' }).click()
  await expect(page.getByRole('cell', { name: period.period, exact: true })).toBeVisible()
  failHistory = true
  await page.getByRole('button', { name: 'Закрыть выбранный период', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Подтверждение закрытия периода' })
  await dialog.getByLabel(/Введите "ROLLOVER"/).fill('ROLLOVER')
  await dialog.getByRole('button', { name: 'Закрыть период', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('alert').filter({ hasText: 'Показана ранее загруженная история' })).toBeVisible()
  await expect(page.getByRole('cell', { name: period.period, exact: true })).toBeVisible()
  await expect(page.getByText('Нет закрытых периодов', { exact: true })).toHaveCount(0)
})

test('R05/R07: obsolete period history failure cannot replace a newer successful refresh', async ({ page }) => {
  const old = deferred()
  let reads = 0
  await adminFixture(page, async (route, url) => {
    if (url.pathname === '/api/admin/period-history') {
      reads += 1
      if (reads === 1) {
        await old.promise
        await route.fulfill({ status: 503, json: { detail: 'Устаревшая ошибка истории' } })
      } else await route.fulfill({ json: [period] })
      return true
    }
    if (url.pathname === '/api/admin/rollover-period') { await route.fulfill({ json: periodResult }); return true }
    return false
  })
  await page.goto('/admin/users')
  await expect.poll(() => reads).toBe(1)
  await page.getByRole('button', { name: 'Закрыть выбранный период', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel(/Введите "ROLLOVER"/).fill('ROLLOVER')
  await dialog.getByRole('button', { name: 'Закрыть период', exact: true }).click()
  await expect(page.getByRole('cell', { name: period.period, exact: true })).toBeVisible()
  await releaseResponse(page, '/api/admin/period-history', old.resolve)
  await expect(page.getByText('Устаревшая ошибка истории', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('cell', { name: period.period, exact: true })).toBeVisible()
})

for (const outcome of ['success', 'error'] as const) {
  test(`R07/R09: closed user history A ${outcome} cannot alter B error/retry or focus`, async ({ page }) => {
    const a = deferred()
    let failB = true
    await adminFixture(page, async (route, url) => {
      if (!url.pathname.endsWith('/admin-history')) return false
      const id = url.pathname.split('/')[3]
      if (id === staff[0].id) {
        await a.promise
        await route.fulfill(outcome === 'error' ? { status: 503, json: { detail: 'Старая ошибка A' } }
          : { json: historyFor(id, 'Изменение A') })
      } else {
        await route.fulfill(failB ? { status: 503, json: { detail: 'История B недоступна' } }
          : { json: historyFor(id, 'Изменение B') })
      }
      return true
    })
    await page.goto('/admin/users')
    const triggerA = page.getByRole('button', { name: 'История изменений Сотрудник A', exact: true }).filter({ visible: true })
    await triggerA.focus()
    await triggerA.press('Enter')
    await expect(page.getByRole('dialog').getByText('Загрузка истории...')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(triggerA).toBeFocused()
    const triggerB = page.getByRole('button', { name: 'История изменений Сотрудник B', exact: true }).filter({ visible: true })
    await triggerB.focus()
    await triggerB.press('Enter')
    const dialog = page.getByRole('dialog', { name: 'Сотрудник B', exact: true })
    await expect(dialog.getByRole('alert')).toHaveText('История B недоступна')
    await releaseResponse(page, `/api/users/${staff[0].id}/admin-history`, a.resolve)
    await expect(dialog.getByText('Изменений пока нет.', { exact: true })).toHaveCount(0)
    await expect(dialog.getByRole('definition').filter({ hasText: 'Изменение A' })).toHaveCount(0)
    for (const key of ['Tab', 'Shift+Tab', 'Tab', 'Tab']) {
      await page.keyboard.press(key)
      await expect.poll(() => dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
    }
    failB = false
    await dialog.getByRole('button', { name: 'Повторить', exact: true }).click()
    await expect(dialog.getByRole('definition').filter({ hasText: 'Изменение B' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(triggerB).toBeFocused()
  })
}

test('R09/A02: period confirmation traps focus, protects busy input, and retries once', async ({ page }) => {
  const reply = deferred()
  let calls = 0
  let failing = true
  await adminFixture(page, async (route, url) => {
    if (url.pathname !== '/api/admin/rollover-period') return false
    calls += 1
    await reply.promise
    await route.fulfill(failing ? { status: 503, json: { detail: 'Период не закрыт' } } : { json: periodResult })
    return true
  })
  await page.goto('/admin/users')
  const trigger = page.getByRole('button', { name: 'Закрыть выбранный период', exact: true })
  await trigger.focus()
  await trigger.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Подтверждение закрытия периода' })
  await expect.poll(() => dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  await expect.poll(() => trigger.evaluate((element) => Boolean(element.closest('[inert]')))).toBe(true)
  for (let i = 0; i < 6; i += 1) {
    await page.keyboard.press(i % 2 ? 'Tab' : 'Shift+Tab')
    await expect.poll(() => dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  }
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  await trigger.press('Enter')
  await dialog.getByLabel(/Введите "ROLLOVER"/).fill('ROLLOVER')
  page.once('dialog', (prompt) => prompt.dismiss())
  await page.keyboard.press('Escape')
  await expect(dialog.getByLabel(/Введите "ROLLOVER"/)).toHaveValue('ROLLOVER')
  await doubleActivate(dialog.getByRole('button', { name: 'Закрыть период', exact: true }))
  await expect.poll(() => calls).toBe(1)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Отмена', exact: true })).toBeDisabled()
  await expect(dialog.getByLabel(/Введите "ROLLOVER"/)).toBeDisabled()
  reply.resolve()
  await expect(dialog.getByRole('button', { name: 'Закрыть период', exact: true })).toBeEnabled()
  await expect(dialog.getByLabel(/Введите "ROLLOVER"/)).toHaveValue('ROLLOVER')
  failing = false
  await dialog.getByRole('button', { name: 'Закрыть период', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  expect(calls).toBe(2)
})

test('R09/A02: cancelling a period locks confirmation until its own response', async ({ page }) => {
  const reply = deferred()
  let calls = 0
  await adminFixture(page, async (route, url) => {
    if (!url.pathname.endsWith('/cancel')) return false
    calls += 1
    await reply.promise
    await route.fulfill({ status: 503, json: { detail: 'Отмена не выполнена' } })
    return true
  })
  await page.goto('/admin/users')
  const row = page.getByRole('row').filter({ has: page.getByRole('cell', { name: period.period, exact: true }) })
  await row.getByRole('button', { name: 'Отменить', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Отмена закрытия периода', exact: true })
  await dialog.getByLabel(/Введите "CANCEL"/).fill('CANCEL')
  await doubleActivate(dialog.getByRole('button', { name: 'Отменить закрытие', exact: true }))
  await expect.poll(() => calls).toBe(1)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Закрыть', exact: true })).toBeDisabled()
  reply.resolve()
  await expect(dialog.getByRole('button', { name: 'Отменить закрытие', exact: true })).toBeEnabled()
  await expect(dialog.getByLabel(/Введите "CANCEL"/)).toHaveValue('CANCEL')
  expect(calls).toBe(1)
})

for (const viewport of [{ width: 768, height: 500 }, { width: 1024, height: 768 }, { width: 1440, height: 1150 }, { width: 390, height: 844 }, { width: 320, height: 700 }]) {
  test(`R09/R11/A02: quick invite partial success and geometry ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const reply = deferred()
    let creates = 0
    await adminFixture(page, async (route, url) => {
      if (url.pathname !== '/api/users' || route.request().method() !== 'POST') return false
      creates += 1
      await reply.promise
      await route.fulfill({ json: staff[0] })
      return true
    })
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw new Error('Буфер обмена недоступен') } } })
    })
    await page.goto('/admin/users')
    const trigger = page.getByRole('button', { name: 'Быстро добавить', exact: true })
    await trigger.focus()
    await trigger.press('Enter')
    const dialog = page.getByRole('dialog', { name: 'Быстро добавить', exact: true })
    await dialog.getByLabel('ФИО', { exact: true }).fill('Синтетический сотрудник')
    await dialog.getByLabel('Почта', { exact: true }).fill('new@example.test')
    page.once('dialog', (prompt) => prompt.dismiss())
    await page.keyboard.press('Escape')
    await expect(dialog.getByLabel('ФИО', { exact: true })).toHaveValue('Синтетический сотрудник')
    await doubleActivate(dialog.getByRole('button', { name: 'Скопировать', exact: true }))
    await expect.poll(() => creates).toBe(1)
    await expect(dialog.getByLabel('ФИО', { exact: true })).toBeDisabled()
    await page.keyboard.press('Escape')
    await expect(dialog).toBeVisible()
    reply.resolve()
    await expect(dialog.getByLabel('Текст для ручного копирования')).toBeVisible()
    await expect(dialog.getByLabel('Почта', { exact: true })).toBeDisabled()
    await assertModalGeometry(dialog)
    await dialog.getByRole('button', { name: 'Скопировать', exact: true }).click()
    await expect(dialog.getByRole('button', { name: 'Скопировать', exact: true })).toBeEnabled()
    expect(creates).toBe(1)
    page.once('dialog', (prompt) => prompt.accept())
    await dialog.getByRole('button', { name: 'Отмена', exact: true }).click()
    await expect(trigger).toBeFocused()
    await trigger.press('Enter')
    await expect(dialog.getByLabel('ФИО', { exact: true })).toHaveValue('')
    await expect(dialog.getByLabel('Текст для ручного копирования')).toHaveCount(0)
  })
}

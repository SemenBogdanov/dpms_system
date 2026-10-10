import { expect, test } from '@playwright/test'
import { feedback, gate, ids, navigateWithinApp, note, peerId, thread, workerFixture } from './review-messages-notes-feedback-helpers'

test('R01: late A success cannot replace B or address its reply to A', async ({ page }) => {
  const delayed = gate()
  let started = false, finished = false
  const state = await workerFixture(page, async (route, url) => {
    if (url.pathname !== `/api/messages/threads/${ids[0]}`) return false
    started = true
    await delayed.promise
    await route.fulfill({ json: thread() })
    finished = true
    return true
  })
  await page.goto(`/messages/${ids[0]}`)
  await expect.poll(() => started).toBe(true)
  await navigateWithinApp(page, `/messages/${ids[1]}`)
  await expect(page.getByRole('heading', { name: 'Переписка B' })).toBeVisible()
  delayed.release()
  await expect.poll(() => finished).toBe(true)
  await page.getByRole('textbox', { name: 'Текст ответа' }).fill('Ответ B')
  await page.getByRole('button', { name: 'Отправить', exact: true }).click()
  await expect.poll(() => state.writes.filter(item => item.path.endsWith('/posts')).length).toBe(1)
  expect(state.writes.find(item => item.path.endsWith('/posts'))).toMatchObject({ path: `/api/messages/threads/${ids[1]}/posts`, body: { body: 'Ответ B' } })
  await expect(page.getByRole('heading', { name: 'Переписка B' })).toBeVisible()
})

test('R01/R07: failed B never exposes A reply; direct error has retry and back', async ({ page }) => {
  let fail = true
  await workerFixture(page, async (route, url) => {
    if (url.pathname !== `/api/messages/threads/${ids[1]}` || !fail) return false
    await route.fulfill({ status: 503, json: { detail: 'Переписка B недоступна' } })
    return true
  })
  await page.goto(`/messages/${ids[0]}`)
  await expect(page.getByRole('heading', { name: 'Переписка A' })).toBeVisible()
  await navigateWithinApp(page, `/messages/${ids[1]}`)
  await expect(page.getByRole('alert')).toContainText('Переписка B недоступна')
  await expect(page.getByRole('textbox', { name: 'Текст ответа' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'К списку сообщений' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('alert')).toContainText('Переписка B недоступна')
  await expect(page.getByText('Выберите переписку', { exact: true })).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Переписка B' })).toBeVisible()
})

test('R01: navigation and submit in the same event cannot send the old recipient', async ({ page }) => {
  const state = await workerFixture(page)
  await page.goto(`/messages/${ids[0]}`)
  await page.getByRole('textbox', { name: 'Текст ответа' }).fill('Черновик A')
  await page.evaluate(id => {
    const form = document.querySelector<HTMLTextAreaElement>('textarea[name="reply_body"]')!.form!
    window.history.pushState({}, '', `/messages/${id}`)
    window.dispatchEvent(new PopStateEvent('popstate'))
    form.requestSubmit()
  }, ids[1])
  await expect(page.getByRole('heading', { name: 'Переписка B' })).toBeVisible()
  expect(state.writes.filter(item => item.path.endsWith('/posts'))).toHaveLength(0)
  await expect(page.getByRole('textbox', { name: 'Текст ответа' })).toHaveValue('')
  await navigateWithinApp(page, `/messages/${ids[0]}`)
  await expect(page.getByRole('textbox', { name: 'Текст ответа' })).toHaveValue('Черновик A')
})

test('R05: old error and finally cannot dismiss the new thread loading state', async ({ page }) => {
  const a = gate(), b = gate()
  let aStarted = false, bStarted = false, aFinished = false
  await workerFixture(page, async (route, url) => {
    if (url.pathname === `/api/messages/threads/${ids[0]}`) {
      aStarted = true
      await a.promise
      await route.fulfill({ status: 503, json: { detail: 'Старая ошибка A' } })
      aFinished = true
      return true
    }
    if (url.pathname === `/api/messages/threads/${ids[1]}`) {
      bStarted = true
      await b.promise
      await route.fulfill({ json: thread(ids[1], 'Переписка B') })
      return true
    }
    return false
  })
  await page.goto(`/messages/${ids[0]}`)
  await expect.poll(() => aStarted).toBe(true)
  await navigateWithinApp(page, `/messages/${ids[1]}`)
  await expect.poll(() => bStarted).toBe(true)
  a.release()
  await expect.poll(() => aFinished).toBe(true)
  await expect(page.getByText('Загрузка переписки…', { exact: true })).toBeVisible()
  await expect(page.getByText('Старая ошибка A', { exact: true })).toHaveCount(0)
  b.release()
  await expect(page.getByRole('heading', { name: 'Переписка B' })).toBeVisible()
})

test('R07/R04: optional notes failure leaves reply usable; pending fields and close are protected', async ({ page }) => {
  const delayed = gate()
  const state = await workerFixture(page, async (route, url) => {
    if (url.pathname === '/api/quick-notes') {
      await route.fulfill({ status: 503, json: { detail: 'Заметки временно недоступны' } }); return true
    }
    if (url.pathname.endsWith('/posts')) {
      await delayed.promise
      await route.fulfill({ json: {} }); return true
    }
    return false
  })
  await page.goto(`/messages/${ids[0]}`)
  const input = page.getByRole('textbox', { name: 'Текст ответа' })
  await expect(input).toBeEnabled()
  await expect(page.getByText('Контакт больше не активен.', { exact: false })).toHaveCount(0)
  await input.fill('Исходный ответ')
  await page.getByRole('button', { name: 'Отправить', exact: true }).click()
  await expect(input).toBeDisabled()
  await expect(page.getByLabel('Приложить заметку')).toBeDisabled()
  await navigateWithinApp(page, `/messages/${ids[1]}`)
  await page.getByRole('textbox', { name: 'Текст ответа' }).fill('Новый черновик B')
  delayed.release()
  await expect(page.getByRole('textbox', { name: 'Текст ответа' })).toHaveValue('Новый черновик B')
  expect(state.writes.filter(item => item.path.endsWith('/posts'))).toHaveLength(1)
})

test('R04: compose cannot close or change submitted draft while POST is pending', async ({ page }) => {
  const delayed = gate()
  const state = await workerFixture(page, async (route, url) => {
    if (url.pathname !== '/api/messages/threads' || route.request().method() !== 'POST') return false
    await delayed.promise
    await route.fulfill({ json: thread(ids[1], 'Новое письмо') })
    return true
  })
  await page.goto('/messages')
  await page.getByRole('button', { name: 'Новое письмо', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Новое письмо' })
  const body = dialog.getByRole('textbox', { name: 'Текст', exact: true })
  await dialog.getByLabel('Получатель').selectOption(peerId)
  await dialog.getByLabel('Тема', { exact: true }).fill('Новая тема')
  await body.fill('Новый текст')
  await dialog.getByRole('button', { name: 'Отправить' }).click()
  await expect(body).toBeDisabled()
  await expect(body).toHaveValue('Новый текст')
  await dialog.getByRole('button', { name: 'Закрыть окно' }).click()
  await expect(dialog).toBeVisible()
  await expect(body).toHaveValue('Новый текст')
  delayed.release()
  await expect(dialog).toBeHidden()
  expect(state.writes.filter(item => item.path === '/api/messages/threads')).toHaveLength(1)
  expect(state.writes.find(item => item.path === '/api/messages/threads')?.body).toMatchObject({
    recipient_id: peerId, subject: 'Новая тема', body: 'Новый текст',
  })
})

test('R04: note save rejects new edits and closing; failed save retains draft for retry', async ({ page }) => {
  const delayed = gate()
  let fail = true
  const state = await workerFixture(page, async (route, url) => {
    if (url.pathname !== `/api/quick-notes/${ids[0]}` || route.request().method() !== 'PATCH') return false
    if (!fail) return false
    await delayed.promise
    await route.fulfill({ status: 503, json: { detail: 'Сохранение недоступно' } })
    return true
  })
  await page.goto('/quick-notes')
  await page.getByRole('article').filter({ hasText: 'Заметка A' }).getByRole('button', { name: 'Редактировать заметку' }).click()
  const dialog = page.getByRole('dialog', { name: 'Редактирование заметки' })
  await dialog.getByPlaceholder('Текст заметки').fill('Сохранить этот черновик')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog.getByPlaceholder('Текст заметки')).toBeDisabled()
  await expect(dialog.getByRole('button', { name: 'Закрыть окно заметки' })).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  delayed.release()
  await expect(dialog.getByPlaceholder('Текст заметки')).toBeEnabled()
  await expect(dialog.getByPlaceholder('Текст заметки')).toHaveValue('Сохранить этот черновик')
  fail = false
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog).toBeHidden()
  expect(state.writes.filter(item => item.method === 'PATCH')).toHaveLength(2)
  expect(state.writes.filter(item => item.method === 'PATCH').map(item => item.body.base_revision)).toEqual([1, 1])
})

test('A02: completing note B does not unlock pending note A; failure permits explicit retry', async ({ page }) => {
  const a = gate(), b = gate()
  let failA = true
  const state = await workerFixture(page, async (route, url) => {
    if (url.pathname !== '/api/personal-tasks') return false
    const isA = route.request().postDataJSON().source_quick_note_id === ids[0]
    await (isA ? a.promise : b.promise)
    await route.fulfill(isA && failA ? { status: 503, json: { detail: 'Повторите создание задачи' } } : { json: { id: 'task' } })
    return true
  })
  await page.goto('/quick-notes')
  const first = page.getByRole('article').filter({ hasText: 'Заметка A' }).getByRole('button', { name: 'Создать личную задачу из заметки' })
  const second = page.getByRole('article').filter({ hasText: 'Заметка B' }).getByRole('button', { name: 'Создать личную задачу из заметки' })
  await first.click()
  await second.click()
  b.release()
  await expect(second).toBeEnabled()
  await expect(first).toBeDisabled()
  expect(state.writes.filter(item => item.path === '/api/personal-tasks')).toHaveLength(2)
  a.release()
  await expect(first).toBeEnabled()
  failA = false
  await first.click()
  await expect.poll(() => state.writes.filter(item => item.path === '/api/personal-tasks').length).toBe(3)
})

test('R04/A02: comment pending blocks repeat and preserves a different note draft', async ({ page }) => {
  const delayed = gate()
  const state = await workerFixture(page, async (route, url) => {
    if (!url.pathname.endsWith('/comments') || route.request().method() !== 'POST') return false
    await delayed.promise
    await route.fulfill({ json: { id: 'comment' } })
    return true
  })
  await page.goto(`/quick-notes/${ids[0]}`)
  const draft = page.getByPlaceholder('Комментарий к заметке')
  await draft.fill('Комментарий A')
  await page.getByRole('button', { name: 'Отправить', exact: true }).click()
  await expect(draft).toBeDisabled()
  await navigateWithinApp(page, `/quick-notes/${ids[1]}`)
  await expect(page.getByRole('heading', { name: 'Заметка B', exact: true })).toBeVisible()
  await draft.fill('Черновик B')
  delayed.release()
  await expect(draft).toHaveValue('Черновик B')
  expect(state.writes.filter(item => item.path.endsWith('/comments'))).toHaveLength(1)
})

test('R05/R07/G9: list error is not empty, retry works and stale search error cannot replace new results', async ({ page }) => {
  const delayed = gate()
  let initialFail = true, oldStarted = false, oldFinished = false
  await workerFixture(page, async (route, url) => {
    if (url.pathname !== '/api/quick-notes') return false
    if (url.searchParams.get('search') === 'old') {
      oldStarted = true
      await delayed.promise
      await route.fulfill({ status: 503, json: { detail: 'Старая ошибка поиска' } })
      oldFinished = true
      return true
    }
    if (!initialFail) return false
    await route.fulfill({ status: 503, json: { detail: 'Список недоступен' } })
    return true
  })
  await page.goto('/quick-notes')
  await expect(page.getByRole('alert')).toContainText('Список недоступен')
  await expect(page.getByText('Заметок пока нет.', { exact: true })).toHaveCount(0)
  initialFail = false
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Заметка A', exact: true })).toBeVisible()
  const ungrouped = page.getByRole('button', { name: 'Без группы', exact: true })
  await ungrouped.click()
  await expect(ungrouped).toHaveAttribute('aria-pressed', 'true')
  await expect(ungrouped).toHaveClass(/bg-primary/)
  const search = page.getByRole('searchbox', { name: 'Поиск заметок' })
  await search.fill('old')
  await expect.poll(() => oldStarted).toBe(true)
  await search.fill('Заметка B')
  await expect(page.getByRole('link', { name: 'Заметка B', exact: true })).toBeVisible()
  delayed.release()
  await expect.poll(() => oldFinished).toBe(true)
  await expect(page.getByText('Старая ошибка поиска', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Заметка B', exact: true })).toBeVisible()
})

test('R05: late note A cannot replace selected B', async ({ page }) => {
  const delayed = gate()
  let started = false, finished = false
  await workerFixture(page, async (route, url) => {
    if (url.pathname !== `/api/quick-notes/${ids[0]}`) return false
    started = true
    await delayed.promise
    await route.fulfill({ json: note() })
    finished = true
    return true
  })
  await page.goto(`/quick-notes/${ids[0]}`)
  await expect.poll(() => started).toBe(true)
  await navigateWithinApp(page, `/quick-notes/${ids[1]}`)
  await expect(page.getByRole('heading', { name: 'Заметка B' })).toBeVisible()
  delayed.release()
  await expect.poll(() => finished).toBe(true)
  await expect(page.getByRole('heading', { name: 'Заметка B' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Заметка A' })).toHaveCount(0)
})

test('R03/R09: creating B initializes review only from B and both dialogs contain focus', async ({ page }) => {
  const state = await workerFixture(page)
  await page.goto('/feedback')
  const detailsTrigger = page.getByRole('button', { name: /Обращение A/ })
  await detailsTrigger.click()
  const detailA = page.getByRole('dialog', { name: 'Обращение A' })
  await expect(detailA.getByLabel('Решение коротко')).toHaveValue('Итог A')
  await detailA.getByRole('button', { name: 'Закрыть обращение' }).click()
  await expect(detailsTrigger).toBeFocused()
  const trigger = page.getByRole('button', { name: 'Создать', exact: true })
  await trigger.click()
  const create = page.getByRole('dialog', { name: 'Новое обращение' })
  await expect.poll(() => create.evaluate(element => element.contains(document.activeElement))).toBe(true)
  for (let index = 0; index < 36; index += 1) {
    const key = index < 18 ? 'Tab' : 'Shift+Tab'
    const before = await page.evaluate(() => {
      const element = document.activeElement
      return { tag: element?.tagName, label: element?.getAttribute('aria-label') || element?.closest('label')?.textContent?.trim() }
    })
    await page.keyboard.press(key)
    await expect.poll(() => create.evaluate(element => ({
      inside: element.contains(document.activeElement), activeTag: document.activeElement?.tagName,
    })), { message: `${key} step ${index + 1}, from ${JSON.stringify(before)}` }).toMatchObject({ inside: true })
  }
  await page.keyboard.press('Escape')
  await expect(create).toBeHidden()
  await expect(trigger).toBeFocused()
  await trigger.click()
  await create.getByLabel('Заголовок', { exact: true }).fill('Обращение B')
  await create.getByLabel('Описание', { exact: true }).fill('Описание B')
  await create.getByLabel('Ссылка / номер / правило').fill('Контекст B')
  await create.getByLabel('Ожидаемый результат').fill('Результат B')
  await create.getByLabel('Влияние', { exact: true }).fill('Влияние B')
  await create.getByLabel('Ссылки на доказательства').fill('https://example.invalid/b')
  await create.getByRole('button', { name: 'Создать', exact: true }).click()
  const detailB = page.getByRole('dialog', { name: 'Обращение B' })
  await expect(detailB.getByLabel('Решение коротко')).toHaveValue('')
  await expect(detailB.getByLabel('Ссылки на доказательства')).toHaveValue('https://example.invalid/b')
  await expect.poll(() => detailB.evaluate(element => element.contains(document.activeElement))).toBe(true)
  await detailB.getByRole('button', { name: 'Сохранить решение' }).click()
  await expect.poll(() => state.writes.filter(item => item.method === 'PATCH').length).toBe(1)
  expect(state.writes.find(item => item.method === 'PATCH')).toMatchObject({ path: `/api/feedback/${ids[1]}`, body: {
    object_ref: 'Контекст B', expected_result: 'Результат B', impact: 'Влияние B', evidence_links: ['https://example.invalid/b'], decision_summary: null,
  } })
  await detailB.getByRole('button', { name: 'Закрыть обращение' }).click()
  await expect(trigger).toBeFocused()
})

test('R04/R07: feedback save locks fields and close; refresh failure keeps initialized detail and never duplicates create', async ({ page }) => {
  const delayed = gate()
  let refreshFails = false
  const state = await workerFixture(page, async (route, url) => {
    if (url.pathname !== '/api/feedback') return false
    if (route.request().method() === 'POST') {
      await delayed.promise
      refreshFails = true
      await route.fulfill({ json: { ...feedback(ids[1], 'Обращение B'), ...route.request().postDataJSON() } })
      return true
    }
    if (!refreshFails) return false
    await route.fulfill({ status: 503, json: { detail: 'Реестр недоступен' } })
    return true
  })
  await page.goto('/feedback')
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Новое обращение' })
  await dialog.getByLabel('Заголовок', { exact: true }).fill('Обращение B')
  await dialog.getByLabel('Описание', { exact: true }).fill('Описание B')
  await dialog.getByRole('button', { name: 'Создать', exact: true }).click()
  await expect(dialog.getByLabel('Заголовок', { exact: true })).toBeDisabled()
  await expect(dialog.getByRole('button', { name: 'Закрыть обращение' })).toBeDisabled()
  delayed.release()
  const detail = page.getByRole('dialog', { name: 'Обращение B' })
  await expect(detail).toBeVisible()
  await detail.getByRole('button', { name: 'Закрыть обращение' }).click()
  await expect(page.getByRole('alert')).toContainText('Реестр недоступен')
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  expect(state.writes.filter(item => item.method === 'POST' && item.path === '/api/feedback')).toHaveLength(1)
})

test('R07: note share recipient error is not empty and can be retried', async ({ page }) => {
  let fail = true
  await workerFixture(page, async (route, url) => {
    if (url.pathname !== '/api/note-groups/share/recipients' || !fail) return false
    await route.fulfill({ status: 503, json: { detail: 'Получатели недоступны' } })
    return true
  })
  await page.goto('/quick-notes')
  await page.getByRole('checkbox', { name: 'Выбрать заметку: Заметка A' }).check()
  await page.getByRole('button', { name: 'Открыть доступ', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Открыть доступ' })
  await expect(dialog.getByRole('alert')).toContainText('Получатели недоступны')
  await expect(dialog.getByText('Нет принятых контактов в выбранном списке')).toHaveCount(0)
  fail = false
  await dialog.getByRole('button', { name: 'Повторить загрузку' }).click()
  await expect(dialog.getByRole('checkbox', { name: 'Коллега' })).toBeVisible()
  await expect(page).toHaveURL(/quick-notes/)
})

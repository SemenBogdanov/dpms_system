import { expect, test } from '@playwright/test'
import { stamp, user } from './review-main-helpers'
import {
  competency, competencyId, deferred, install, projectA, projectB,
  project, qContract, respond, summary,
} from './review-projects-competencies-helpers'

test('R07: portfolio read failure has a retry, not a false empty state; overdue agrees with detail', async ({ page }) => {
  let fail = true
  await install(page, async (route, url) => {
    if (url.pathname === '/api/work-entities' && fail) return respond(route, { detail: 'Портфель временно недоступен' }, 503)
    if (url.pathname.endsWith('/summary')) return respond(route, summary(url.pathname.split('/')[3], 2))
    return false
  })
  await page.goto('/work-entities')
  await expect(page.getByRole('button', { name: 'Повторить загрузку проектов' })).toBeVisible()
  await expect(page.getByText('Проектов пока нет')).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: 'Повторить загрузку проектов' }).click()
  const portfolio = page.getByRole('region', { name: 'Обзор проектов и целей' })
  await expect(portfolio.getByText('Есть просрочка')).toHaveCount(2)
  await portfolio.getByRole('button', { name: /Проект А/ }).click()
  await expect(page.locator('[aria-label="Статус выбранного проекта"]').getByText('Есть просрочка')).toBeVisible()
})

for (const lateStatus of [200, 503]) {
  test(`R05: late A ${lateStatus} cannot replace B or end B loading; URL Back/Forward`, async ({ page }) => {
    const a = deferred(), b = deferred()
    let aStarted = false, bStarted = false, aFinished = false
    await install(page, async (route, url) => {
      if (url.pathname === `/api/work-entities/${projectA}/links` && !aFinished) {
        aStarted = true
        await a.promise
        aFinished = true
        return respond(route, lateStatus === 200 ? [] : { detail: 'Старая ошибка проекта А' }, lateStatus)
      }
      if (url.pathname === `/api/work-entities/${projectB}/links`) {
        bStarted = true
        await b.promise
        return respond(route, [])
      }
      return false
    })
    await page.goto(`/work-entities?entity=${projectA}`)
    await expect.poll(() => aStarted).toBe(true)
    await page.getByRole('combobox', { name: 'Выбрать проект или цель' }).selectOption(projectB)
    await expect.poll(() => bStarted).toBe(true)
    a.release()
    await expect.poll(() => aFinished).toBe(true)
    await expect(page.getByText('Загрузка', { exact: true })).toBeVisible()
    await expect(page.getByText('Старая ошибка проекта А')).toHaveCount(0)
    b.release()
    await expect(page.getByText('Описание проекта', { exact: true })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`entity=${projectB}`))
    await page.goBack()
    await expect(page.getByRole('combobox', { name: 'Выбрать проект или цель' })).toHaveValue(projectA)
    await page.goForward()
    await expect(page.getByRole('combobox', { name: 'Выбрать проект или цель' })).toHaveValue(projectB)
    await page.reload()
    await expect(page.getByRole('combobox', { name: 'Выбрать проект или цель' })).toHaveValue(projectB)
  })
}

test('R05/R07: detail B failure does not show A, then retries in place', async ({ page }) => {
  let fail = true
  await install(page, async (route, url) => {
    if (url.pathname === `/api/work-entities/${projectB}/links` && fail) return respond(route, { detail: 'Ошибка проекта Б' }, 503)
    return false
  })
  await page.goto(`/work-entities?entity=${projectA}`)
  await expect(page.getByText('Описание проекта', { exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: 'Выбрать проект или цель' }).selectOption(projectB)
  await expect(page.getByRole('button', { name: 'Повторить загрузку проекта', exact: true })).toBeVisible()
  await expect(page.getByText('Описание проекта', { exact: true })).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: 'Повторить загрузку проекта', exact: true }).click()
  await expect(page.getByText('Описание проекта', { exact: true })).toBeVisible()
})

test('R06: wizard preserves dirty input and retries opening the created ID without another POST', async ({ page }) => {
  let creates = 0, failRefresh = false
  const save = deferred()
  await install(page, async (route, url) => {
    if (url.pathname === '/api/project-cockpit/projects') {
      creates += 1
      await save.promise
      failRefresh = true
      return respond(route, { entity_id: projectB }, 201)
    }
    if (url.pathname === '/api/work-entities' && failRefresh) return respond(route, { detail: 'Список не обновлён' }, 503)
    return false
  })
  await page.goto('/work-entities')
  await page.getByRole('button', { name: 'Новый проект', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Новый проект' })
  await dialog.getByPlaceholder('Например:', { exact: false }).fill('Новый синтетический проект')
  page.once('dialog', (confirm) => confirm.dismiss())
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await expect(dialog.getByPlaceholder('Например:', { exact: false })).toHaveValue('Новый синтетический проект')
  await dialog.getByPlaceholder('На 100 рабочих местах', { exact: false }).fill('Результат')
  await dialog.getByPlaceholder('Флажки размещены', { exact: false }).fill('Приёмка завершена')
  for (let step = 0; step < 3; step += 1) await dialog.getByRole('button', { name: 'Продолжить', exact: true }).click()
  await dialog.getByRole('button', { name: 'Создать черновик', exact: true }).click()
  await expect.poll(() => creates).toBe(1)
  await expect(dialog.getByRole('button', { name: 'Закрыть', exact: true })).toBeDisabled()
  save.release()
  await expect(dialog.getByRole('alert')).toContainText(projectB)
  await expect(dialog.getByRole('button', { name: 'Создать черновик', exact: true })).toHaveCount(0)
  failRefresh = false
  await dialog.getByRole('button', { name: 'Открыть созданный проект' }).click()
  await expect(dialog).toHaveCount(0)
  expect(creates).toBe(1)
  await expect(page).toHaveURL(new RegExp(`entity=${projectB}`))
  await page.getByRole('button', { name: 'Новый проект', exact: true }).click()
  await expect(page.getByRole('dialog').getByPlaceholder('Например:', { exact: false })).toHaveValue('')
})

test('R07: workspace and map initial errors keep their local retry', async ({ page }) => {
  let failWorkspace = true, failMap = true
  await install(page, async (route, url) => {
    if (url.pathname.endsWith('/workspace') && failWorkspace) return respond(route, { detail: 'План недоступен' }, 503)
    if (url.pathname.endsWith('/map') && failMap) return respond(route, { detail: 'График недоступен' }, 503)
    return false
  })
  await page.goto(`/work-entities?entity=${projectA}`)
  await expect(page.getByRole('button', { name: 'Повторить загрузку плана' })).toBeVisible()
  failWorkspace = false
  await page.getByRole('button', { name: 'Повторить загрузку плана' }).click()
  await expect(page.getByText('Описание проекта', { exact: true })).toBeVisible()
  failWorkspace = true
  await page.getByRole('navigation', { name: 'Разделы выбранного проекта' }).getByRole('button', { name: 'План', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Повторить загрузку плана' })).toBeVisible()
  failWorkspace = false
  await page.getByRole('button', { name: 'Повторить загрузку плана' }).click()
  await expect(page.getByText('Операции проекта', { exact: true })).toBeVisible()
  await page.getByRole('navigation', { name: 'Разделы выбранного проекта' }).getByRole('button', { name: 'График', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Повторить загрузку графика' })).toBeVisible()
  failMap = false
  await page.getByRole('button', { name: 'Повторить загрузку графика' }).click()
  await expect(page.getByText('График проекта', { exact: true })).toBeVisible()
})

test('A01/R06: Enter searches instead of linking A; successful link with failed refresh is not resubmitted', async ({ page }) => {
  let links = 0, failWorkspace = false
  let payload: { task_id?: string } = {}
  await install(page, async (route, url) => {
    if (url.pathname.endsWith('/execution-contract') && route.request().method() === 'POST') {
      links += 1
      payload = route.request().postDataJSON()
      failWorkspace = true
      return respond(route, qContract)
    }
    if (url.pathname.endsWith('/workspace') && failWorkspace) return respond(route, { detail: 'Не удалось обновить план' }, 503)
    return false
  })
  await page.goto(`/work-entities?entity=${projectA}`)
  await page.getByRole('navigation', { name: 'Разделы выбранного проекта' }).getByRole('button', { name: 'План', exact: true }).click()
  await page.getByRole('button', { name: 'Q-пул', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Связать готовую' }).click()
  await dialog.getByRole('radio').check()
  const search = dialog.getByPlaceholder('Номер или название Q-задачи')
  await search.fill('qb')
  await search.press('Enter')
  await expect(dialog.getByText('Q-задача qb', { exact: false })).toBeVisible()
  expect(links).toBe(0)
  await dialog.getByRole('radio').check()
  await dialog.getByRole('button', { name: 'Связать Q-задачу', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Обновить проект' })).toBeVisible()
  expect(payload.task_id).toBe('qb')
  failWorkspace = false
  await dialog.getByRole('button', { name: 'Обновить проект' }).click()
  await expect(dialog).toHaveCount(0)
  expect(links).toBe(1)
})

test('R07: competency access failure recovers; chosen section survives reload and Back', async ({ page }) => {
  let fail = true
  await install(page, async (route, url) => url.pathname === '/api/competencies/access' && fail
    ? respond(route, { detail: 'Доступ временно недоступен' }, 503) : false)
  await page.goto('/competencies')
  await expect(page.getByRole('button', { name: 'Повторить загрузку раздела' })).toBeVisible()
  fail = false
  await page.getByRole('button', { name: 'Повторить загрузку раздела' }).click()
  await page.getByRole('button', { name: /^ИПР/ }).click()
  await expect(page).toHaveURL(/section=plan/)
  await page.reload()
  await expect(page.getByText('Мой индивидуальный план развития', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Назад', exact: true }).click()
  await page.goBack()
  await expect(page).toHaveURL(/section=plan/)
})

test('R06: competency create and assignment failure retain ID; retry only assigns and preserves new draft', async ({ page }) => {
  let creates = 0, assigns = 0
  const save = deferred()
  await install(page, async (route, url) => {
    if (url.pathname === '/api/competencies/constructor' && route.request().method() === 'POST') {
      creates += 1
      await save.promise
      return respond(route, competency, 201)
    }
    if (url.pathname.endsWith('/assign') && route.request().method() === 'POST') {
      assigns += 1
      return assigns === 1 ? respond(route, { detail: 'Назначение недоступно' }, 503)
        : respond(route, { id: 'assignment', link: '/competencies/assignments/assignment' })
    }
    return false
  })
  await page.goto('/competencies?section=constructor')
  await page.getByPlaceholder('Название компетенции').fill('Новый опрос')
  await page.getByPlaceholder('Текст вопроса').fill('Вопрос')
  await page.getByPlaceholder('Вариант 1', { exact: true }).fill('Да')
  await page.getByPlaceholder('Вариант 2', { exact: true }).fill('Нет')
  await page.locator('select').filter({ has: page.locator('option[value="' + user.id + '"]') }).selectOption(user.id)
  await page.getByRole('button', { name: 'Создать', exact: true }).click()
  await expect.poll(() => creates).toBe(1)
  await expect(page.getByPlaceholder('Название компетенции')).toBeDisabled()
  save.release()
  await expect(page.getByRole('alert')).toContainText(competencyId)
  await page.getByPlaceholder('Название компетенции').fill('Следующий черновик')
  await page.getByRole('button', { name: 'Повторить назначение' }).click()
  await expect(page.getByRole('link', { name: 'Открыть назначение' })).toBeVisible()
  await expect(page.getByPlaceholder('Название компетенции')).toHaveValue('Следующий черновик')
  expect({ creates, assigns }).toEqual({ creates: 1, assigns: 2 })
})

test('R07/R11: failed assignment read cannot save empty access; retry and dirty close protection', async ({ page }) => {
  let fail = true, writes = 0
  await install(page, async (route, url) => {
    if (url.pathname.endsWith('/report') && fail) return respond(route, { detail: 'Назначения недоступны' }, 503)
    if (url.pathname.endsWith('/assignments') && route.request().method() === 'PUT') {
      writes += 1
      return respond(route, competency)
    }
    return false
  })
  await page.goto('/competencies?section=constructor')
  await page.getByRole('button', { name: 'Доступ', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('button', { name: 'Сохранить', exact: true })).toBeDisabled()
  await expect(dialog.getByRole('button', { name: 'Повторить загрузку назначений' })).toBeVisible()
  expect(writes).toBe(0)
  fail = false
  await dialog.getByRole('button', { name: 'Повторить загрузку назначений' }).click()
  await expect(dialog.getByRole('checkbox')).toBeChecked()
  await dialog.getByRole('checkbox').uncheck()
  page.once('dialog', (confirm) => confirm.dismiss())
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('checkbox')).not.toBeChecked()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
})

test('R11/R12: long assessment is scrollable and keyboard focus cannot reach background', async ({ page }) => {
  let answers = 0
  await install(page, async (route, url) => {
    if (url.pathname.endsWith('/start')) return respond(route, {
      attempt_id: 'attempt', competency_id: competencyId, competency_title: 'Длинная оценка',
      status: 'in_progress', questions: [{ id: 'question', text: 'Вопрос '.repeat(80), question_type: 'custom', position: 0,
        choices: Array.from({ length: 10 }, (_, i) => ({ id: String(i), text: `Ответ ${i} ${'длинный текст '.repeat(12)}` })),
      }],
    })
    if (url.pathname.endsWith('/answer')) { answers += 1; return respond(route, {}) }
    return false
  })
  await page.goto('/competencies?section=assessment')
  await page.getByRole('button', { name: 'Начать', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Начать', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Длинная оценка', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: /^Ответ 9 / }).scrollIntoViewIfNeeded()
  await expect(dialog.getByRole('button', { name: /^Ответ 9 / })).toBeInViewport()
  for (let i = 0; i < 13; i += 1) {
    await page.keyboard.press('Tab')
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  }
  expect(answers).toBe(0)
})

test('R12: portfolio columns have their own horizontal scroll at 1024px', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 })
  await install(page)
  await page.goto('/work-entities')
  const portfolio = page.getByRole('region', { name: 'Обзор проектов и целей' })
  await expect(portfolio.getByRole('button', { name: /Проект А/ })).toBeVisible()
  const bounds = await portfolio.evaluate((element) => {
    element.scrollLeft = element.scrollWidth
    return { scroll: element.scrollLeft, width: element.clientWidth, content: element.scrollWidth,
      pageWidth: document.documentElement.clientWidth, pageContent: document.documentElement.scrollWidth }
  })
  expect(bounds.scroll).toBeGreaterThan(0)
  expect(bounds.content).toBeGreaterThan(bounds.width)
  expect(bounds.pageContent).toBeLessThanOrEqual(bounds.pageWidth + 1)
})

test('R11: competency editor keeps dirty input on Cancel and freezes it during a failed save', async ({ page }) => {
  const save = deferred()
  let writes = 0
  await install(page, async (route, url) => {
    if (url.pathname !== `/api/competencies/constructor/${competencyId}`) return false
    if (route.request().method() === 'PATCH') {
      writes += 1
      await save.promise
      return respond(route, { detail: 'Сохранение не выполнено' }, 503)
    }
    return respond(route, {
      ...competency,
      questions: [{ text: 'Вопрос', choices: [{ text: 'Да', position: 0 }, { text: 'Нет', position: 1 }] }],
      interpretations: [{ text: 'Интерпретация', min_score_ib: 0, max_score_ib: 100 }],
    })
  })
  await page.goto('/competencies?section=constructor')
  await page.getByRole('button', { name: 'Редактировать', exact: true }).click()
  const dialog = page.getByRole('dialog')
  const title = dialog.locator('input').first()
  await title.fill('Исправленный опрос')
  page.once('dialog', (confirm) => confirm.dismiss())
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click()
  await expect(title).toHaveValue('Исправленный опрос')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect.poll(() => writes).toBe(1)
  await expect(title).toBeDisabled()
  save.release()
  await expect(title).toBeEnabled()
  await expect(title).toHaveValue('Исправленный опрос')
  expect(writes).toBe(1)
})

test('R07: candidate-list failure does not hide backlinks; failed post-write refresh is retry-only', async ({ page }) => {
  const taskId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
  const task = {
    id: taskId, task_key: 'PT-1', task_number: 1, owner_id: user.id, title: 'Синтетическая личная задача',
    description: 'Описание', notes: '', status: 'inbox', priority: 'medium', category: null,
    project: null, context: null, responsible: null, tags: [], acceptance_criteria: null,
    next_step: null, next_step_at: null, start_at: null, due_at: null, waiting_for: null,
    blocked_reason: null, impact: null, effort: null, source_quick_note_id: null,
    promoted_task_id: null, linked_task_id: null, promoted_at: null, promoted_task: null,
    execution_task: null, created_at: stamp, updated_at: stamp,
  }
  let failCandidates = true, failLinks = false, deleted = false, deletes = 0
  await install(page, async (route, url) => {
    if (url.pathname === '/api/personal-tasks') return respond(route, [task])
    if (url.pathname === `/api/personal-tasks/${taskId}`) return respond(route, task)
    if (url.pathname === '/api/note-groups/backlinks') return respond(route, { notes: [], groups: [] })
    if (url.pathname === '/api/work-entities') return failCandidates
      ? respond(route, { detail: 'Список недоступен' }, 503) : respond(route, [project()])
    if (url.pathname === '/api/work-entities/links/by-target') return failLinks
      ? respond(route, { detail: 'Связи недоступны' }, 503)
      : respond(route, deleted ? [] : [{ link_id: 'link', entity_id: projectA, entity_title: 'Проект А', relation_type: 'contains', access_role: 'owner' }])
    if (url.pathname === `/api/work-entities/${projectA}/links/link` && route.request().method() === 'DELETE') {
      deletes += 1
      deleted = true
      failLinks = true
      return respond(route, {})
    }
    return false
  })
  await page.goto(`/personal-tasks?task=${taskId}`)
  await expect(page.getByRole('link', { name: 'Проект А', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Добавить в проект или цель' })).toBeDisabled()
  failCandidates = false
  await page.getByRole('button', { name: 'Повторить загрузку связей' }).click()
  await page.getByRole('button', { name: 'Убрать связь с Проект А' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Изменение сохранено' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Убрать связь с Проект А' })).toBeDisabled()
  failLinks = false
  await page.getByRole('button', { name: 'Повторить загрузку связей' }).click()
  await expect(page.getByRole('link', { name: 'Проект А', exact: true })).toHaveCount(0)
  expect(deletes).toBe(1)
})

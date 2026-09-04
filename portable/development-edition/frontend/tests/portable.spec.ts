import { expect, test } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

test('first-run setup and development workspace', async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.goto('/')
  await page.waitForFunction(() => document.body.innerText.includes('Первичная настройка') || document.body.innerText.includes('Войти'))

  if (await page.getByRole('heading', { name: 'Первичная настройка' }).isVisible().catch(() => false)) {
    await page.getByLabel('ФИО администратора').fill('UI Test Admin')
    await page.getByLabel('Электронная почта').fill('ui-test@example.com')
    await page.getByLabel('Пароль', { exact: true }).fill(`Portable${2026}!Test`)
    await page.getByRole('button', { name: 'Создать администратора' }).click()
  } else {
    await page.getByLabel('Электронная почта').fill('ui-test@example.com')
    await page.getByLabel('Пароль', { exact: true }).fill(`Portable${2026}!Test`)
    await page.getByRole('button', { name: 'Войти' }).click()
  }

  await expect(page.getByRole('heading', { name: 'Развитие компетенций' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Пройти опрос/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Индивидуальный план развития/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Конструктор компетенций/ })).toBeVisible()
  await expect(page.getByText('84', { exact: true })).toHaveCount(0)

  await page.screenshot({
    path: testInfo.outputPath(`development-${testInfo.project.name}.png`),
    fullPage: true,
  })

  await page.getByRole('button', { name: /Пройти опрос/ }).click()
  await expect(page.getByText('Доступные оценки')).toBeVisible()
  await expect(page.getByText('14 вопросов')).toHaveCount(6)

  await page.getByRole('button', { name: 'Описание' }).first().click()
  const descriptionDialog = page.locator('.portable-modal-surface')
  await expect(descriptionDialog).toBeVisible()
  await expect(descriptionDialog).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await expect(descriptionDialog.locator('.text-slate-700').first()).toHaveCSS('color', 'rgb(51, 65, 85)')
  await page.screenshot({
    path: testInfo.outputPath(`description-modal-system-dark-${testInfo.project.name}.png`),
  })
  await descriptionDialog.getByRole('button', { name: 'Закрыть' }).click()

  await page.getByRole('button', { name: 'Начать' }).first().click()
  const startDialog = page.locator('.portable-modal-surface')
  await expect(startDialog.getByRole('heading', { name: 'Начать оценку' })).toBeVisible()
  await expect(startDialog).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await startDialog.getByRole('button', { name: 'Отмена' }).click()

  await page.getByRole('button', { name: 'Сотрудники' }).click()
  const usersDialog = page.getByRole('dialog', { name: 'Сотрудники' })
  await expect(usersDialog).toBeVisible()
  await expect(usersDialog).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await page.screenshot({
    path: testInfo.outputPath(`users-modal-system-dark-${testInfo.project.name}.png`),
  })
  await usersDialog.getByRole('button', { name: 'Закрыть' }).click()
})

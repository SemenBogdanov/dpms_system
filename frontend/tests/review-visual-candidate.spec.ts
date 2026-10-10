import { expect, test } from '@playwright/test'
import { article, fixture } from './review-main-helpers'

for (const theme of ['light', 'dark', 'rose']) {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }, { width: 390, height: 844 }]) {
    test(`Local candidate knowledge ${theme} ${viewport.width}`, async ({ page }, info) => {
      await page.setViewportSize(viewport)
      await fixture(page, async (route, url) => {
        if (url.pathname !== '/api/knowledge') return false
        await route.fulfill({ json: ['A', 'B', 'C'].map(article) })
        return true
      })
      await page.addInitScript((value) => localStorage.setItem('dpms-theme', value), theme)
      await page.goto('/knowledge?article=A')
      await expect(page.locator('#knowledge-article-reader').getByRole('heading', { name: 'Статья A' })).toBeVisible()
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await page.screenshot({ path: info.outputPath(`knowledge-${theme}-${viewport.width}.png`), fullPage: true })
      await page.getByRole('button', { name: 'Редактировать', exact: true }).click()
      const dialog = page.getByRole('dialog')
      await expect(dialog.getByRole('textbox', { name: 'Название', exact: true })).toHaveValue('Статья A')
      const save = dialog.getByRole('button', { name: 'Сохранить', exact: true })
      await save.scrollIntoViewIfNeeded()
      const bounds = await save.boundingBox()
      expect(bounds).not.toBeNull()
      expect(bounds!.x).toBeGreaterThanOrEqual(0)
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width)
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height)
      await page.screenshot({ path: info.outputPath(`knowledge-editor-${theme}-${viewport.width}.png`) })
    })
  }
}

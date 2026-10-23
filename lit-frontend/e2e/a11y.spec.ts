import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { answerForm, startSampleReview } from './helpers'

async function audit(page: import('@playwright/test').Page, label: string) {
  await page.waitForTimeout(450) // let fade/rise-in animations finish: axe measures colour mid-animation otherwise
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(bad.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`), `${label}: serious/critical accessibility violations`).toEqual([])
}

test.describe('accessibility (WCAG 2.1 AA, no serious or critical violations)', () => {
  for (const scheme of ['light', 'dark'] as const) {
    test.describe(scheme, () => {
      test.use({ colorScheme: scheme })
      test('empty state and demo', async ({ page }) => {
        await page.goto('/'); await audit(page, 'empty state')
        await page.goto('/demo'); await audit(page, 'demo start')
      })
      test('a conversation with every card, the map panel and the dialogs', async ({ page }) => {
        await startSampleReview(page)
        await audit(page, 'needs-input form')
        await answerForm(page)
        await expect(page.getByText('Indicative outcome estimate')).toBeVisible()
        await audit(page, 'conversation with cards')
        await page.getByRole('button', { name: 'Open map' }).click()
        await expect(page.getByRole('complementary', { name: 'Details panel' }).locator('canvas').first()).toBeVisible()
        await audit(page, 'map panel')
        await page.getByRole('button', { name: 'Close panel' }).click()
        await page.getByRole('button', { name: 'Matters' }).click()
        await audit(page, 'matters dialog')
      })
    })
  }
})

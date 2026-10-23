import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 390, height: 844 } })

test('on a phone the sidebar is a drawer, the composer fits, and nothing scrolls sideways', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('complementary', { name: 'Sidebar' })).toBeHidden()
  await expect(page.getByRole('textbox', { name: 'Message' })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  await page.getByRole('button', { name: 'Open menu' }).click()
  await expect(page.getByRole('button', { name: 'New chat' })).toBeVisible()
})

test('on a phone a review runs and the map opens as a full-screen sheet', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /Review a sample appeal/ }).click()
  await expect(page.getByText('Two details needed')).toBeVisible()
  await page.getByRole('radio', { name: /The accused/ }).click()
  await page.locator('input[type=date]').fill('2024-06-14')
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: 'Open map' }).click()
  const panel = page.getByLabel('Details panel')
  await expect(panel).toBeVisible()
  const box = await panel.boundingBox()
  expect(box!.width).toBeGreaterThanOrEqual(385)
})

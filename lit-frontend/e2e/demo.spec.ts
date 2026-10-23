import { expect, test } from '@playwright/test'

test.describe('recorded sample session', () => {
  test('plays end to end offline of any server call, with the honest banner', async ({ page }) => {
    const apiCalls: string[] = []
    page.on('request', (r) => { if (r.url().includes('/agent/chat') || r.url().includes('/cases/')) apiCalls.push(r.url()) })
    await page.goto('/demo')
    await expect(page.getByRole('note')).toContainText('fictional matter')
    await expect(page.getByRole('note')).toContainText('Nothing here is sent to a server')
    await page.getByRole('button', { name: '4×' }).click()
    await page.getByLabel('Autoplay').check()
    await page.getByRole('button', { name: /Start the session/ }).click()
    await expect(page.getByText('Indicative outcome estimate')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Scenario comparison')).toBeVisible()
    await expect(page.getByRole('button', { name: /^Sources · \d+ passages? from the document/ })).toBeVisible()
    await expect(page.getByText('That’s the walkthrough')).toBeVisible({ timeout: 60_000 })
    expect(apiCalls).toEqual([])
  })

  test('the form is pre-filled with the recorded answer and waits for Continue', async ({ page }) => {
    await page.goto('/demo')
    await page.getByRole('button', { name: '4×' }).click()
    await page.getByRole('button', { name: /Start the session/ }).click()
    // turn 1 plays after Start; turn 2 (map) and turn 3 ("How likely…") are each sent with the Send button
    await page.getByRole('button', { name: /^Send/ }).click({ timeout: 30_000 })
    await page.getByRole('button', { name: /^Send/ }).click({ timeout: 30_000 })
    await expect(page.getByText('Two details needed')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('radio', { name: /The accused/ })).toHaveAttribute('aria-checked', 'true')
    await page.getByRole('button', { name: 'Continue' }).click()
    await expect(page.getByText('Indicative outcome estimate')).toBeVisible({ timeout: 30_000 })
  })

  test('"Run this live" starts a real conversation on the same matter', async ({ page }) => {
    await page.goto('/demo')
    await page.getByRole('button', { name: 'Run this live on the same matter' }).click()
    await expect(page).toHaveURL(/\/c\//)
    await expect(page.getByText('Two details needed')).toBeVisible()
  })
})

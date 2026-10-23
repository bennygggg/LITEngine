import { expect, type Page } from '@playwright/test'

export async function startSampleReview(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: /Review a sample appeal/ }).click()
  await expect(page.getByText('Two details needed')).toBeVisible()
}

export async function answerForm(page: Page, who = /The accused/, date = '2024-06-14') {
  await page.getByRole('radio', { name: who }).click()
  await page.locator('input[type=date]').fill(date)
  await page.getByRole('button', { name: 'Continue' }).click()
}

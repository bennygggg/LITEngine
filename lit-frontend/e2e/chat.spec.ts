import { expect, test } from '@playwright/test'
import { answerForm, startSampleReview } from './helpers'

test.describe('live chat flow (deterministic mode)', () => {
  test('a full review: profile, then the form, then precedents, map and an honest outcome', async ({ page }) => {
    await startSampleReview(page)
    await expect(page.getByText('Case profile', { exact: true }).first()).toBeVisible()
    // never-infer: nothing is pre-selected and Continue is disabled until the user answers
    await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled()
    await expect(page.getByRole('radio', { checked: true })).toHaveCount(0)
    await answerForm(page)
    await expect(page.getByText('Closest matches in the library').first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Open map' })).toBeVisible()
    await expect(page.getByText('Indicative outcome estimate')).toBeVisible()
    await expect(page.getByText(/Indicative research estimate/)).toBeVisible()
    // the figure is rounded to 5 and never shown as a "match" percentage on precedents
    await expect(page.getByText(/about \d*[05]%/).first()).toBeVisible()
    await expect(page.getByText(/\d+% match/)).toHaveCount(0)
  })

  test('the + menu offers every tool, and picking one adds a chip', async ({ page }) => {
    await startSampleReview(page)
    await page.getByRole('radio', { name: /The accused/ }).click()
    await page.locator('input[type=date]').fill('2024-06-14')
    await page.getByRole('button', { name: 'Continue' }).click()
    await expect(page.getByText('Indicative outcome estimate')).toBeVisible()
    await page.getByRole('button', { name: 'Add a matter or pick a tool' }).click()
    for (const name of ['Read the case', 'Find precedents', 'Map the argument', 'Assess the outcome', 'Explore scenarios', 'Ask about the case', 'Full case review']) {
      await expect(page.getByRole('menuitem', { name: new RegExp(name) })).toBeVisible()
    }
    await page.getByRole('menuitem', { name: /Explore scenarios/ }).click()
    await expect(page.getByRole('button', { name: 'Remove tool' })).toBeVisible()
    await page.getByRole('textbox', { name: 'Message' }).fill('if the State were the appellant')
    await page.keyboard.press('Enter')
    await expect(page.getByText('Scenario comparison')).toBeVisible()
    await expect(page.getByText('If the State were the appellant')).toBeVisible()
    await expect(page.getByText('Large effect')).toBeVisible()
  })

  test('opening the map shows an interactive canvas and the precedent reader highlights a cited judgment', async ({ page }) => {
    await startSampleReview(page)
    await answerForm(page)
    await expect(page.getByRole('button', { name: 'Open map' })).toBeVisible()
    await page.getByRole('button', { name: 'Open map' }).click()
    const panel = page.getByRole('complementary', { name: 'Details panel' })
    await expect(panel.locator('canvas').first()).toBeVisible()
    await expect(panel.getByRole('tab', { name: 'List' })).toBeVisible()
    await panel.getByRole('tab', { name: 'List' }).click()
    await expect(panel.getByText('Issue', { exact: true }).first()).toBeVisible()
    await panel.getByRole('button', { name: 'Close panel' }).click()
    await expect(panel).toHaveCount(0)
    // a citation chip in the narration opens the precedents reader
    await page.getByRole('button', { name: /Open source P1/ }).first().click()
    await expect(panel.getByText(/cosine \d\.\d\d/).first()).toBeVisible()
    await expect(panel.getByText('P1', { exact: true })).toBeVisible()
  })

  test('a question about the document returns passages and opens them in context', async ({ page }) => {
    await startSampleReview(page)
    await answerForm(page)
    await expect(page.getByText('Indicative outcome estimate')).toBeVisible()
    await page.getByRole('textbox', { name: 'Message' }).fill('What does the judgment say about the delay in lodging the FIR?')
    await page.keyboard.press('Enter')
    await expect(page.getByText('Sources in the document')).toBeVisible()
    await page.getByRole('button', { name: /View in document|S1/ }).first().click()
    const panel = page.getByRole('complementary', { name: 'Details panel' })
    await expect(panel.locator('mark')).toBeVisible()
    await expect(panel.locator('mark')).toContainText(/eleven|delay|FIR/i)
  })

  test('conversations persist across a reload', async ({ page }) => {
    await startSampleReview(page)
    await page.reload()
    await expect(page.getByText('Two details needed')).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Conversations' }).getByRole('link').first()).toBeVisible()
  })
})

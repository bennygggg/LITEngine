import { expect, test } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const fixture = path.resolve(here, '../../lit-backend/tests/fixtures/criminal_case.txt')

test.describe('matters', () => {
  test('uploading a document attaches it and the first question works', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Add a matter or pick a tool' }).click()
    await page.getByRole('menuitem', { name: /^Add a case…/ }).click()
    await page.getByLabel('Choose a file to upload').setInputFiles(fixture)
    await expect(page.getByRole('button', { name: 'Detach matter' })).toBeVisible()
    await expect(page.getByText('criminal case').first()).toBeVisible() // titled from the file name
    await page.getByRole('textbox', { name: 'Message' }).fill('Who are the parties and which court is this?')
    await page.keyboard.press('Enter')
    await expect(page.getByText('Case profile', { exact: true }).first()).toBeVisible()
  })

  test('an unsupported file type is explained, not silently dropped', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Add a matter or pick a tool' }).click()
    await page.getByRole('menuitem', { name: /^Add a case…/ }).click()
    await page.getByLabel('Choose a file to upload').setInputFiles({ name: 'notes.xyz', mimeType: 'application/octet-stream', buffer: Buffer.from('hello') })
    await expect(page.getByRole('alert')).toContainText(/Unsupported file type|\.txt/i)
  })

  test('the matters library lists fictional samples and searches them', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Matters', exact: true }).click()
    await expect(page.getByText('Mohan Lal v. State of Rajasthan')).toBeVisible()
    await page.getByRole('textbox', { name: 'Search matters' }).fill('138')
    await expect(page.getByText('Anita Desai v. State of Gujarat')).toBeVisible()
    await expect(page.getByText('Mohan Lal v. State of Rajasthan')).toHaveCount(0)
    await page.getByRole('button', { name: /Anita Desai/ }).click()
    await expect(page.getByRole('button', { name: 'Detach matter' })).toBeVisible()
  })

  test('pasted text becomes a matter', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Matters', exact: true }).click()
    await page.getByRole('tab', { name: 'Paste text' }).click()
    await page.getByLabel('Case text').fill(Array(60).fill('The appellant was convicted under Section 302 of the Indian Penal Code.').join(' '))
    await page.getByRole('button', { name: 'Use this text' }).click()
    await expect(page.getByRole('button', { name: 'Detach matter' })).toBeVisible()
  })
})

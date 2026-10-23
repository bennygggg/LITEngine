import { expect, test, type Page } from '@playwright/test'
import { answerForm, startSampleReview } from './helpers'

const docOverflow = (page: Page) => page.evaluate(() => ({ y: window.scrollY, doc: document.documentElement.scrollHeight, view: document.documentElement.clientHeight }))

test.describe('the interface frame never moves', () => {
  test('wheel-scrolling past the end of a long conversation does not scroll the page itself', async ({ page }) => {
    await startSampleReview(page)
    await answerForm(page)
    await expect(page.getByText('Indicative outcome estimate')).toBeVisible()
    await page.mouse.move(700, 400)
    for (let i = 0; i < 10; i++) { await page.mouse.wheel(0, 700); await page.waitForTimeout(40) }
    const o = await docOverflow(page)
    expect(o.y).toBe(0)
    expect(o.doc).toBeLessThanOrEqual(o.view)
    await expect(page.getByRole('navigation', { name: 'Conversations' })).toBeInViewport()   // the sidebar is still where it was
  })

  test('the same holds on the sample session', async ({ page }) => {
    await page.goto('/demo')
    await page.getByRole('button', { name: '4×' }).click()
    await page.getByLabel('Autoplay').check()
    await page.getByRole('button', { name: /Start the session/ }).click()
    await expect(page.getByText('That’s the walkthrough')).toBeVisible({ timeout: 60_000 })
    await page.mouse.move(700, 400)
    for (let i = 0; i < 10; i++) { await page.mouse.wheel(0, 800); await page.waitForTimeout(40) }
    const o = await docOverflow(page)
    expect(o.y).toBe(0)
    expect(o.doc).toBeLessThanOrEqual(o.view)
    await expect(page.getByRole('button', { name: 'Settings' })).toBeInViewport()
  })
})

test.describe('the argument map', () => {
  test('opens full screen, can step back to a side panel, and Esc does the same', async ({ page }) => {
    await startSampleReview(page)
    await answerForm(page)
    await page.getByRole('button', { name: 'Open map' }).click()
    const panel = page.getByLabel('Details panel')
    await expect(panel.locator('canvas').first()).toBeVisible()
    const vp = page.viewportSize()!
    const full = await panel.boundingBox()
    expect(full!.x).toBe(0); expect(full!.width).toBe(vp.width); expect(full!.height).toBe(vp.height)
    // the page behind is not reachable while the map covers it
    await expect(page.locator('div.contents[inert]')).toHaveCount(1)

    await panel.getByRole('button', { name: 'Exit full screen' }).click()
    const side = await panel.boundingBox()
    expect(side!.width).toBeLessThan(vp.width * 0.6)
    await expect(page.locator('div.contents[inert]')).toHaveCount(0)
    await expect(page.getByRole('textbox', { name: 'Message' })).toBeVisible()

    await panel.getByRole('button', { name: 'Full screen' }).click()
    expect((await panel.boundingBox())!.width).toBe(vp.width)
    await page.keyboard.press('Escape')
    expect((await panel.boundingBox())!.width).toBeLessThan(vp.width * 0.6)
  })

  test('the map is large enough to read when full screen: nodes fill the available space', async ({ page }) => {
    await startSampleReview(page)
    await answerForm(page)
    await page.getByRole('button', { name: 'Open map' }).click()
    const host = page.getByLabel('Details panel').getByRole('img', { name: /Interactive argument map/ })
    await expect(host).toBeVisible()
    const box = await host.boundingBox()
    expect(box!.width).toBeGreaterThan(1000)
  })
})

test.describe('one-liners', () => {
  test('a one-line request gets one line, on top, with the passages tucked below', async ({ page }) => {
    await startSampleReview(page)
    await answerForm(page)
    await expect(page.getByText('Indicative outcome estimate')).toBeVisible()
    await page.getByRole('textbox', { name: 'Message' }).fill('What happened exactly? One liner please')
    await page.keyboard.press('Enter')
    const sources = page.getByRole('button', { name: /^Sources · \d+ passages? from the document/ })
    await expect(sources).toBeVisible()
    const message = page.getByRole('article', { name: 'Assistant message' }).last()
    const answer = message.locator('p').first()
    await expect(answer).toBeVisible()
    expect((await answer.innerText()).trim().split(/\s+/).length).toBeLessThanOrEqual(60)
    const a = await answer.boundingBox(); const s = await sources.boundingBox()
    expect(a!.y).toBeLessThan(s!.y)                                                  // answer above the sources row
    await expect(message.getByText('Sources in the document')).toBeHidden()          // passages are collapsed
    await sources.click()
    await expect(message.getByText('Sources in the document')).toBeVisible()
  })
})

test.describe('alignment', () => {
  test('the assistant avatar sits on the same centre line as the first row of its reply', async ({ page }) => {
    await startSampleReview(page)
    await answerForm(page)
    await expect(page.getByText('Indicative outcome estimate')).toBeVisible()
    const articles = await page.getByRole('article', { name: 'Assistant message' }).all()
    expect(articles.length).toBeGreaterThan(1)
    for (const article of articles) {
      const avatar = await article.locator('span[aria-hidden]').first().boundingBox()
      // the first thing in the reply column: a step row or a paragraph; compare against its FIRST LINE (a paragraph may wrap)
      const first = await article.evaluate((el) => { const r = (el.children[1]!.children[0] as HTMLElement).getBoundingClientRect(); return { y: r.y, h: r.height } })
      const firstLine = Math.min(first.h, 25)
      expect(Math.abs(avatar!.y + avatar!.height / 2 - (first.y + firstLine / 2))).toBeLessThanOrEqual(2)
    }
  })
})

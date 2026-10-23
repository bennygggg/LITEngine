// Fails the build if the JavaScript needed for first paint grows past budget.
// "Initial" = what index.html loads eagerly (entry + vendor chunks); markdown, Cytoscape, dialogs, demo and cards-gallery are lazy.
import { readdirSync, readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { gzipSync } from 'node:zlib'
import { join } from 'node:path'

const BUDGET_KB = 170
const dir = 'dist/assets'
const html = readFileSync('dist/index.html', 'utf8')
const eager = [...html.matchAll(/(?:src|href)="\/assets\/([^"]+\.js)"/g)].map((m) => m[1])
let total = 0
for (const f of eager) {
  const kb = gzipSync(readFileSync(join(dir, f))).length / 1024
  total += kb
  console.log(`  ${f.padEnd(34)} ${kb.toFixed(1)} kB gz`)
}
const lazyHeavy = readdirSync(dir).filter((f) => /^(cytoscape|markdown)-/.test(f))
const leaked = lazyHeavy.filter((f) => eager.includes(f))
console.log(`initial JS: ${total.toFixed(1)} kB gzipped (budget ${BUDGET_KB})`)
if (leaked.length) { console.error(`FAIL: heavy chunks loaded eagerly: ${leaked.join(', ')}`); process.exit(1) }
if (total > BUDGET_KB) { console.error('FAIL: initial JavaScript is over budget'); process.exit(1) }

// The CSP allows the inline theme script by hash; if that script changes without updating vercel.json, production
// would block it (a flash of the wrong theme at best). Fail the build instead.
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1])
const csp = JSON.parse(readFileSync('vercel.json', 'utf8')).headers[0].headers.find((h) => h.key === 'Content-Security-Policy').value
for (const body of inline) {
  const hash = `'sha256-${createHash('sha256').update(body).digest('base64')}'`
  if (!csp.includes(hash)) { console.error(`FAIL: inline script hash ${hash} is not in the vercel.json Content-Security-Policy`); process.exit(1) }
}
console.log(`CSP: ${inline.length} inline script(s), all allowed by hash`)

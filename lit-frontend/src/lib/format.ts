/** Small, shared formatting helpers. Figures are always shown with tabular numerals (`.tnum`) by the caller. */

export function formatDate(iso?: string | null): string {
  if (!iso) return 'undated'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

export const yearOf = (iso?: string | null): string => (iso ? iso.slice(0, 4) : 'undated')

/** The extractor lists "Section 302" and "Section 302 IPC" separately; show each section number once, as "s.302". */
export function uniqueSections(sections: string[], limit = 12): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const s of sections) {
    const m = /\d+[A-Za-z]?/.exec(s)
    const key = m ? m[0].toUpperCase() : s
    if (seen.has(key)) continue
    seen.add(key)
    out.push(m ? `s.${key}` : s)
    if (out.length >= limit) break
  }
  return out
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function signed(n: number, digits = 1): string {
  const s = Math.abs(n).toFixed(digits)
  return n > 0 ? `+${s}` : n < 0 ? `−${s}` : s
}

export function courtLabel(tier: string, court?: string | null): string {
  return tier === 'SC' ? 'Supreme Court' : tier === 'HC' ? (court ?? 'High Court') : court ?? 'Court'
}

/** The extractor sometimes returns sentence fragments as "acts" ("Act and that the Indian Contract Act, 1872"); keep only name-like ones. */
export function cleanActs(acts: string[], limit = 4): string[] {
  const out: string[] = []
  for (const a of acts) {
    const t = a.trim()
    if (t.length > 55 || /\b(?:that|which|whether|under|and the)\b/i.test(t) || !/^[A-Z]/.test(t) || /^Act\b/.test(t)) continue
    if (!out.includes(t)) out.push(t)
    if (out.length >= limit) break
  }
  return out
}

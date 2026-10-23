/** Short, collision-safe ids for conversations, messages and runs. */
export function newId(prefix: string): string {
  const bytes = crypto.getRandomValues(new Uint8Array(8))
  return `${prefix}_${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`
}

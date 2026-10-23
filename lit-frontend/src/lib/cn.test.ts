import { cn } from './cn'

describe('cn', () => {
  it('merges conflicting Tailwind utilities, last one wins', () => {
    expect(cn('px-2 py-1', 'px-4')).toBe('py-1 px-4')
  })
  it('drops falsy values', () => {
    expect(cn('a', false && 'b', undefined, null, 'c')).toBe('a c')
  })
})

import type { Config } from 'tailwindcss'
import typography from '@tailwindcss/typography'
import animate from 'tailwindcss-animate'

// Every colour is an RGB-triplet CSS variable (src/design/tokens.css) so light/dark and the later
// restyles are a token change, never a component change.
const token = (name: string) => `rgb(var(--c-${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: token('bg'),
        surface: token('surface'),
        sunken: token('sunken'),
        border: { DEFAULT: token('border'), strong: token('border-strong') },
        ink: { DEFAULT: token('ink'), muted: token('ink-muted'), subtle: token('ink-subtle') },
        accent: { DEFAULT: token('accent'), ink: token('accent-ink'), soft: token('accent-soft') },
        side: { DEFAULT: token('side'), ink: token('side-ink'), muted: token('side-muted'), subtle: token('side-subtle'), hover: token('side-hover'), border: token('side-border') },
        tier: { favorable: token('fav'), uncertain: token('unc'), unfavorable: token('unfav') },
        node: {
          issue: token('node-issue'), claim: token('node-claim'), evidence: token('node-evidence'),
          statute: token('node-statute'), precedent: token('node-precedent'),
        },
      },
      fontFamily: {
        sans: ['"Inter Variable"', 'Inter', 'system-ui', '-apple-system', '"Segoe UI"', 'sans-serif'],
        display: ['"Newsreader Variable"', 'Newsreader', 'Georgia', '"Times New Roman"', 'serif'],
      },
      fontSize: {
        // UI scale (px): chrome 13/14, body 15, display sizes for greetings and key figures
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
        xs: ['0.75rem', { lineHeight: '1.125rem' }],
        sm: ['0.8125rem', { lineHeight: '1.25rem' }],
        base: ['0.9375rem', { lineHeight: '1.65' }],
      },
      borderRadius: { sm: '6px', md: '8px', lg: '12px', xl: '16px', composer: '12px' },
      maxWidth: { column: '46rem' },
      boxShadow: {
        raised: '0 1px 1px rgb(var(--c-shadow) / 0.03)',
        float: '0 8px 24px rgb(var(--c-shadow) / 0.12), 0 2px 6px rgb(var(--c-shadow) / 0.08)',
      },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'rise-in': { from: { opacity: '0', transform: 'translateY(4px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        caret: { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0' } },
      },
      animation: {
        'fade-in': 'fade-in 160ms ease-out',
        'rise-in': 'rise-in 180ms ease-out',
        caret: 'caret 1s steps(1) infinite',
      },
    },
  },
  plugins: [typography, animate],
} satisfies Config

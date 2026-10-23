import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CitationProvider } from './citations'
import { StreamingMarkdown, splitBlocks } from './StreamingMarkdown'

describe('splitBlocks', () => {
  it('splits on blank lines but never inside a code fence', () => {
    expect(splitBlocks('one\n\ntwo\n\n```\na\n\nb\n```\n\nthree')).toEqual(['one', 'two', '```\na\n\nb\n```', 'three'])
  })
})

describe('StreamingMarkdown', () => {
  const api = { resolve: (h: string) => (h === 'P1' ? { title: 'Basavaraju v. State of Karnataka', detail: 'High Court · 2022' } : null), open: vi.fn() }
  const renderMd = (text: string) => render(<CitationProvider value={api}><StreamingMarkdown text={text} /></CitationProvider>)

  it('renders resolvable handles as clickable chips and leaves unresolvable ones as plain text', async () => {
    renderMd('The closest match [P1] and another [P9].')
    const chip = await screen.findByRole('button', { name: /Open source P1/ })
    await userEvent.click(chip)
    expect(api.open).toHaveBeenCalledWith('P1')
    expect(screen.queryByRole('button', { name: /P9/ })).toBeNull()
    expect(screen.getByText('P9')).toBeInTheDocument()
  })

  it('does not render raw HTML or images, and drops javascript: links', async () => {
    const { container } = renderMd('Hello <img src=x onerror=alert(1)> ![x](https://evil.test/p.png?q=secret) [bad](javascript:alert(1)) [ok](https://example.com)\n\n<script>alert(1)</script>')
    await screen.findByText('ok')
    expect(container.querySelector('script')).toBeNull()
    expect(container.innerHTML).not.toContain('onerror')
    expect(container.querySelector('img')).toBeNull()
    expect(container.innerHTML).not.toContain('javascript:')
    expect(container.innerHTML).not.toContain('evil.test')
    const ok = [...container.querySelectorAll('a')].find((a) => a.textContent === 'ok')
    expect(ok).toHaveAttribute('rel', 'noopener noreferrer')
    expect(ok).toHaveAttribute('target', '_blank')
  })

  it('does not turn handles inside code into chips', async () => {
    renderMd('Use `[P1]` literally.')
    await screen.findByText('[P1]')
    expect(screen.queryByRole('button')).toBeNull()
  })
})

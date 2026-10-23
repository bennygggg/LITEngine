import { ArrowRight, FileText, Scale, Upload } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'

interface Props {
  composer: ReactNode
  onReviewSample: () => void
  onUpload: () => void
  onFindPrecedents: () => void
}

export function EmptyState({ composer, onReviewSample, onUpload, onFindPrecedents }: Props) {
  const starters = [
    { icon: FileText, title: 'Review a sample appeal', body: 'Read it, search precedents, map the argument, estimate the outcome', onClick: onReviewSample },
    { icon: Upload, title: 'Upload a judgment', body: 'PDF, Word or text — or choose from your matters', onClick: onUpload },
    { icon: Scale, title: 'Find precedents', body: 'Search the library on a point of law', onClick: onFindPrecedents },
  ]
  return (
    <div className="mx-auto flex min-h-0 w-full max-w-column flex-1 flex-col justify-center px-4 pb-16 pt-8">
      <h1 className="mb-8 text-center font-display text-4xl font-medium leading-tight tracking-tight text-ink sm:text-[2.75rem]">What are you working on?</h1>
      {composer}
      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        {starters.map((s) => (
          <button key={s.title} type="button" onClick={s.onClick}
            className="group flex flex-col items-start gap-2 rounded-xl border border-border bg-surface/60 p-4 text-left transition-colors hover:border-border-strong hover:bg-surface">
            <s.icon className="size-4.5 text-ink-muted" />
            <span className="text-sm font-medium">{s.title}</span>
            <span className="text-xs leading-relaxed text-ink-muted">{s.body}</span>
          </button>
        ))}
      </div>
      <p className="mt-8 text-center text-sm text-ink-muted">
        Not ready to try your own matter?{' '}
        <Link to="/demo" className="inline-flex items-center gap-1 font-medium text-ink underline decoration-border-strong underline-offset-4 hover:decoration-ink">
          Watch a recorded sample session <ArrowRight className="size-3.5" />
        </Link>
      </p>
    </div>
  )
}

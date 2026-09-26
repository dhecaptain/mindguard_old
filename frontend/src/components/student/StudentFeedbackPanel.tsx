import { useCallback, useEffect, useState } from 'react'
import api from '../../api/client'

type FeedbackItem = {
  id: string
  body: string
  student_title: string | null
  shared_at: string | null
  created_at: string
  author_name: string
}

function formatDate(value: string | null) {
  if (!value) return 'Recently'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Recently' : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function StudentFeedbackPanel() {
  const [items, setItems] = useState<FeedbackItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const { data } = await api.get<{ feedback?: FeedbackItem[] }>('/institution/student-feedback')
      setItems(Array.isArray(data.feedback) ? data.feedback : [])
    } catch {
      setError('Shared updates could not be loaded. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  return <section className="rounded-2xl border border-teal-100 bg-white p-5 shadow-sm" aria-live="polite">
    <div className="flex items-center justify-between gap-3">
      <div><p className="text-xs font-bold uppercase tracking-wide text-teal-700">Your support</p><h2 className="mt-1 font-bold text-slate-800">Updates from your counsellor</h2><p className="mt-1 text-sm text-slate-500">Only messages your counsellor intentionally shares with you appear here.</p></div>
      <button type="button" onClick={() => void load()} disabled={loading} className="shrink-0 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50">{loading ? 'Refreshing…' : 'Refresh'}</button>
    </div>
    {loading ? <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-500">Loading your shared updates…</p>
      : error ? <div className="mt-4 rounded-xl border border-red-100 bg-red-50 p-4 text-sm text-red-700" role="alert">{error} <button type="button" onClick={() => void load()} className="ml-1 font-semibold underline">Retry</button></div>
      : items.length === 0 ? <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-500">There are no shared updates yet. When your counsellor shares a message, it will appear here.</p>
      : <div className="mt-4 space-y-3">{items.map((item) => <article key={item.id} className="rounded-xl border border-teal-100 bg-teal-50/50 p-4">
        <div className="flex items-start justify-between gap-3"><h3 className="font-semibold text-slate-800">{item.student_title || 'A wellbeing update'}</h3><time className="shrink-0 text-xs text-slate-500">{formatDate(item.shared_at || item.created_at)}</time></div>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{item.body}</p>
        <p className="mt-3 text-xs font-medium text-teal-700">From {item.author_name || 'Your counsellor'}</p>
      </article>)}</div>}
  </section>
}

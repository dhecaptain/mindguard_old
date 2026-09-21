'use client'

import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'

type Details = { full_name: string; organisation: string; meeting_at: string; meeting_url: string; meeting_response?: string }

function DemoMeetingResponseContent() {
  const params = useSearchParams()
  const token = params.get('token') || ''
  const requestedAction = params.get('action') || ''
  const [details, setDetails] = useState<Details | null>(null)
  const [note, setNote] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!token) return
    fetch(`/api/v1/demo-requests/respond?token=${encodeURIComponent(token)}`)
      .then((res) => res.ok ? res.json() : Promise.reject(new Error('This invitation is no longer valid.')))
      .then(setDetails)
      .catch((error) => setMessage(error.message))
      .finally(() => setLoading(false))
  }, [token])

  const respond = async (action: 'accept' | 'reschedule') => {
    const res = await fetch(`/api/v1/demo-requests/respond?token=${encodeURIComponent(token)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, note }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) { setMessage(data.detail || 'Unable to update the invitation.'); return }
    setMessage(action === 'accept' ? 'Thanks — your meeting is confirmed.' : 'Thanks — our team will contact you to agree another time.')
    setDetails((current) => current ? { ...current, meeting_response: data.meeting_response } : current)
  }

  if (loading) return <main className="min-h-screen flex items-center justify-center text-ink-soft">Loading invitation…</main>
  if (!details) return <main className="min-h-screen flex items-center justify-center p-6 text-red-700">{message || 'Invitation not found.'}</main>
  return (
    <main className="min-h-screen bg-[#f7faf8] flex items-center justify-center p-6">
      <section className="mg-card max-w-xl w-full p-8">
        <p className="text-xs font-bold uppercase tracking-widest text-forest">MindGuard onboarding</p>
        <h1 className="text-2xl font-bold text-ink mt-2">Meeting invitation</h1>
        <p className="text-sm text-ink-soft mt-3">Hello {details.full_name}, your meeting for {details.organisation} is scheduled for:</p>
        <div className="rounded-lg bg-forest-50 border border-forest/20 p-4 mt-5 text-sm text-ink">
          <div className="font-semibold">{new Date(details.meeting_at).toLocaleString()}</div>
          <a className="text-forest underline break-all" href={details.meeting_url} target="_blank" rel="noreferrer">{details.meeting_url}</a>
        </div>
        {details.meeting_response === 'ACCEPTED' || details.meeting_response === 'RESCHEDULE_REQUESTED' ? (
          <p className="mt-5 text-sm text-forest font-semibold">{message || `Response recorded: ${details.meeting_response.toLowerCase().replace('_', ' ')}.`}</p>
        ) : (
          <>
            <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional note for a reschedule request" className="w-full mt-5 rounded-lg border border-black/10 p-3 text-sm" rows={3} />
            <div className="flex flex-wrap gap-3 mt-4">
              <button onClick={() => respond('accept')} className="mg-btn-primary px-5 py-2.5 text-sm">Accept meeting</button>
              <button onClick={() => respond('reschedule')} className="px-5 py-2.5 text-sm rounded-lg border border-black/10 text-ink">Request another time</button>
            </div>
          </>
        )}
        {requestedAction === 'accept' && !message && <p className="mt-3 text-xs text-ink-soft">Choose “Accept meeting” below to confirm.</p>}
        {message && details.meeting_response !== 'ACCEPTED' && details.meeting_response !== 'RESCHEDULE_REQUESTED' && <p className="mt-4 text-sm text-red-700">{message}</p>}
      </section>
    </main>
  )
}

export default function DemoMeetingResponsePage() {
  return (
    <Suspense fallback={<main className="min-h-screen flex items-center justify-center text-ink-soft">Loading invitation…</main>}>
      <DemoMeetingResponseContent />
    </Suspense>
  )
}

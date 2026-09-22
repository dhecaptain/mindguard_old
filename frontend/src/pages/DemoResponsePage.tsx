import { useEffect, useState } from 'react'
import {
  getDemoResponseDetails,
  respondToDemoMeeting,
  type DemoResponseDetails,
} from '../api/demo'

function formatMeetingDate(value: string | null) {
  if (!value) return 'Date to be confirmed'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'full',
    timeStyle: 'short',
  }).format(date)
}

function statusText(response: string | null) {
  if (response === 'ACCEPTED') return 'You have accepted this meeting time.'
  if (response === 'RESCHEDULE_REQUESTED') return 'You have asked the MindGuard team to arrange a different time.'
  return 'Please confirm whether this time works for you.'
}

export default function DemoResponsePage() {
  const params = new URLSearchParams(window.location.search)
  const token = params.get('token') || ''
  const requestedAction = params.get('action') === 'reschedule' ? 'reschedule' : 'accept'
  const [details, setDetails] = useState<DemoResponseDetails | null>(null)
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [complete, setComplete] = useState(false)
  const [action, setAction] = useState<'accept' | 'reschedule' | null>(token ? requestedAction : null)

  useEffect(() => {
    if (!token) {
      setError('This meeting invitation is missing its security token.')
      setLoading(false)
      return
    }
    getDemoResponseDetails(token)
      .then(setDetails)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [token])

  const submit = async (nextAction: 'accept' | 'reschedule') => {
    if (!token || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      await respondToDemoMeeting(token, nextAction, note)
      setDetails((current) => current ? {
        ...current,
        meeting_response: nextAction === 'accept' ? 'ACCEPTED' : 'RESCHEDULE_REQUESTED',
      } : current)
      setComplete(true)
      setAction(null)
    } catch (err: any) {
      setError(err.message || 'We could not record your response. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const alreadyResponded = details?.meeting_response === 'ACCEPTED' || details?.meeting_response === 'RESCHEDULE_REQUESTED'

  return (
    <div className="min-h-screen bg-[#f7f9fb] flex flex-col">
      <header className="w-full bg-white border-b border-[#eef2f6]">
        <div className="max-w-[560px] mx-auto px-[20px] py-[18px] flex items-center justify-between">
          <div className="flex items-center gap-[8px]">
            <span className="w-[30px] h-[30px] rounded-lg bg-[#0F766E] flex items-center justify-center text-white font-bold text-[0.85rem]">M</span>
            <span className="text-[1.05rem] font-bold text-[#1f2937]">MindGuard</span>
          </div>
          <a href="/" className="text-[0.8rem] text-[#0F766E] font-semibold hover:text-[#115E59]">MindGuard home</a>
        </div>
      </header>

      <main className="flex-1 w-full max-w-[560px] mx-auto px-[20px] py-[40px]">
        <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[26px] shadow-sm">
          {loading ? (
            <div className="py-[30px] text-center text-[0.85rem] text-[#6b7280]">Loading your meeting invitation…</div>
          ) : error ? (
            <div className="text-center">
              <div className="w-[52px] h-[52px] rounded-full bg-[#fee2e2] flex items-center justify-center mx-auto mb-[14px]"><i className="ti ti-link-off text-[26px] text-[#b91c1c]" /></div>
              <h1 className="text-[1.15rem] font-bold text-[#1f2937] mb-[8px]">Invitation unavailable</h1>
              <p className="text-[0.85rem] text-[#6b7280]">{error}</p>
              <p className="text-[0.78rem] text-[#9ca3af] mt-[12px]">Please contact the MindGuard team if you need a new invitation.</p>
            </div>
          ) : details ? (
            <>
              <div className="text-center mb-[24px]">
                <div className="w-[52px] h-[52px] rounded-full bg-[#d1fae5] flex items-center justify-center mx-auto mb-[14px]"><i className="ti ti-calendar-event text-[26px] text-[#047857]" /></div>
                <h1 className="text-[1.25rem] font-bold text-[#1f2937]">MindGuard onboarding meeting</h1>
                <p className="text-[0.85rem] text-[#6b7280] mt-[6px]">Hello {details.full_name || 'there'}, please review your meeting details.</p>
              </div>

              <div className="rounded-lg bg-[#f8fafc] border border-[#e5e7eb] p-[16px] text-[0.85rem] text-[#374151] space-y-[8px]">
                <div><span className="font-semibold">Organisation:</span> {details.organisation || '—'}</div>
                <div><span className="font-semibold">When:</span> {formatMeetingDate(details.meeting_at)}</div>
                {details.meeting_url && <div><span className="font-semibold">Join:</span> <a className="text-[#0F766E] break-all" href={details.meeting_url} target="_blank" rel="noreferrer">{details.meeting_url}</a></div>}
              </div>

              {complete || alreadyResponded ? (
                <div className="mt-[20px] rounded-lg bg-[#ecfdf5] border border-[#a7f3d0] px-[14px] py-[12px] text-[0.85rem] text-[#065f46]">{statusText(details.meeting_response)}</div>
              ) : (
                <>
                  {action === 'reschedule' && (
                    <div className="mt-[20px]">
                      <label className="block text-[0.75rem] font-bold text-[#374151] uppercase tracking-[0.06em] mb-[6px]">Optional note</label>
                      <textarea className="w-full bg-[#fafbfc] border border-[#e5e7eb] rounded-[8px] px-[12px] py-[9px] text-[0.85rem] text-[#1f2937] outline-none focus:border-[#0F766E] focus:ring-2 focus:ring-[#0F766E]/20 resize-none" rows={4} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Tell us which times work better…" />
                    </div>
                  )}
                  <div className="mt-[22px] flex flex-col sm:flex-row gap-[10px]">
                    {action === 'accept' ? (
                      <>
                        <button disabled={submitting} onClick={() => submit('accept')} className="flex-1 px-[16px] py-[10px] rounded-[8px] text-[0.85rem] font-semibold text-white bg-[#0F766E] hover:bg-[#115E59] disabled:opacity-60">{submitting ? 'Saving…' : 'Accept this time'}</button>
                        <button disabled={submitting} onClick={() => setAction('reschedule')} className="flex-1 px-[16px] py-[10px] rounded-[8px] text-[0.85rem] font-semibold text-[#0F766E] border border-[#99f6e4] hover:bg-[#f0fdfa] disabled:opacity-60">Request a different time</button>
                      </>
                    ) : (
                      <>
                        <button disabled={submitting} onClick={() => submit('reschedule')} className="flex-1 px-[16px] py-[10px] rounded-[8px] text-[0.85rem] font-semibold text-white bg-[#0F766E] hover:bg-[#115E59] disabled:opacity-60">{submitting ? 'Sending…' : 'Request a different time'}</button>
                        <button disabled={submitting} onClick={() => setAction('accept')} className="flex-1 px-[16px] py-[10px] rounded-[8px] text-[0.85rem] font-semibold text-[#0F766E] border border-[#99f6e4] hover:bg-[#f0fdfa] disabled:opacity-60">Keep this time</button>
                      </>
                    )}
                  </div>
                </>
              )}
            </>
          ) : null}
        </div>
      </main>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { useCounsellorStore } from '../store/counsellorStore'
import { getReferrals, createReferral, updateReferral, getStudents } from '../api/counsellor'
import type { StudentDTO } from '../api/counsellor'

const URGENCY_STYLES: Record<string, string> = {
  low: 'text-[#6b7280] bg-[#f3f4f6]',
  medium: 'text-[#92400e] bg-[#fef3c7]',
  high: 'text-[#991b1b] bg-[#fee2e2]',
  crisis: 'text-[#fff] bg-[#dc2626]',
}

const STATUS_STYLES: Record<string, string> = {
  open: 'bg-[#dbeafe] text-[#1e40af]',
  accepted: 'bg-[#d1fae5] text-[#065f46]',
  in_progress: 'bg-[#ccfbf1] text-[#115e59]',
  completed: 'bg-[#e0e7ff] text-[#4338ca]',
  declined: 'bg-[#f1f5f9] text-[#6b7280]',
  cancelled: 'bg-[#f1f5f9] text-[#475569]',
}

function formatDate(d: string) {
  if (!d) return '—'
  const dt = new Date(d)
  const now = new Date()
  const diff = now.getTime() - dt.getTime()
  const days = Math.floor(diff / 86400000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days}d ago`
  return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export default function ReferralsPage() {
  const { referrals, setReferrals, addReferral, updateReferralStatus, loading, setLoading, error, setError } = useCounsellorStore()
  const [showModal, setShowModal] = useState(false)
  const [students, setStudents] = useState<StudentDTO[]>([])
  const [formData, setFormData] = useState({ student_id: '', urgency: 'medium', notes: '', destination: '', follow_up_at: '' })
  const [submitting, setSubmitting] = useState(false)
  const [filter, setFilter] = useState<string>('all')
  const [formError, setFormError] = useState<string | null>(null)

  useEffect(() => {
    loadReferrals()
    getStudents().then(setStudents).catch(() => {})
  }, [])

  const loadReferrals = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getReferrals()
      setReferrals(data)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to load referrals')
    }
    setLoading(false)
  }

  const handleCreate = async () => {
    if (!formData.student_id) return
    setSubmitting(true)
    setFormError(null)
    try {
      const ref = await createReferral(formData.student_id, formData.urgency, formData.notes, formData.destination, formData.follow_up_at ? new Date(formData.follow_up_at).toISOString() : undefined)
      addReferral(ref)
      setShowModal(false)
      setFormData({ student_id: '', urgency: 'medium', notes: '', destination: '', follow_up_at: '' })
    } catch (e: any) {
      setFormError(e?.response?.data?.detail ?? 'Failed to create referral')
    }
    setSubmitting(false)
  }

  const handleStatusChange = async (id: string, status: string) => {
    try {
      await updateReferral(id, { status })
      updateReferralStatus(id, status)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to update referral')
    }
  }

  const filtered = filter === 'all' ? referrals : referrals.filter((r) => r.status === filter)

  return (
    <div className="flex flex-col gap-[16px]">
      {error && (
        <div className="flex items-center gap-[8px] px-[14px] py-[10px] bg-[#fee2e2] border border-[#fca5a5] rounded-[8px] text-[0.8rem] text-[#991b1b]">
          <i className="ti ti-alert-circle text-[16px]" />
          {error}
          <button onClick={() => setError(null)} className="ml-auto cursor-pointer bg-transparent border-none text-[#991b1b] hover:text-[#7f1d1d]"><i className="ti ti-x text-[14px]" /></button>
        </div>
      )}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[1.3rem] font-bold text-[#1f2937]">Referrals</h2>
          <p className="text-[0.82rem] text-[#6b7280] mt-[2px]">
            Create and manage student referrals
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-[6px] px-[14px] py-[8px] bg-[#0F766E] text-white rounded-[8px] text-[0.82rem] font-semibold cursor-pointer hover:bg-[#115E59] transition-colors"
        >
          <i className="ti ti-plus text-[16px]" />
          New Referral
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-[8px]">
        {['all', 'open', 'accepted', 'in_progress', 'completed', 'declined', 'cancelled'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-[12px] py-[5px] rounded-full text-[0.72rem] font-semibold cursor-pointer transition-colors capitalize ${
              filter === f
                ? 'bg-[#0F766E] text-white'
                : 'bg-[#f3f4f6] text-[#6b7280] hover:bg-[#e5e7eb]'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* List */}
      {loading && referrals.length === 0 ? (
        <div className="flex items-center justify-center py-[60px] text-[#6b7280]">
          <div className="w-[24px] h-[24px] border-2 border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin mr-[10px]" />
          Loading referrals...
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-[60px] text-[#9ca3af] bg-white rounded-xl border border-[rgba(229,231,235,0.7)]">
          <i className="ti ti-file-description text-[32px] mb-[8px]" />
          <span className="text-[0.82rem]">No referrals found</span>
        </div>
      ) : (
        <div className="grid gap-[10px]">
          {filtered.map((r) => (
            <div key={r.id} className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[16px] flex items-start gap-[14px]">
              <div className={`w-[10px] h-[10px] rounded-full mt-[5px] flex-shrink-0 ${
                r.urgency === 'crisis' ? 'bg-[#dc2626] animate-pulse' :
                r.urgency === 'high' ? 'bg-[#ef4444]' :
                r.urgency === 'medium' ? 'bg-[#f59e0b]' : 'bg-[#9ca3af]'
              }`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-[8px] flex-wrap">
                  <span className="font-semibold text-[0.85rem] text-[#1f2937]">{r.student_name || r.student_id}</span>
                  <span className={`px-[8px] py-[2px] rounded-full text-[0.65rem] font-bold uppercase ${URGENCY_STYLES[r.urgency] || ''}`}>
                    {r.urgency}
                  </span>
                  <span className={`px-[8px] py-[2px] rounded-full text-[0.65rem] font-bold uppercase ${STATUS_STYLES[r.status] || ''}`}>
                    {r.status}
                  </span>
                  <span className="text-[0.7rem] text-[#9ca3af] ml-auto">{formatDate(r.created_at)}</span>
                </div>
                {r.notes && <p className="text-[0.78rem] text-[#6b7280] mt-[6px]">{r.notes}</p>}
                {(r.destination || r.follow_up_at || r.outcome) && <div className="flex flex-wrap gap-3 mt-[6px] text-[0.72rem] text-[#64748b]"><span>{r.destination || 'No destination'}</span>{r.follow_up_at && <span>Follow up: {new Date(r.follow_up_at).toLocaleString()}</span>}{r.outcome && <span>Outcome: {r.outcome}</span>}</div>}
                <div className="flex gap-[8px] mt-[8px]">
                  {r.status === 'open' && (
                    <>
                      <button onClick={() => handleStatusChange(r.id, 'accepted')} className="text-[0.72rem] text-[#0F766E] font-semibold cursor-pointer bg-transparent border-none hover:underline">Accept</button>
                      <button onClick={() => handleStatusChange(r.id, 'declined')} className="text-[0.72rem] text-[#ef4444] font-semibold cursor-pointer bg-transparent border-none hover:underline">Decline</button>
                    </>
                  )}
                  {(r.status === 'accepted' || r.status === 'in_progress') && (
                    <button onClick={() => handleStatusChange(r.id, 'completed')} className="text-[0.72rem] text-[#0F766E] font-semibold cursor-pointer bg-transparent border-none hover:underline">Mark Complete</button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setShowModal(false)}>
          <div className="bg-white rounded-xl p-[24px] w-[440px] max-w-[90vw]" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-[1.05rem] font-bold text-[#1f2937] mb-[16px]">New Referral</h3>
            <div className="flex flex-col gap-[12px]">
              <div>
                <label className="text-[0.78rem] font-semibold text-[#374151] mb-[4px] block">Receiving service / destination</label>
                <input value={formData.destination} onChange={(e) => setFormData({ ...formData, destination: e.target.value })} placeholder="School nurse, clinic, safeguarding team..." className="w-full px-[12px] py-[9px] rounded-[8px] border border-[#d1d5db] text-[0.82rem]" />
              </div>
              <div>
                <label className="text-[0.78rem] font-semibold text-[#374151] mb-[4px] block">Follow-up date</label>
                <input type="datetime-local" value={formData.follow_up_at} onChange={(e) => setFormData({ ...formData, follow_up_at: e.target.value })} className="w-full px-[12px] py-[9px] rounded-[8px] border border-[#d1d5db] text-[0.82rem]" />
              </div>
              <div>
                <label className="text-[0.78rem] font-semibold text-[#374151] mb-[4px] block">Student</label>
                <select
                  value={formData.student_id}
                  onChange={(e) => setFormData({ ...formData, student_id: e.target.value })}
                  className="w-full px-[12px] py-[9px] rounded-[8px] border border-[#d1d5db] text-[0.82rem] bg-white"
                >
                  <option value="">Select a student...</option>
                  {students.map((s) => (
                    <option key={s.id} value={s.id}>{s.name} ({s.email})</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[0.78rem] font-semibold text-[#374151] mb-[4px] block">Urgency</label>
                <div className="flex gap-[6px]">
                  {['low', 'medium', 'high', 'crisis'].map((u) => (
                    <button
                      key={u}
                      onClick={() => setFormData({ ...formData, urgency: u })}
                      className={`px-[12px] py-[6px] rounded-[6px] text-[0.76rem] font-semibold capitalize cursor-pointer border ${
                        formData.urgency === u
                          ? 'bg-[#0F766E] text-white border-[#0F766E]'
                          : 'bg-white text-[#6b7280] border-[#d1d5db] hover:border-[#9ca3af]'
                      }`}
                    >
                      {u}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="text-[0.78rem] font-semibold text-[#374151] mb-[4px] block">Notes</label>
                <textarea
                  value={formData.notes}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  placeholder="Add notes about this referral..."
                  rows={3}
                  className="w-full px-[12px] py-[9px] rounded-[8px] border border-[#d1d5db] text-[0.82rem] resize-none"
                />
              </div>
            </div>
            {formError && (
              <div className="flex items-center gap-[8px] px-[12px] py-[8px] bg-[#fee2e2] border border-[#fca5a5] rounded-[8px] text-[0.78rem] text-[#991b1b] mt-[12px]">
                <i className="ti ti-alert-circle text-[14px]" />
                {formError}
              </div>
            )}
            <div className="flex justify-end gap-[10px] mt-[20px]">
              <button onClick={() => { setShowModal(false); setFormError(null) }} className="px-[14px] py-[8px] rounded-[8px] text-[0.82rem] font-semibold text-[#6b7280] cursor-pointer bg-transparent border border-[#d1d5db] hover:bg-[#f9fafb]">Cancel</button>
              <button
                onClick={handleCreate}
                disabled={!formData.student_id || submitting}
                className="px-[14px] py-[8px] rounded-[8px] text-[0.82rem] font-semibold text-white cursor-pointer bg-[#0F766E] hover:bg-[#115E59] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submitting ? 'Creating...' : 'Create Referral'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

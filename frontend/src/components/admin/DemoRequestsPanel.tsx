import { useCallback, useEffect, useState } from 'react'
import { DEMO_STATUSES, convertDemoRequest, getDemoRequests, scheduleDemoRequest, updateDemoRequest } from '../../api/admin'
import api from '../../api/client'
import type { DemoRequest } from '../../types'

interface AssignableUser {
  id: string
  name: string
  email: string
  role_type: string
}

const STATUS_STYLE: Record<string, string> = {
  new: 'bg-[#dbeafe] text-[#1e40af]',
  contacted: 'bg-[#fef3c7] text-[#92400e]',
  qualified: 'bg-[#ede9fe] text-[#5b21b6]',
  demo_scheduled: 'bg-[#ccfbf1] text-[#115e59]',
  institution_provisioning: 'bg-[#fef3c7] text-[#92400e]',
  onboarding: 'bg-[#ffedd5] text-[#9a3412]',
  closed_won: 'bg-[#d1fae5] text-[#065f46]',
  closed_lost: 'bg-[#fee2e2] text-[#991b1b]',
}

export default function DemoRequestsPanel() {
  const [requests, setRequests] = useState<DemoRequest[]>([])
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [assignees, setAssignees] = useState<AssignableUser[]>([])
  const [converting, setConverting] = useState<string | null>(null)
  const [scheduling, setScheduling] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRequests(await getDemoRequests(filter || undefined))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    api.get('/admin/users')
      .then(({ data }) => {
        const list: AssignableUser[] = Array.isArray(data) ? data : []
        setAssignees(list.filter((u) => u.role_type === 'admin' || u.role_type === 'counsellor'))
      })
      .catch(() => {})
  }, [])

  const handleStatus = async (id: string, status: string) => {
    try {
      const updated = await updateDemoRequest(id, { status: status as DemoRequest['status'] })
      setRequests((rs) => rs.map((r) => (r.id === id ? { ...r, ...updated } : r)))
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleNotes = async (id: string, notes: string) => {
    try {
      const updated = await updateDemoRequest(id, { notes })
      setRequests((rs) => rs.map((r) => (r.id === id ? { ...r, ...updated } : r)))
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleAssignment = async (id: string, userId: string) => {
    try {
      const updated = await updateDemoRequest(id, { assigned_to: userId || null })
      setRequests((rs) => rs.map((r) => (r.id === id ? { ...r, ...updated } : r)))
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleConvert = async (id: string) => {
    setConverting(id)
    try {
      const result = await convertDemoRequest(id)
      setRequests((rs) => rs.map((r) => r.id === id ? result.demo_request : r))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setConverting(null)
    }
  }

  const handleSchedule = async (request: DemoRequest, event: React.MouseEvent<HTMLButtonElement>) => {
    const row = event.currentTarget.closest('tr')
    const dateInput = row?.querySelector('input[type="datetime-local"]') as HTMLInputElement | null
    const urlInput = row?.querySelector('input[placeholder="Meeting link"]') as HTMLInputElement | null
    if (!dateInput?.value || !urlInput?.value.trim()) {
      setError('Choose a meeting time and add the meeting link before sending the invitation.')
      return
    }
    setScheduling(request.id)
    try {
      const result = await scheduleDemoRequest(request.id, new Date(dateInput.value).toISOString(), urlInput.value.trim())
      setRequests((rs) => rs.map((r) => r.id === request.id ? result.demo_request : r))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setScheduling(null)
    }
  }

  const open = requests.filter((r) => r.status !== 'closed_won' && r.status !== 'closed_lost').length

  return (
    <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-[10px] px-[20px] py-[14px] border-b border-[#f1f5f9]">
        <div className="flex items-center gap-[8px]">
          <i className="ti ti-rocket text-[16px] text-[#6b7280]" />
          <span className="text-[0.9rem] font-bold text-[#1f2937]">Demo requests</span>
          {!loading && (
            <span className="text-[0.78rem] text-[#9ca3af] ml-[4px]">
              ({requests.length}) · {open} open
            </span>
          )}
        </div>
        <div className="flex items-center gap-[8px]">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-[7px] border border-[#e5e7eb] px-[10px] py-[6px] text-[0.78rem] text-[#374151] bg-white focus:outline-none focus:ring-2 focus:ring-[#0F766E]"
          >
            <option value="">All statuses</option>
            {DEMO_STATUSES.map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <button
            onClick={load}
            className="flex items-center gap-[6px] px-[12px] py-[6px] bg-[#0F766E] text-white rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#115E59] transition-colors"
          >
            <i className="ti ti-refresh text-[14px]" />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-[20px] my-[12px] rounded-[8px] bg-[#fee2e2] border border-[#fca5a5] px-[12px] py-[8px] text-[0.78rem] text-[#991b1b]">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-[40px] text-[#6b7280]">
          <div className="w-[24px] h-[24px] border-2 border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin mr-[10px]" />
          <span className="text-[0.82rem]">Loading demo requests...</span>
        </div>
      ) : requests.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-[40px] text-[#9ca3af]">
          <i className="ti ti-inbox text-[28px] mb-[6px]" />
          <span className="text-[0.82rem]">No demo requests yet.</span>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[0.82rem]">
            <thead className="bg-[#f9fafb]">
              <tr className="text-[#6b7280] font-semibold text-[0.72rem] uppercase tracking-wider">
                <th className="text-left py-[10px] px-[20px]">Requester</th>
                <th className="text-left py-[10px] px-[20px]">Organisation</th>
                <th className="text-left py-[10px] px-[20px]">Type</th>
                <th className="text-left py-[10px] px-[20px]">Status</th>
                <th className="text-left py-[10px] px-[20px]">Assigned to</th>
                <th className="text-left py-[10px] px-[20px]">Meeting</th>
                <th className="text-left py-[10px] px-[20px]">Onboarding</th>
                <th className="text-left py-[10px] px-[20px]">Notes</th>
                <th className="text-left py-[10px] px-[20px]">Submitted</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#f1f5f9]">
              {requests.map((r) => (
                <tr key={r.id} className="hover:bg-[#f8fafc] transition-colors align-top">
                  <td className="py-[12px] px-[20px]">
                    <div className="text-[#1f2937] font-medium">{r.full_name}</div>
                    <div className="text-[0.7rem] text-[#9ca3af]">{r.work_email}</div>
                    {r.role_title && (
                      <div className="text-[0.7rem] text-[#6b7280]">{r.role_title}</div>
                    )}
                  </td>
                  <td className="py-[12px] px-[20px]">
                    <input
                      type="datetime-local"
                      defaultValue={r.meeting_at ? r.meeting_at.slice(0, 16) : ''}
                      onBlur={(e) => {
                        const value = e.target.value ? new Date(e.target.value).toISOString() : null
                        if (value !== (r.meeting_at || null)) updateDemoRequest(r.id, { meeting_at: value }).then((updated) => setRequests((rs) => rs.map((x) => x.id === r.id ? { ...x, ...updated } : x))).catch((e) => setError(e.message))
                      }}
                      className="w-[170px] rounded-[7px] border border-[#e5e7eb] px-[8px] py-[4px] text-[0.72rem] text-[#374151]"
                    />
                    <input
                      defaultValue={r.meeting_url || ''}
                      onBlur={(e) => {
                        if (e.target.value !== (r.meeting_url || '')) updateDemoRequest(r.id, { meeting_url: e.target.value || null }).then((updated) => setRequests((rs) => rs.map((x) => x.id === r.id ? { ...x, ...updated } : x))).catch((err) => setError(err.message))
                      }}
                      placeholder="Meeting link"
                      className="w-[170px] mt-[5px] rounded-[7px] border border-[#e5e7eb] px-[8px] py-[4px] text-[0.72rem] text-[#374151]"
                    />
                    <button
                      onClick={(event) => handleSchedule(r, event)}
                      disabled={scheduling === r.id}
                      className="w-[170px] mt-[5px] rounded-[7px] bg-[#0F766E] px-[8px] py-[5px] text-[0.7rem] font-semibold text-white disabled:opacity-50"
                    >
                      {scheduling === r.id ? 'Sending invite…' : 'Send calendar invite'}
                    </button>
                    {r.meeting_response === 'ACCEPTED' && <div className="text-[0.7rem] text-[#047857] mt-[5px]">Accepted</div>}
                    {r.meeting_response === 'RESCHEDULE_REQUESTED' && <div className="text-[0.7rem] text-[#b45309] mt-[5px]">Reschedule requested</div>}
                  </td>
                  <td className="py-[12px] px-[20px]">
                    {r.institution_id ? (
                      <div className="text-[0.72rem] text-[#047857] font-semibold">Institution provisioned</div>
                    ) : (
                      <button
                        onClick={() => handleConvert(r.id)}
                        disabled={converting === r.id || !['qualified', 'demo_scheduled'].includes(r.status)}
                        className="rounded-[7px] bg-[#0F766E] px-[9px] py-[5px] text-[0.7rem] font-semibold text-white disabled:opacity-40"
                      >
                        {converting === r.id ? 'Setting up…' : 'Set up institution'}
                      </button>
                    )}
                  </td>
                  <td className="py-[12px] px-[20px] text-[#374151]">
                    {r.organisation}
                    {r.student_count_range && (
                      <div className="text-[0.7rem] text-[#9ca3af]">{r.student_count_range}</div>
                    )}
                    {r.country && (
                      <div className="text-[0.7rem] text-[#9ca3af]">{r.country}</div>
                    )}
                  </td>
                  <td className="py-[12px] px-[20px]">
                    <span className="inline-block px-[8px] py-[2px] rounded-full text-[0.7rem] font-semibold bg-[#f1f5f9] text-[#6b7280]">
                      {r.organisation_type.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="py-[12px] px-[20px]">
                    <select
                      value={r.status}
                      onChange={(e) => handleStatus(r.id, e.target.value)}
                      className={`rounded-[7px] border border-[#e5e7eb] px-[8px] py-[4px] text-[0.72rem] font-semibold focus:outline-none focus:ring-2 focus:ring-[#0F766E] ${STATUS_STYLE[r.status] || 'bg-[#f1f5f9] text-[#6b7280]'}`}
                    >
                      {DEMO_STATUSES.map((s) => (
                        <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
                      ))}
                    </select>
                  </td>
                  <td className="py-[12px] px-[20px]">
                    <select
                      value={r.assigned_to || ''}
                      onChange={(e) => handleAssignment(r.id, e.target.value)}
                      className="rounded-[7px] border border-[#e5e7eb] px-[8px] py-[4px] text-[0.72rem] text-[#374151] bg-white focus:outline-none focus:ring-2 focus:ring-[#0F766E]"
                    >
                      <option value="">Unassigned</option>
                      {assignees.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.name} ({u.role_type})
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-[12px] px-[20px]">
                    <input
                      defaultValue={r.notes || ''}
                      onBlur={(e) => {
                        if ((e.target.value || '').trim() !== (r.notes || '').trim()) {
                          handleNotes(r.id, e.target.value.trim())
                        }
                      }}
                      placeholder="Add notes..."
                      className="w-[180px] rounded-[7px] border border-[#e5e7eb] px-[8px] py-[4px] text-[0.75rem] text-[#374151] bg-white focus:outline-none focus:ring-2 focus:ring-[#0F766E]"
                    />
                  </td>
                  <td className="py-[12px] px-[20px] text-[0.72rem] text-[#9ca3af] whitespace-nowrap">
                    {new Date(r.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

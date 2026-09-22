import { useState, useEffect } from 'react'
import { broadcastNotification } from '../api/auth'
import api from '../api/client'
import DemoRequestsPanel from '../components/admin/DemoRequestsPanel'
import AuditTrailPanel from '../components/admin/AuditTrailPanel'
import { permanentlyDeleteAdminUser } from '../api/admin'

interface SystemUser {
  id: string
  email: string
  name: string
  role_type: string
  status: string
}

export default function AdminPage() {
  const [title, setTitle] = useState('')
  const [message, setMessage] = useState('')
  const [targetRole, setTargetRole] = useState('')
  const [sending, setSending] = useState(false)
  const [success, setSuccess] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [users, setUsers] = useState<SystemUser[]>([])
  const [population, setPopulation] = useState({ institutionStudents: 0, individuals: 0 })
  const [loadingUsers, setLoadingUsers] = useState(true)
  const [usersError, setUsersError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<SystemUser | null>(null)
  const [deleteConfirmation, setDeleteConfirmation] = useState('')
  const [deleting, setDeleting] = useState(false)

  const loadUsers = () => {
    setLoadingUsers(true)
    setUsersError(null)
    Promise.all([api.get('/admin/users'), api.get('/counsellor/dashboard')])
      .then(([usersResponse, dashboardResponse]) => {
        setUsers(usersResponse.data)
        setPopulation({
          institutionStudents: dashboardResponse.data.total_students ?? 0,
          individuals: dashboardResponse.data.individual_users ?? 0,
        })
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : 'Unable to load users'
        setUsersError(msg)
      })
      .finally(() => setLoadingUsers(false))
  }

  useEffect(() => {
    // The loader synchronizes this page with the admin API on mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadUsers()
  }, [])

  const handleBroadcast = async () => {
    if (!title.trim() || !message.trim()) return
    setSending(true)
    setSuccess(null)
    setError(null)
    try {
      const { sent } = await broadcastNotification(title, message, targetRole || undefined)
      setSuccess(`Broadcast sent to ${sent} user${sent !== 1 ? 's' : ''}.`)
      setTitle('')
      setMessage('')
      setTargetRole('')
    } catch (e: unknown) {
      const error = e as { response?: { data?: { detail?: string } } }
      setError(error.response?.data?.detail ?? 'Failed to send broadcast')
    }
    setSending(false)
  }

  const handleDeleteUser = async () => {
    if (!deleteTarget || deleteConfirmation.trim().toLowerCase() !== deleteTarget.email.toLowerCase()) return
    setDeleting(true)
    setError(null)
    try {
      await permanentlyDeleteAdminUser(deleteTarget.id, deleteConfirmation.trim())
      setSuccess(`${deleteTarget.email} was permanently deleted.`)
      setDeleteTarget(null)
      setDeleteConfirmation('')
      loadUsers()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setError(detail ?? 'Unable to permanently delete this user')
    } finally {
      setDeleting(false)
    }
  }

  const counts = {
    total: users.length,
    students: population.institutionStudents,
    individuals: population.individuals,
    counsellors: users.filter((u) => u.role_type === 'counsellor').length,
  }

  return (
    <div className="flex flex-col gap-[20px]">
      <div>
        <h2 className="text-[1.3rem] font-bold text-[#1f2937]">Admin Panel</h2>
        <p className="text-[0.82rem] text-[#6b7280] mt-[2px]">System administration and broadcast messaging</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-[12px]">
        {[
          { label: 'Total Users', value: counts.total, icon: 'ti ti-users', color: '#0F766E' },
          { label: 'Students', value: counts.students, icon: 'ti ti-school', color: '#3b82f6' },
          { label: 'Individuals', value: counts.individuals, icon: 'ti ti-user', color: '#f59e0b' },
          { label: 'Counsellors', value: counts.counsellors, icon: 'ti ti-stethoscope', color: '#8b5cf6' },
        ].map((s) => (
          <div key={s.label} className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[16px] flex items-center gap-[12px]">
            <div className="w-[40px] h-[40px] rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: `${s.color}18` }}>
              <i className={`${s.icon} text-[20px]`} style={{ color: s.color }} />
            </div>
            <div>
              <div className="text-[1.4rem] font-bold text-[#1f2937]">{loadingUsers ? '—' : s.value}</div>
              <div className="text-[0.72rem] text-[#6b7280]">{s.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Broadcast */}
      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[20px]">
        <div className="flex items-center gap-[8px] mb-[16px]">
          <i className="ti ti-speakerphone text-[20px] text-[#0F766E]" />
          <h3 className="text-[1rem] font-bold text-[#1f2937]">Broadcast Message</h3>
        </div>
        <div className="flex flex-col gap-[12px]">
          <div>
            <label className="text-[0.72rem] font-bold text-[#374151] uppercase tracking-[0.06em] mb-[6px] block">Recipients</label>
            <select
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              className="w-full bg-[#fafbfc] border border-[#e5e7eb] rounded-[8px] px-[12px] py-[9px] text-[0.85rem] text-[#4b5563] outline-none focus:border-[#0F766E]"
            >
              <option value="">All users</option>
              <option value="student">Students only</option>
              <option value="counsellor">Counsellors only</option>
            </select>
          </div>
          <div>
            <label className="text-[0.72rem] font-bold text-[#374151] uppercase tracking-[0.06em] mb-[6px] block">Subject</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Notification subject..."
              className="w-full bg-[#fafbfc] border border-[#e5e7eb] rounded-[8px] px-[12px] py-[9px] text-[0.85rem] text-[#4b5563] outline-none focus:border-[#0F766E]"
            />
          </div>
          <div>
            <label className="text-[0.72rem] font-bold text-[#374151] uppercase tracking-[0.06em] mb-[6px] block">Message</label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Write your message..."
              rows={4}
              className="w-full bg-[#fafbfc] border border-[#e5e7eb] rounded-[8px] px-[12px] py-[9px] text-[0.85rem] text-[#4b5563] outline-none focus:border-[#0F766E] resize-none"
            />
          </div>
          {error && (
            <div className="flex items-center gap-[8px] px-[12px] py-[8px] bg-[#fee2e2] border border-[#fca5a5] rounded-[8px] text-[0.78rem] text-[#991b1b]">
              <i className="ti ti-alert-circle text-[14px]" />{error}
            </div>
          )}
          {success && (
            <div className="flex items-center gap-[8px] px-[12px] py-[8px] bg-[#d1fae5] border border-[#6ee7b7] rounded-[8px] text-[0.78rem] text-[#065f46]">
              <i className="ti ti-circle-check text-[14px]" />{success}
            </div>
          )}
          <button
            onClick={handleBroadcast}
            disabled={!title.trim() || !message.trim() || sending}
            className="self-end px-[18px] py-[9px] bg-[#0F766E] text-white rounded-[8px] text-[0.82rem] font-semibold cursor-pointer hover:bg-[#115E59] disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-[6px]"
          >
            <i className="ti ti-send text-[15px]" />
            {sending ? 'Sending...' : 'Send Broadcast'}
          </button>
        </div>
      </div>

      {/* User list */}
      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[20px]">
        <div className="flex items-center gap-[8px] mb-[14px]">
          <i className="ti ti-list text-[20px] text-[#0F766E]" />
          <h3 className="text-[1rem] font-bold text-[#1f2937]">All Users</h3>
        </div>
        {loadingUsers ? (
          <div className="flex items-center gap-[8px] text-[#6b7280] text-[0.82rem]">
            <div className="w-[18px] h-[18px] border-2 border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin" />
            Loading...
          </div>
        ) : usersError ? (
          <div className="flex flex-col gap-[10px]">
            <div className="flex items-center gap-[8px] px-[12px] py-[10px] bg-[#fee2e2] border border-[#fca5a5] rounded-[8px] text-[0.82rem] text-[#991b1b]">
              <i className="ti ti-alert-circle text-[16px]" />Unable to load dashboard data: {usersError}
            </div>
            <button onClick={loadUsers} className="self-start px-[14px] py-[7px] bg-[#0F766E] text-white rounded-[8px] text-[0.78rem] font-semibold hover:bg-[#115E59]">Retry</button>
          </div>
        ) : users.length === 0 ? (
          <div className="text-center py-[16px] text-[#6b7280] text-[0.82rem]">No users found. Invite a counsellor or wait for registrations.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[0.8rem]">
              <thead>
                <tr className="text-left text-[#9ca3af] border-b border-[#f3f4f6]">
                  <th className="pb-[8px] font-semibold">Name</th>
                  <th className="pb-[8px] font-semibold">Email</th>
                  <th className="pb-[8px] font-semibold">Role</th>
                  <th className="pb-[8px] font-semibold">Status</th>
                  <th className="pb-[8px] font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-[#f9fafb] hover:bg-[#fafbfc]">
                    <td className="py-[8px] font-medium text-[#1f2937]">{u.name}</td>
                    <td className="py-[8px] text-[#6b7280]">{u.email}</td>
                    <td className="py-[8px]">
                      <span className={`px-[8px] py-[2px] rounded-full text-[0.65rem] font-bold uppercase ${
                        u.role_type === 'admin' ? 'bg-[#fef3c7] text-[#92400e]' :
                        u.role_type === 'counsellor' ? 'bg-[#d1fae5] text-[#065f46]' :
                        'bg-[#dbeafe] text-[#1e40af]'
                      }`}>{u.role_type}</span>
                    </td>
                    <td className="py-[8px]">
                      <span className={`px-[8px] py-[2px] rounded-full text-[0.65rem] font-bold uppercase ${
                        u.status === 'approved' ? 'bg-[#d1fae5] text-[#065f46]' : 'bg-[#f3f4f6] text-[#6b7280]'
                      }`}>{u.status}</span>
                    </td>
                    <td className="py-[8px] text-right"><button type="button" onClick={() => { setDeleteTarget(u); setDeleteConfirmation(''); setError(null) }} className="rounded-md border border-red-200 px-2 py-1 text-[0.68rem] font-semibold text-red-700 hover:bg-red-50">Delete permanently</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Demo request pipeline */}
      <DemoRequestsPanel />

      {/* Compliance & audit trail */}
      <AuditTrailPanel />

      {deleteTarget && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4"><div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"><div className="flex items-start gap-3"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-700"><i className="ti ti-trash text-xl" /></div><div><h3 className="text-lg font-bold text-slate-900">Permanently delete user?</h3><p className="mt-1 text-sm leading-5 text-slate-600">This removes the account, roster link, consent records, analyses, messages, assignments, and other user-owned data. Audit history is retained. This cannot be undone.</p></div></div><p className="mt-4 text-sm text-slate-700">Type <strong>{deleteTarget.email}</strong> to confirm.</p><input autoFocus type="email" value={deleteConfirmation} onChange={(e) => setDeleteConfirmation(e.target.value)} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-red-500" placeholder={deleteTarget.email} /><div className="mt-5 flex justify-end gap-2"><button type="button" onClick={() => { setDeleteTarget(null); setDeleteConfirmation('') }} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700">Cancel</button><button type="button" onClick={handleDeleteUser} disabled={deleting || deleteConfirmation.trim().toLowerCase() !== deleteTarget.email.toLowerCase()} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">{deleting ? 'Deleting…' : 'Delete permanently'}</button></div></div></div>}
    </div>
  )
}

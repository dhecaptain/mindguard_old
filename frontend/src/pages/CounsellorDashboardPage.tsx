import { useEffect, useState } from 'react'
import { useCounsellorStore } from '../store/counsellorStore'
import { getDashboard, getStudentSocialAccounts, getStudents, type StudentDTO, type StudentSocialAccount } from '../api/counsellor'
import { useUiStore } from '../store'

type StudentWorkspaceItem = {
  student: StudentDTO
  accounts: StudentSocialAccount[]
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

export default function CounsellorDashboardPage() {
  const { dashboard, setDashboard, setLoading, loading, requestStudentWorkspace } = useCounsellorStore()
  const setPage = useUiStore((s) => s.setPage)
  const [error, setError] = useState<string | null>(null)
  const [workspace, setWorkspace] = useState<StudentWorkspaceItem[]>([])
  const [workspaceLoading, setWorkspaceLoading] = useState(true)

  const loadDashboard = async () => {
    setLoading(true)
    setError(null)
    setWorkspaceLoading(true)
    try {
      const [data, assignedStudents] = await Promise.all([getDashboard(), getStudents()])
      setDashboard(data)
      const workspaceItems = await Promise.all(assignedStudents.slice(0, 12).map(async (student) => {
        try {
          return { student, accounts: await getStudentSocialAccounts(student.id) }
        } catch {
          return { student, accounts: [] }
        }
      }))
      setWorkspace(workspaceItems)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to load the dashboard.')
    } finally {
      setWorkspaceLoading(false)
      setLoading(false)
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadDashboard()
  }, [])

  if (loading && !dashboard) {
    return (
      <div className="flex items-center justify-center py-[80px] text-[#6b7280]">
        <div className="w-[28px] h-[28px] border-2 border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin mr-[10px]" />
        Loading dashboard...
      </div>
    )
  }

  if (!dashboard) {
    return (
      <div role="alert" className="rounded-[10px] border border-[#fca5a5] bg-[#fef2f2] px-[16px] py-[14px] text-[0.84rem] text-[#991b1b]">
        <div className="font-semibold">Dashboard unavailable</div>
        <div className="mt-[4px]">{error || 'No dashboard data was returned.'}</div>
        <button
          type="button"
          onClick={loadDashboard}
          className="mt-[10px] rounded-[7px] bg-[#991b1b] px-[12px] py-[6px] text-[0.78rem] font-semibold text-white"
        >
          Try again
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-[16px]">
      <div>
        <h2 className="text-[1.3rem] font-bold text-[#1f2937]">Counsellor Dashboard</h2>
        <p className="text-[0.82rem] text-[#6b7280] mt-[2px]">
          Overview of your students and activities
        </p>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-[12px]">
        <div onClick={() => setPage('students')} className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[18px] cursor-pointer hover:shadow-sm transition-shadow">
          <div className="flex items-center gap-[10px]">
            <div className="w-[40px] h-[40px] rounded-[10px] bg-[#e0f2fe] flex items-center justify-center">
              <i className="ti ti-users text-[#0284c7] text-[20px]" />
            </div>
            <div>
              <div className="text-[1.3rem] font-bold text-[#1f2937]">{dashboard.total_students}</div>
              <div className="text-[0.72rem] text-[#6b7280]">Total Students</div>
            </div>
          </div>
        </div>
        <div onClick={() => setPage('students')} className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[18px] cursor-pointer hover:shadow-sm transition-shadow">
          <div className="flex items-center gap-[10px]">
            <div className="w-[40px] h-[40px] rounded-[10px] bg-[#fef3c7] flex items-center justify-center">
              <i className="ti ti-clock text-[#d97706] text-[20px]" />
            </div>
            <div>
              <div className="text-[1.3rem] font-bold text-[#1f2937]">{dashboard.pending_approvals}</div>
              <div className="text-[0.72rem] text-[#6b7280]">Pending Approvals</div>
            </div>
          </div>
        </div>
        <div onClick={() => setPage('referrals')} className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[18px] cursor-pointer hover:shadow-sm transition-shadow">
          <div className="flex items-center gap-[10px]">
            <div className="w-[40px] h-[40px] rounded-[10px] bg-[#d1fae5] flex items-center justify-center">
              <i className="ti ti-file-description text-[#059669] text-[20px]" />
            </div>
            <div>
              <div className="text-[1.3rem] font-bold text-[#1f2937]">{dashboard.open_referrals}</div>
              <div className="text-[0.72rem] text-[#6b7280]">Open Referrals</div>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[18px]">
          <div className="flex items-center gap-[10px]">
            <div className="w-[40px] h-[40px] rounded-[10px] bg-[#fee2e2] flex items-center justify-center">
              <i className="ti ti-alert-triangle text-[#dc2626] text-[20px]" />
            </div>
            <div>
              <div className="text-[1.3rem] font-bold text-[#dc2626]">{dashboard.crisis_flags_7d}</div>
              <div className="text-[0.72rem] text-[#6b7280]">Crisis Alerts (7d)</div>
            </div>
          </div>
        </div>
      </div>

      {/* Assigned-student workspace */}
      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-[10px] px-[20px] py-[14px] border-b border-[#f1f5f9]">
          <div>
            <h3 className="text-[0.9rem] font-bold text-[#1f2937]">Assigned student workspace</h3>
            <p className="mt-[3px] text-[0.72rem] text-[#6b7280]">Monitor connected accounts and open a student case to review consent, run analysis, write notes, and share safe feedback.</p>
          </div>
          <button onClick={() => setPage('students')} className="text-[0.78rem] text-[#0F766E] font-semibold cursor-pointer bg-transparent border-none hover:underline">Open all students</button>
        </div>
        {workspaceLoading ? (
          <div className="px-[20px] py-[28px] text-[0.8rem] text-[#94a3b8]">Loading assigned student accounts…</div>
        ) : workspace.length === 0 ? (
          <div className="px-[20px] py-[28px] text-center text-[0.8rem] text-[#94a3b8]">No assigned students yet. Students assigned to you will appear here.</div>
        ) : (
          <div className="divide-y divide-[#f1f5f9]">
            {workspace.map(({ student, accounts }) => (
              <div key={student.id} className="flex flex-wrap items-center gap-[12px] px-[20px] py-[13px] hover:bg-[#f8fafc]">
                <div className="flex h-[36px] w-[36px] shrink-0 items-center justify-center rounded-full bg-[#dff7f2] text-[0.82rem] font-bold text-[#0f766e]">{student.name.charAt(0)}</div>
                <div className="min-w-[180px] flex-1">
                  <div className="text-[0.82rem] font-semibold text-[#1f2937]">{student.name}</div>
                  <div className="mt-[2px] text-[0.7rem] text-[#94a3b8]">{student.email}</div>
                </div>
                <div className="flex min-w-[240px] flex-1 flex-wrap gap-[6px]">
                  {accounts.length === 0 ? <span className="rounded-full bg-[#f1f5f9] px-[8px] py-[4px] text-[0.66rem] font-semibold text-[#64748b]">No connected accounts</span> : accounts.map((account) => {
                    const verified = account.verification_status === 'verified' && !account.reverification_required && account.availability_status !== 'unavailable'
                    const unavailable = account.availability_status === 'unavailable'
                    return <span key={account.id} className={`rounded-full px-[8px] py-[4px] text-[0.66rem] font-semibold ${verified ? 'bg-[#d1fae5] text-[#065f46]' : unavailable ? 'bg-[#fee2e2] text-[#991b1b]' : 'bg-[#fef3c7] text-[#92400e]'}`} title={account.handle || account.profile_url || account.platform}>{account.platform}: {verified ? 'verified' : unavailable ? 'unavailable' : 'verification needed'}</span>
                  })}
                </div>
                <button onClick={() => { requestStudentWorkspace(student.id); setPage('students') }} className="rounded-[7px] border border-[#99d5ce] px-[10px] py-[7px] text-[0.72rem] font-semibold text-[#0f766e] hover:bg-[#f0fdfa]">Open workspace <i className="ti ti-arrow-up-right text-[12px]" /></button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent referrals */}
      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)]">
        <div className="flex items-center justify-between px-[20px] py-[14px] border-b border-[#f1f5f9]">
          <h3 className="text-[0.9rem] font-bold text-[#1f2937]">Recent Referrals</h3>
          <button onClick={() => setPage('referrals')} className="text-[0.78rem] text-[#0F766E] font-semibold cursor-pointer bg-transparent border-none hover:underline">
            View all
          </button>
        </div>
        {dashboard.recent_referrals.length === 0 ? (
          <div className="py-[40px] text-center text-[#9ca3af] text-[0.82rem]">No recent referrals</div>
        ) : (
          <div className="divide-y divide-[#f1f5f9]">
            {dashboard.recent_referrals.map((r) => (
              <div key={r.id} className="px-[20px] py-[10px] flex items-center gap-[12px]">
                <div className={`w-[8px] h-[8px] rounded-full flex-shrink-0 ${
                  r.urgency === 'crisis' ? 'bg-[#dc2626] animate-pulse' :
                  r.urgency === 'high' ? 'bg-[#ef4444]' :
                  r.urgency === 'medium' ? 'bg-[#f59e0b]' : 'bg-[#9ca3af]'
                }`} />
                <div className="flex-1 min-w-0">
                  <div className="text-[0.8rem] text-[#1f2937] font-medium">{r.student_name || r.student_id}</div>
                  <div className="text-[0.7rem] text-[#6b7280] capitalize">{r.urgency} urgency · {r.status}</div>
                </div>
                <span className="text-[0.7rem] text-[#9ca3af] flex-shrink-0">{formatDate(r.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

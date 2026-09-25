import { useEffect, useState, type ReactNode } from 'react'
import { useCounsellorStore } from '../store/counsellorStore'
import { getStudents, getStudentDetail, approveStudent, revokeStudent, analyzeStudent, getStudentSocialAccounts, type StudentSocialAccount } from '../api/counsellor'
import type { StudentAnalysisResult, StudentDetail } from '../api/counsellor'
import StudentTimeline from '../components/counsellor/StudentTimeline'
import StudentNotes from '../components/counsellor/StudentNotes'
import StudentAccounts from '../components/counsellor/StudentAccounts'

const STATUS_STYLES: Record<string, string> = {
  approved: 'bg-[#d1fae5] text-[#065f46]',
  pending: 'bg-[#fef3c7] text-[#92400e]',
  revoked: 'bg-[#f1f5f9] text-[#6b7280]',
}

function riskTone(score: number): { color: string; label: string } {
  if (score >= 0.75) return { color: '#ef4444', label: 'High risk' }
  if (score >= 0.5) return { color: '#f59e0b', label: 'Elevated risk' }
  return { color: '#22c55e', label: 'Low risk' }
}

function RiskAnalysisPanel({ student, onAnalyzed }: { student: StudentDetail; onAnalyzed: () => void }) {
  const [platform, setPlatform] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<StudentAnalysisResult | null>(null)
  const [error, setError] = useState('')
  const [accounts, setAccounts] = useState<StudentSocialAccount[]>([])

  const available = accounts.filter((account) =>
    account.verification_status === 'verified' &&
    !account.reverification_required &&
    account.availability_status !== 'unavailable'
  )

  const consentDenied = student.consent_status?.enforced === true && student.consent_status?.active === false

  const handleRun = async () => {
    if (!platform || running || consentDenied) return
    setRunning(true)
    setError('')
    try {
      const verifiedAccount = accounts.find((account) => account.platform === platform && account.verification_status === 'verified')
      if (!verifiedAccount) { setError('Select a verified student account before running analysis.'); return }
      const res = await analyzeStudent(student.id, { platform, account_id: verifiedAccount.id })
      setResult(res)
      onAnalyzed()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Analysis failed')
      setResult(null)
    } finally {
      setRunning(false)
    }
  }

  useEffect(() => { getStudentSocialAccounts(student.id).then(setAccounts).catch(() => setAccounts([])) }, [student.id])

  return (
    <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)]">
      <div className="px-[20px] py-[14px] border-b border-[#f1f5f9]">
        <h3 className="text-[0.9rem] font-bold text-[#1f2937] flex items-center gap-[8px]">
          <i className="ti ti-activity-heartbeat text-[16px] text-[#6b7280]" />
          Run Rolling Risk Analysis
        </h3>
      </div>
      <div className="px-[20px] py-[14px]">
        {consentDenied ? (
          <div className="rounded-[7px] border border-[#fef3c7] bg-[#fffbeb] px-[12px] py-[9px] text-[0.78rem] text-[#92400e]">
            This student has no active (accepted, non-expired) consent on record. Analysis is consent-gated —
            dispatch and obtain consent before running a rolling risk analysis.
          </div>
        ) : available.length === 0 ? (
          <div className="text-[0.8rem] text-[#9ca3af]">
            No verified and available student accounts are ready for analysis. The student must complete ownership verification first; private, deleted or unavailable accounts remain blocked.
          </div>
        ) : (
          <>
            <label className="block text-[0.7rem] font-bold uppercase tracking-wider text-[#6b7280] mb-[6px]">
              Verified student account
            </label>
            <div className="flex flex-col sm:flex-row gap-[10px]">
              <select
                value={platform}
                onChange={(e) => { setPlatform(e.target.value); setResult(null); setError('') }}
                className="flex-1 h-[40px] rounded-[7px] border border-[#d1d5db] bg-white px-[11px] text-[0.8rem] text-[#111827] outline-none focus:border-[#0F766E]"
              >
                <option value="">Select a verified account…</option>
                {available.map((account) => (
                  <option key={account.id} value={account.platform}>
                    {account.platform} · {account.handle || account.profile_url || 'verified account'}
                  </option>
                ))}
              </select>
              <button
                onClick={handleRun}
                disabled={!platform || running}
                className="h-[40px] px-[16px] rounded-[7px] bg-[#0F766E] text-white text-[0.8rem] font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#115E59] transition-colors"
              >
                {running ? 'Running…' : 'Run analysis'}
              </button>
            </div>
            <p className="mt-[10px] text-[0.72rem] text-[#6b7280]">
              Consent-gated: the system retrieves only this student’s verified account. Handles and post lists cannot be supplied by the counsellor. Results persist to the risk summary and alert queue.
            </p>
            {error && (
              <div className="mt-[12px] rounded-[7px] border border-[#fecaca] bg-[#fef2f2] px-[12px] py-[9px] text-[0.78rem] text-[#b91c1c]">
                {error}
              </div>
            )}
            {result && (
              <div className="mt-[12px] rounded-[7px] border border-[#e5e7eb] bg-[#f8fafc] px-[14px] py-[12px]">
                <div className="flex items-center justify-between gap-[10px]">
                  <div className="text-[0.8rem] font-bold text-[#1f2937]">
                    Rolling risk: {(result.rolling_score * 100).toFixed(0)}%
                  </div>
                  <span className="text-[0.72rem] font-bold uppercase" style={{ color: riskTone(result.rolling_score).color }}>
                    {riskTone(result.rolling_score).label}
                  </span>
                </div>
                <div className="mt-[8px] text-[0.72rem] text-[#6b7280] space-y-[2px]">
              <div>{result.n_posts} post(s) retrieved and analysed from the verified {result.platform} account</div>
                  <div>
                    {result.alert_created
                      ? <span className="text-[#b91c1c] font-semibold">Risk alert created and queued for follow-up.</span>
                      : 'No alert triggered — score below threshold.'}
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function formatDate(d: string) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function CollapsibleSection({ title, icon, children }: { title: string; icon: string; children: ReactNode }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-[20px] py-[14px] border-b border-[#f1f5f9] cursor-pointer bg-transparent text-left"
      >
        <h3 className="text-[0.9rem] font-bold text-[#1f2937] flex items-center gap-[8px]">
          <i className={`${icon} text-[16px] text-[#6b7280]`} />
          {title}
        </h3>
        <i className={`ti ${open ? 'ti-chevron-up' : 'ti-chevron-down'} text-[#9ca3af] text-[16px]`} />
      </button>
      {open && <div className="px-[20px] py-[14px]">{children}</div>}
    </div>
  )
}

function StudentDetailView({ student, onBack, onRefresh }: { student: StudentDetail; onBack: () => void; onRefresh: () => void }) {
  const gaugeAngle = Math.min(student.risk_summary.latest_prob * 180, 180)
  const gaugeColor = student.risk_summary.latest_prob >= 0.75 ? '#ef4444' : student.risk_summary.latest_prob >= 0.5 ? '#f59e0b' : '#22c55e'

  return (
    <div className="flex flex-col gap-[16px]">
      <button onClick={onBack} className="flex items-center gap-[6px] text-[#0F766E] text-[0.82rem] font-semibold cursor-pointer bg-transparent border-none w-fit">
        <i className="ti ti-arrow-left" /> Back to students
      </button>

      {/* Student header */}
      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[20px] flex items-center gap-[16px]">
        <div className="w-[48px] h-[48px] rounded-full bg-gradient-to-br from-[#0F766E] to-[#1D9E75] flex items-center justify-center text-white font-bold text-[1rem]">
          {student.name.charAt(0)}
        </div>
        <div className="flex-1">
          <h2 className="text-[1.15rem] font-bold text-[#1f2937]">{student.name}</h2>
          <p className="text-[0.8rem] text-[#6b7280]">{student.email} · Joined {formatDate(student.created_at)}</p>
        </div>
        <span className={`inline-block px-[12px] py-[4px] rounded-full text-[0.72rem] font-bold uppercase ${STATUS_STYLES[student.status] || ''}`}>
          {student.status}
        </span>
      </div>

      {/* Risk gauge */}
      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[20px]">
        <h3 className="text-[0.9rem] font-bold text-[#1f2937] mb-[12px]">Risk Assessment</h3>
        <div className="flex items-center gap-[24px]">
          <div className="relative w-[140px] h-[80px] flex-shrink-0">
            <svg viewBox="0 0 160 90" className="w-[140px] h-[80px]">
              <path d="M 15 80 A 65 65 0 0 1 145 80" fill="none" stroke="#e5e7eb" strokeWidth="14" strokeLinecap="round" />
              <path
                d="M 15 80 A 65 65 0 0 1 145 80"
                fill="none"
                stroke={gaugeColor}
                strokeWidth="14"
                strokeLinecap="round"
                strokeDasharray={`${(gaugeAngle / 180) * 204} 204`}
                style={{ transition: 'stroke-dasharray 0.6s ease' }}
              />
              <text x="80" y="60" textAnchor="middle" fill={gaugeColor} fontSize="18" fontWeight="bold">
                {(student.risk_summary.latest_prob * 100).toFixed(0)}%
              </text>
            </svg>
          </div>
          <div className="grid grid-cols-2 gap-x-[24px] gap-y-[8px] text-[0.82rem]">
            <div><span className="text-[#6b7280]">Status</span><br /><span className="font-semibold text-[#1f2937]">{student.risk_summary.latest_label}</span></div>
            <div><span className="text-[#6b7280]">Total analyses</span><br /><span className="font-semibold text-[#1f2937]">{student.risk_summary.total_analyses}</span></div>
            <div><span className="text-[#6b7280]">Latest risk</span><br /><span className="font-semibold text-[#1f2937]">{(student.risk_summary.latest_prob * 100).toFixed(0)}%</span></div>
            <div><span className="text-[#6b7280]">High risk flags</span><br /><span className="font-semibold text-[#ef4444]">{student.risk_summary.high_risk_count}</span></div>
          </div>
        </div>
      </div>

      {/* Run rolling risk analysis (consent-gated) */}
      <RiskAnalysisPanel student={student} onAnalyzed={onRefresh} />

      <StudentAccounts studentId={student.id} />

      {/* Analysis history */}
      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)]">
        <div className="px-[20px] py-[14px] border-b border-[#f1f5f9]">
          <h3 className="text-[0.9rem] font-bold text-[#1f2937]">Analysis History</h3>
        </div>
        {student.analyses.length === 0 ? (
          <div className="py-[40px] text-center text-[#9ca3af] text-[0.82rem]">No analyses recorded yet</div>
        ) : (
          <div className="divide-y divide-[#f1f5f9] max-h-[320px] overflow-y-auto">
            {student.analyses.map((a) => (
              <div key={a.id} className="px-[20px] py-[10px] flex items-center gap-[12px]">
                <div className={`w-[8px] h-[8px] rounded-full flex-shrink-0 ${a.prob >= 0.75 ? 'bg-[#ef4444]' : a.prob >= 0.5 ? 'bg-[#f59e0b]' : 'bg-[#22c55e]'}`} />
                <div className="flex-1 min-w-0">
                  <div className="text-[0.8rem] text-[#1f2937] font-medium truncate">{a.text || `[${a.platform}]`}</div>
                  <div className="text-[0.7rem] text-[#9ca3af]">{a.platform} · {formatDate(a.created_at)}</div>
                </div>
                <span className={`text-[0.78rem] font-bold px-[6px] py-[1px] rounded ${a.prob >= 0.75 ? 'text-[#ef4444] bg-[#fef2f2]' : a.prob >= 0.5 ? 'text-[#f59e0b] bg-[#fffbeb]' : 'text-[#22c55e] bg-[#f0fdf4]'}`}>
                  {(a.prob * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Risk Timeline */}
      <CollapsibleSection title="Risk Timeline" icon="ti ti-chart-line">
        <StudentTimeline studentId={student.id} />
      </CollapsibleSection>

      {/* Counsellor Notes */}
      <CollapsibleSection title="Counsellor Notes" icon="ti ti-notes">
        <StudentNotes studentId={student.id} />
      </CollapsibleSection>
    </div>
  )
}

export default function StudentManagementPage() {
  const { students, loading, setStudents, updateStudentStatus, setLoading } = useCounsellorStore()
  const [detailId, setDetailId] = useState<string | null>(null)
  const [studentDetail, setStudentDetail] = useState<StudentDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [notice, setNotice] = useState<{ tone: 'ok' | 'warn' | 'err'; text: string } | null>(null)
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null)

  const handleStatusChange = async (studentId: string, action: 'approve' | 'revoke') => {
    setActionLoadingId(studentId)
    setNotice(null)
    try {
      const result = action === 'approve'
        ? await approveStudent(studentId)
        : await revokeStudent(studentId)
      updateStudentStatus(studentId, action === 'approve' ? 'approved' : 'revoked')
      if (result.email_sent) {
        setNotice({ tone: 'ok', text: `Student ${action === 'approve' ? 'approved' : 'revoked'} — notification email sent.` })
      } else {
        setNotice({
          tone: 'warn',
          text: `Student ${action === 'approve' ? 'approved' : 'revoked'}, but the notification email could not be sent${result.email_error ? `: ${result.email_error}` : '.'}`,
        })
      }
    } catch (e) {
      setNotice({ tone: 'err', text: e instanceof Error ? e.message : `Failed to ${action} student.` })
    } finally {
      setActionLoadingId(null)
    }
  }

  const loadStudents = async () => {
    setLoading(true)
    try {
      const data = await getStudents()
      setStudents(data)
    } catch { /* the page remains usable with the existing list */ }
    setLoading(false)
  }

  useEffect(() => {
    if (students.length === 0) {
      void loadStudents()
    }
  }, [])

  const openDetail = async (id: string) => {
    setDetailId(id)
    setDetailLoading(true)
    setStudentDetail(null)
    try {
      const data = await getStudentDetail(id)
      setStudentDetail(data)
    } catch { /* the detail view will remain empty and recover on retry */ }
    setDetailLoading(false)
  }

  const closeDetail = () => {
    setDetailId(null)
    setStudentDetail(null)
  }

  if (detailId) {
    if (detailLoading) {
      return (
        <div className="flex items-center justify-center py-[80px]">
          <div className="w-[28px] h-[28px] border-2 border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin mr-[10px]" />
          <span className="text-[0.82rem] text-[#6b7280]">Loading student details...</span>
        </div>
      )
    }
    if (studentDetail) {
      return <StudentDetailView student={studentDetail} onBack={closeDetail} onRefresh={() => openDetail(detailId!)} />
    }
  }

  return (
    <div className="flex flex-col gap-[16px]">
      <div>
        <h2 className="text-[1.3rem] font-bold text-[#1f2937]">Student Management</h2>
        <p className="text-[0.82rem] text-[#6b7280] mt-[2px]">
          View and manage students assigned to you
        </p>
      </div>

      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] overflow-hidden">
        {notice && (
          <div className={`m-[16px] mb-0 rounded-[8px] border px-[12px] py-[9px] text-[0.8rem] ${
            notice.tone === 'ok' ? 'bg-[#ecfdf5] border-[#bbf7d0] text-[#065f46]'
            : notice.tone === 'warn' ? 'bg-[#fff7ed] border-[#fed7aa] text-[#9a3412]'
            : 'bg-[#fef2f2] border-[#fecaca] text-[#991b1b]'
          }`} role="status">
            <i className={`ti ${notice.tone === 'ok' ? 'ti-circle-check' : 'ti-alert-circle'} text-[14px] mr-[6px]`} />{notice.text}
          </div>
        )}
        <div className="flex items-center justify-between px-[20px] py-[14px] border-b border-[#f1f5f9]">
          <div className="flex items-center gap-[8px]">
            <i className="ti ti-list text-[16px] text-[#6b7280]" />
            <span className="text-[0.9rem] font-bold text-[#1f2937]">Assigned students</span>
            <span className="text-[0.78rem] text-[#9ca3af] ml-[4px]">({students.length})</span>
          </div>
          <button
            onClick={loadStudents}
            className="flex items-center gap-[6px] px-[12px] py-[6px] bg-[#0F766E] text-white rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#115E59] transition-colors"
          >
            <i className="ti ti-refresh text-[14px]" />
            Refresh
          </button>
        </div>

        {loading && students.length === 0 ? (
          <div className="flex items-center justify-center py-[60px] text-[#6b7280]">
            <div className="w-[24px] h-[24px] border-2 border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin mr-[10px]" />
            <span className="text-[0.82rem]">Loading students...</span>
          </div>
        ) : students.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-[60px] text-[#9ca3af]">
            <i className="ti ti-users text-[32px] mb-[8px]" />
            <span className="text-[0.82rem]">No students found</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[0.82rem]">
              <thead>
                <tr className="text-[#6b7280] font-semibold text-[0.72rem] uppercase tracking-wider">
                  <th className="text-left py-[12px] px-[20px]">Name</th>
                  <th className="text-left py-[12px] px-[20px]">Email</th>
                  <th className="text-left py-[12px] px-[20px]">Status</th>
                  <th className="text-left py-[12px] px-[20px]">Joined</th>
                  <th className="text-left py-[12px] px-[20px]">Actions</th>
                </tr>
              </thead>
              <tbody>
                {students.map((student) => (
                  <tr
                    key={student.id}
                    className="border-t border-[#f1f5f9] hover:bg-[#f8fafc] cursor-pointer transition-colors"
                    onClick={() => openDetail(student.id)}
                  >
                    <td className="py-[12px] px-[20px] font-medium text-[#1f2937]">{student.name}</td>
                    <td className="py-[12px] px-[20px] text-[#6b7280]">{student.email}</td>
                    <td className="py-[12px] px-[20px]">
                      <span
                        className={`inline-block px-[10px] py-[3px] rounded-full text-[0.7rem] font-bold uppercase ${
                          STATUS_STYLES[student.status] || ''
                        }`}
                      >
                        {student.status}
                      </span>
                    </td>
                    <td className="py-[12px] px-[20px] text-[#6b7280]">{formatDate(student.created_at)}</td>
                    <td className="py-[12px] px-[20px]" onClick={(e) => e.stopPropagation()}>
                      {student.status === 'pending' ? (
                        <button
                          onClick={() => handleStatusChange(student.id, 'approve')}
                          disabled={actionLoadingId === student.id}
                          className="text-[#0F766E] font-bold cursor-pointer hover:underline bg-transparent border-none text-[0.82rem] disabled:opacity-50"
                        >
                          {actionLoadingId === student.id ? '…' : 'Approve'}
                        </button>
                      ) : student.status === 'approved' ? (
                        <button
                          onClick={() => handleStatusChange(student.id, 'revoke')}
                          disabled={actionLoadingId === student.id}
                          className="text-[#9ca3af] cursor-pointer hover:text-[#6b7280] bg-transparent border-none text-[0.82rem] disabled:opacity-50"
                        >
                          {actionLoadingId === student.id ? '…' : 'Revoke'}
                        </button>
                      ) : (
                        <span className="text-[#d1d5db]">Revoked</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  commitRoster,
  getInstitutions,
  getRosterStudents,
  runConsentMaintenance,
  uploadRoster,
} from '../../api/admin'
import RosterErrorReport from './RosterErrorReport'
import type { Institution, RosterDispatchSummary, RosterStudent, RosterUploadSummary } from '../../types'

const CONSENT_STYLE: Record<string, string> = {
  ACCEPTED: 'bg-[#d1fae5] text-[#065f46]',
  PENDING: 'bg-[#fef3c7] text-[#92400e]',
  VIEWED: 'bg-[#dbeafe] text-[#1e40af]',
  DECLINED: 'bg-[#fee2e2] text-[#991b1b]',
  EXPIRED: 'bg-[#f1f5f9] text-[#6b7280]',
  REVOKED: 'bg-[#fee2e2] text-[#991b1b]',
}

export default function RosterPanel() {
  const [institutions, setInstitutions] = useState<Institution[]>([])
  const [institutionId, setInstitutionId] = useState('')
  const [students, setStudents] = useState<RosterStudent[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [summary, setSummary] = useState<RosterUploadSummary | null>(null)
  const [dispatch, setDispatch] = useState<RosterDispatchSummary | null>(null)
  const [sendOnUpload, setSendOnUpload] = useState(false)
  const [maintaining, setMaintaining] = useState(false)
  const [maintenanceMsg, setMaintenanceMsg] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const loadInstitutions = useCallback(async () => {
    try {
      const insts = await getInstitutions()
      setInstitutions(insts)
      if (insts.length > 0 && !institutionId) setInstitutionId(insts[0].id)
    } catch (e: any) {
      setError(e.message)
    }
  }, [institutionId])

  const loadStudents = useCallback(async () => {
    if (!institutionId) return
    setLoading(true)
    setError(null)
    try {
      setStudents(await getRosterStudents(institutionId))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [institutionId])

  useEffect(() => { loadInstitutions() }, [loadInstitutions])
  useEffect(() => { loadStudents() }, [loadStudents])

  const handleUpload = async () => {
    if (!file || !institutionId) {
      setError(institutions.length ? 'Select an institution before uploading.' : 'Create an institution before uploading.')
      return
    }
    setUploading(true)
    setSummary(null)
    setDispatch(null)
    setError(null)
    try {
      if (sendOnUpload) {
        const result = await commitRoster(file, institutionId)
        setSummary(result.roster)
        setDispatch(result.dispatch)
      } else {
        setSummary(await uploadRoster(file, institutionId))
      }
      await loadStudents()
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
    } catch (e: any) {
      setError(e.message)
    } finally {
      setUploading(false)
    }
  }

  const handleMaintenance = async () => {
    setMaintaining(true)
    setMaintenanceMsg(null)
    try {
      const result = await runConsentMaintenance()
      setMaintenanceMsg(
        `Maintenance complete: ${result.expired} expired, ${result.reminders.sent} reminder(s) sent, ${result.reminders.failed} failed.`
      )
      await loadStudents()
    } catch (e: any) {
      setMaintenanceMsg(null)
      setError(e.message)
    } finally {
      setMaintaining(false)
    }
  }

  const accepted = students.filter((s) => s.consent_status === 'ACCEPTED').length

  const term = search.trim().toLowerCase()
  const filteredStudents = term
    ? students.filter((s) =>
        s.name.toLowerCase().includes(term) ||
        s.email.toLowerCase().includes(term) ||
        s.id.toLowerCase().includes(term))
    : students

  return (
    <div className="flex flex-col gap-[16px]">
      {/* Upload card */}
      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[20px]">
        <div className="flex items-center gap-[8px] mb-[14px]">
          <i className="ti ti-upload text-[16px] text-[#0F766E]" />
          <span className="text-[0.9rem] font-bold text-[#1f2937]">Upload roster (CSV)</span>
        </div>
        <div className="grid md:grid-cols-3 gap-[12px] items-end">
          <div>
            <label className="block text-[0.78rem] font-semibold text-[#374151] mb-[4px]">Institution *</label>
            <select
              value={institutionId}
              onChange={(e) => setInstitutionId(e.target.value)}
              className="w-full rounded-[8px] border border-[#e5e7eb] px-[10px] py-[8px] text-[0.82rem] text-[#1f2937] bg-white focus:outline-none focus:ring-2 focus:ring-[#0F766E]"
            >
              <option value="">Select institution...</option>
            {institutions.map((i) => (
              <option key={i.id} value={i.id}>{i.name}</option>
            ))}
          </select>
          {institutions.length === 0 && (
            <p className="text-[0.72rem] text-[#92400e] mt-[4px]">No institutions yet — add one below to upload a roster.</p>
          )}
          {institutions.length === 0 && <p className="mt-1 text-xs text-amber-800">No institutions yet. Create one from Global Admin → Institutions before importing a roster.</p>}
        </div>
          <div>
            <label className="block text-[0.78rem] font-semibold text-[#374151] mb-[4px]">CSV file</label>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="w-full text-[0.8rem] text-[#6b7280] file:mr-[8px] file:px-[10px] file:py-[6px] file:rounded-[7px] file:border-none file:bg-[#f1f5f9] file:text-[#374151] file:font-semibold file:cursor-pointer"
            />
            <p className="text-[0.7rem] text-[#9ca3af] mt-[4px]">
              Required: student_id, first_name, last_name, email. Optional: date_of_birth, grade_level, parent_email.
            </p>
          </div>
          <div className="flex gap-[8px]">
            <button
              onClick={handleUpload}
              disabled={!file || uploading}
              className="flex-1 flex items-center justify-center gap-[6px] px-[14px] py-[8px] bg-[#0F766E] text-white rounded-[8px] text-[0.82rem] font-semibold cursor-pointer hover:bg-[#0d5c56] transition-colors disabled:opacity-50"
            >
              {uploading ? (
                <div className="w-[14px] h-[14px] border-2 border-white/40 border-t-white rounded-full animate-spin" />
              ) : (
                <i className="ti ti-cloud-upload text-[14px]" />
              )}
              {uploading ? 'Uploading...' : sendOnUpload ? 'Upload & send consents' : 'Upload'}
            </button>
            <button
              onClick={handleMaintenance}
              disabled={maintaining}
              className="px-[14px] py-[8px] border border-[#e5e7eb] text-[#374151] rounded-[8px] text-[0.82rem] font-semibold cursor-pointer hover:bg-[#f9fafb] transition-colors bg-white disabled:opacity-50"
            >
              {maintaining ? 'Running...' : 'Run maintenance'}
            </button>
          </div>
        </div>

        <div className="mt-[12px]">
          <label className="flex items-center gap-[8px] cursor-pointer select-none">
            <input
              type="checkbox"
              checked={sendOnUpload}
              onChange={(e) => setSendOnUpload(e.target.checked)}
              className="w-[15px] h-[15px] accent-[#0F766E] cursor-pointer"
            />
            <span className="text-[0.8rem] text-[#374151]">
              Send consent requests immediately (one-action upload + dispatch, Delivery Brief §2.5)
            </span>
          </label>
        </div>

        {summary && (
          <div className={`mt-[14px] rounded-[10px] border px-[14px] py-[10px] text-[0.82rem] ${
            summary.parse_error
              ? 'bg-[#fff7ed] border-[#fed7aa] text-[#9a3412]'
              : 'bg-[#ecfdf5] border-[#bbf7d0] text-[#065f46]'
          }`}>
            <div className="font-bold mb-[2px]">
              {summary.parse_error ? 'Roster rejected' : 'Upload complete'}
            </div>
            {summary.parse_error && (
              <div className="mb-[6px]">{summary.parse_error}</div>
            )}
            <div>
              {summary.created} created · {summary.updated} updated · {summary.total} total
              {' · '}{summary.minors} minor(s) · {summary.adults} adult(s)
              {summary.errors.length ? ` · ${summary.errors.length} row(s) failed` : ''}
            </div>
            <RosterErrorReport summary={summary} />
          </div>
        )}

        {dispatch && (
          <div className="mt-[10px] rounded-[10px] bg-[#eff6ff] border border-[#bfdbfe] px-[14px] py-[10px] text-[0.82rem] text-[#1e40af]">
            <div className="font-bold mb-[2px]">Consent dispatch</div>
            <div>
              {dispatch.dispatched} request(s) dispatched · {dispatch.email_queued} email(s) queued ·{' '}
              {dispatch.courtesy_queued} courtesy copy/copies
            </div>
            <div className="mt-[2px] text-[0.76rem] text-[#64748b]">
              {dispatch.skipped_live} already consented · {dispatch.skipped_no_parent} minor(s) without parent email
              {dispatch.users_created ? ` · ${dispatch.users_created} account(s) created` : ''}
            </div>
            {dispatch.routing_errors.length > 0 && (
              <div className="mt-[6px] max-h-[120px] overflow-y-auto text-[0.76rem] text-[#991b1b]">
                {dispatch.routing_errors.slice(0, 10).map((e, i) => (
                  <div key={i}>{e.student_id} — {e.reason}</div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {maintenanceMsg && (
        <div className="rounded-[10px] bg-[#ecfdf5] border border-[#bbf7d0] px-[14px] py-[10px] text-[0.82rem] text-[#065f46]">
          {maintenanceMsg}
        </div>
      )}

      {/* Students table */}
      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] overflow-hidden">
        <div className="flex items-center justify-between px-[20px] py-[14px] border-b border-[#f1f5f9]">
          <div className="flex items-center gap-[8px]">
            <i className="ti ti-users text-[16px] text-[#6b7280]" />
            <span className="text-[0.9rem] font-bold text-[#1f2937]">Students</span>
            {!loading && (
              <span className="text-[0.78rem] text-[#9ca3af] ml-[4px]">
                ({filteredStudents.length} of {students.length}) · {accepted} consented
              </span>
            )}
          </div>
          <div className="flex items-center gap-[8px]">
            <div className="relative">
              <i className="ti ti-search absolute left-[10px] top-1/2 -translate-y-1/2 text-[13px] text-[#9ca3af]" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search students..."
                className="rounded-[7px] border border-[#e5e7eb] pl-[28px] pr-[10px] py-[6px] text-[0.78rem] text-[#1f2937] placeholder-[#9ca3af] bg-white focus:outline-none focus:ring-2 focus:ring-[#0F766E] w-[200px]"
              />
            </div>
            <button
              onClick={loadStudents}
              className="flex items-center gap-[6px] px-[12px] py-[6px] bg-[#0F766E] text-white rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#115E59] transition-colors"
            >
              <i className="ti ti-refresh text-[14px]" />
              Refresh
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-[40px] text-[#6b7280]">
            <div className="w-[24px] h-[24px] border-2 border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin mr-[10px]" />
            <span className="text-[0.82rem]">Loading students...</span>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-[40px] text-[#ef4444]">
            <i className="ti ti-alert-circle text-[28px] mb-[6px]" />
            <span className="text-[0.82rem]">{error}</span>
          </div>
        ) : filteredStudents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-[40px] text-[#9ca3af]">
            <i className="ti ti-search text-[28px] mb-[6px]" />
            <span className="text-[0.82rem]">No students match your search.</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[0.82rem]">
              <thead className="bg-[#f9fafb]">
                <tr className="text-[#6b7280] font-semibold text-[0.72rem] uppercase tracking-wider">
                  <th className="text-left py-[10px] px-[20px]">Student</th>
                  <th className="text-left py-[10px] px-[20px]">Grade</th>
                  <th className="text-left py-[10px] px-[20px]">Age group</th>
                  <th className="text-left py-[10px] px-[20px]">Consent</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f1f5f9]">
                {filteredStudents.map((s) => (
                  <tr key={s.id} className="hover:bg-[#f8fafc] transition-colors">
                    <td className="py-[12px] px-[20px]">
                      <div className="text-[#1f2937] font-medium">{s.name}</div>
                      <div className="text-[0.7rem] text-[#9ca3af]">{s.email}</div>
                    </td>
                    <td className="py-[12px] px-[20px] text-[#6b7280]">{s.grade_level || '—'}</td>
                    <td className="py-[12px] px-[20px]">
                      {s.is_minor ? (
                        <span className="inline-block px-[8px] py-[2px] rounded-full text-[0.7rem] font-semibold bg-[#fef3c7] text-[#92400e]">
                          Minor
                        </span>
                      ) : (
                        <span className="inline-block px-[8px] py-[2px] rounded-full text-[0.7rem] font-semibold bg-[#f1f5f9] text-[#6b7280]">
                          Adult
                        </span>
                      )}
                    </td>
                    <td className="py-[12px] px-[20px]">
                      {s.consent_status ? (
                        <span className={`inline-block px-[8px] py-[2px] rounded-full text-[0.7rem] font-semibold ${CONSENT_STYLE[s.consent_status] || 'bg-[#f1f5f9] text-[#6b7280]'}`}>
                          {s.consent_status.replace(/_/g, ' ')}
                        </span>
                      ) : (
                        <span className="text-[0.72rem] text-[#9ca3af]">No consent yet</span>
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

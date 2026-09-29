import { useEffect, useMemo, useState } from 'react'
import Plot from 'react-plotly.js'
import {
  analyzeStudent,
  getStudentDetail,
  getStudentSocialAccounts,
  getStudents,
  type StudentDTO,
  type StudentSocialAccount,
  type StudentAnalysisResult,
} from '../api/counsellor'
import { useCounsellorStore } from '../store/counsellorStore'
import { useUiStore } from '../store/uiStore'

const RETRIEVABLE_PLATFORMS = new Set(['reddit', 'bluesky', 'mastodon', 'youtube'])

type RunRow = {
  account: StudentSocialAccount
  status: 'queued' | 'running' | 'complete' | 'failed'
  message: string
  result?: StudentAnalysisResult
}

const accountLabel = (account: StudentSocialAccount) =>
  account.handle || account.profile_url || `${account.platform} account`

export default function CounsellorBatchAnalysisPage() {
  const analysisStudentId = useCounsellorStore((state) => state.analysisStudentId)
  const setAnalysisStudentId = useCounsellorStore((state) => state.setAnalysisStudentId)
  const setPage = useUiStore((state) => state.setPage)
  const [students, setStudents] = useState<StudentDTO[]>([])
  const [studentId, setStudentId] = useState(analysisStudentId || '')
  const [accounts, setAccounts] = useState<StudentSocialAccount[]>([])
  const [selectedAccountIds, setSelectedAccountIds] = useState<string[]>([])
  const [rows, setRows] = useState<RunRow[]>([])
  const [consentActive, setConsentActive] = useState(false)
  const [studentsLoading, setStudentsLoading] = useState(true)
  const [studentLoading, setStudentLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    getStudents()
      .then((data) => { if (active) setStudents(data) })
      .catch((err: unknown) => { if (active) setError(err instanceof Error ? err.message : 'Could not load your assigned students.') })
      .finally(() => { if (active) setStudentsLoading(false) })
    return () => { active = false }
  }, [])

  const availableAccounts = useMemo(() => accounts.filter((account) =>
    RETRIEVABLE_PLATFORMS.has(account.platform.toLowerCase()) &&
    account.verification_status === 'verified' &&
    !account.reverification_required &&
    (account.availability_status == null || account.availability_status === 'available')
  ), [accounts])

  const loadStudent = async (id: string) => {
    setStudentId(id)
    setAnalysisStudentId(id || null)
    setAccounts([])
    setSelectedAccountIds([])
    setRows([])
    setConsentActive(false)
    setError('')
    if (!id) return
    setStudentLoading(true)
    try {
      const [detail, linkedAccounts] = await Promise.all([
        getStudentDetail(id),
        getStudentSocialAccounts(id),
      ])
      setConsentActive(detail.consent_status?.active === true)
      setAccounts(linkedAccounts)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load this student’s consent and account status.')
    } finally {
      setStudentLoading(false)
    }
  }

  const toggleAccount = (accountId: string) => {
    setSelectedAccountIds((current) => current.includes(accountId)
      ? current.filter((id) => id !== accountId)
      : [...current, accountId])
  }

  const runSelected = async () => {
    if (!studentId || !consentActive || running) return
    const selected = availableAccounts.filter((account) => selectedAccountIds.includes(account.id))
    if (selected.length === 0) return
    setRunning(true)
    setError('')
    setRows(selected.map((account) => ({ account, status: 'queued', message: 'Waiting to run' })))

    // Run sequentially: platform retrieval/model inference is expensive and shares the account rate limit.
    for (const account of selected) {
      setRows((current) => current.map((row) => row.account.id === account.id
        ? { ...row, status: 'running', message: 'Retrieving and analysing verified account…' }
        : row))
      try {
        const result = await analyzeStudent(studentId, {
          platform: account.platform,
          account_id: account.id,
        })
        setRows((current) => current.map((row) => row.account.id === account.id
          ? { ...row, status: 'complete', message: `${result.n_posts} post(s) reviewed`, result }
          : row))
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Analysis could not be completed.'
        setRows((current) => current.map((row) => row.account.id === account.id
          ? { ...row, status: 'failed', message }
          : row))
      }
    }
    setRunning(false)
  }

  const studentName = students.find((student) => student.id === studentId)?.name
  const completedRows = rows.filter((row) => row.status === 'complete' && row.result?.rolling_score != null && Number.isFinite(Number(row.result.rolling_score)))

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-5 md:p-8">
      <header>
        <p className="text-xs font-bold uppercase tracking-[0.14em] text-teal-700">Assigned-student workspace</p>
        <h1 className="mt-1 text-2xl font-bold text-slate-900">Batch analysis</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
          Run consent-gated analysis across a student’s selected, ownership-verified accounts in sequence. Handles and account targets come from the student’s saved account records—not free-form input.
        </p>
      </header>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <label htmlFor="batch-student" className="mb-2 block text-sm font-semibold text-slate-800">Assigned student</label>
        <select id="batch-student" value={studentId} onChange={(event) => void loadStudent(event.target.value)} disabled={studentsLoading || running} className="min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 focus:border-teal-700 focus:outline-none">
          <option value="">Select a student…</option>
          {students.map((student) => <option key={student.id} value={student.id}>{student.name} · {student.email}</option>)}
        </select>
        {studentsLoading && <p className="mt-2 text-sm text-slate-500">Loading assigned students…</p>}
        {!studentsLoading && students.length === 0 && <p className="mt-2 text-sm text-slate-600">No assigned students are available in your caseload.</p>}
      </section>

      {studentId && <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-slate-900">{studentName || 'Student'} · connected accounts</h2>
        {studentLoading ? <p className="mt-3 text-sm text-slate-500">Checking consent and account readiness…</p> : (
          <>
            {!consentActive ? <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" role="status">Analysis is unavailable until this student has active consent. Consent is checked again by the server for every account run.</div> : (
              <p className="mt-2 text-sm text-slate-600">Active consent confirmed. Select one or more accounts below; each remains independently consent- and verification-gated.</p>
            )}
            {availableAccounts.length === 0 ? <div className="mt-4 rounded-lg bg-slate-50 p-4 text-sm text-slate-600">No accounts are currently eligible. The student must have active consent and a verified, available account on a supported retrieval platform (Reddit, Bluesky, Mastodon, or YouTube). X/Twitter and other unavailable integrations stay blocked.</div> : (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {availableAccounts.map((account) => <label key={account.id} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 ${selectedAccountIds.includes(account.id) ? 'border-teal-600 bg-teal-50' : 'border-slate-200 hover:border-slate-300'}`}>
                  <input type="checkbox" checked={selectedAccountIds.includes(account.id)} disabled={!consentActive || running || studentLoading} onChange={() => toggleAccount(account.id)} className="mt-1 accent-teal-700" />
                  <span className="min-w-0"><span className="block font-semibold capitalize text-slate-900">{account.platform}</span><span className="block break-all text-sm text-slate-600">{accountLabel(account)}</span><span className="mt-1 inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800">Verified · available</span></span>
                </label>)}
              </div>
            )}
            {accounts.some((account) => !RETRIEVABLE_PLATFORMS.has(account.platform.toLowerCase())) && <p className="mt-3 text-xs leading-5 text-slate-500">Some connected platforms are omitted because verified retrieval is not currently supported for them. No arbitrary handle or file-upload analysis is available in this student-bound workflow.</p>}
            <button type="button" onClick={() => void runSelected()} disabled={!consentActive || selectedAccountIds.length === 0 || running || studentLoading} className="mt-5 min-h-11 w-full rounded-lg bg-teal-800 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-900 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto">
              {running ? 'Running selected accounts…' : `Run selected analyses (${selectedAccountIds.length})`}
            </button>
          </>
        )}
      </section>}

      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800" role="alert">{error}</div>}

      {rows.length > 0 && <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" aria-live="polite">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="text-lg font-bold text-slate-900">Run progress</h2><p className="mt-1 text-sm text-slate-600">Each account can succeed or fail independently; successful results are recorded in the student’s analysis history.</p></div>
          {!running && rows.some((row) => row.status === 'complete') && <button onClick={() => setPage('unified')} className="rounded-lg border border-teal-700 px-3 py-2 text-sm font-semibold text-teal-800 hover:bg-teal-50">Open multi-platform report</button>}
        </div>
        <div className="mt-4 space-y-3">
          {rows.map((row) => <div key={row.account.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-50 p-4">
            <div className="min-w-0"><p className="font-semibold capitalize text-slate-900">{row.account.platform} · {accountLabel(row.account)}</p><p className={`mt-1 text-sm ${row.status === 'failed' ? 'text-red-700' : 'text-slate-600'}`}>{row.message}</p></div>
            {row.result && <p className="text-sm font-semibold text-teal-800">Rolling signal: {Number.isFinite(row.result.rolling_score) ? `${(row.result.rolling_score * 100).toFixed(0)}%` : 'not available'}</p>}
            <span className={`rounded-full px-2.5 py-1 text-xs font-bold uppercase ${row.status === 'complete' ? 'bg-emerald-100 text-emerald-800' : row.status === 'failed' ? 'bg-red-100 text-red-800' : row.status === 'running' ? 'bg-blue-100 text-blue-800' : 'bg-slate-200 text-slate-700'}`}>{row.status}</span>
          </div>)}
        </div>
        {completedRows.length > 0 && <div className="mt-5 rounded-xl border border-slate-200 p-4">
          <h3 className="font-bold text-slate-900">Completed platform comparison</h3>
          <p className="mt-1 text-xs text-slate-500">Missing or failed platforms remain visible above and are never treated as zero.</p>
          <Plot data={[{ type: 'bar', x: completedRows.map(row => row.account.platform), y: completedRows.map(row => Math.max(0, Math.min(1, Number(row.result?.rolling_score)))), marker: { color: '#0f766e' }, text: completedRows.map(row => `${(Number(row.result?.rolling_score) * 100).toFixed(0)}%`), textposition: 'outside' }]} layout={{ autosize: true, height: 320, margin: { l: 50, r: 20, t: 20, b: 45 }, yaxis: { range: [0, 1.1], tickformat: '.0%' }, paper_bgcolor: 'transparent', plot_bgcolor: '#fff' }} config={{ responsive: true, displaylogo: false, toImageButtonOptions: { filename: `mindguard-${studentId}-batch-comparison` } }} className="w-full" />
        </div>}
        {rows.some((row) => row.status === 'complete') && <p className="mt-4 rounded-lg border border-blue-100 bg-blue-50 p-3 text-xs leading-5 text-blue-900">Decision-support signals are shown separately by platform. They are not a diagnosis and are not combined into an unvalidated single score. Review source context with the student.</p>}
      </section>}
    </main>
  )
}

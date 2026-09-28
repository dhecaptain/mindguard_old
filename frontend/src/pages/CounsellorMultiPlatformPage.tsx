import { useEffect, useMemo, useState } from 'react'
import {
  getStudentDetail,
  getStudents,
  type StudentDTO,
  type StudentDetail,
} from '../api/counsellor'
import { useCounsellorStore } from '../store/counsellorStore'

type PlatformSummary = {
  platform: string
  score: number
  createdAt: string
  posts: number
  sessionId: string
}

export default function CounsellorMultiPlatformPage() {
  const analysisStudentId = useCounsellorStore((state) => state.analysisStudentId)
  const setAnalysisStudentId = useCounsellorStore((state) => state.setAnalysisStudentId)
  const [students, setStudents] = useState<StudentDTO[]>([])
  const [studentId, setStudentId] = useState(analysisStudentId || '')
  const [detail, setDetail] = useState<StudentDetail | null>(null)
  const [loadingStudents, setLoadingStudents] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState('')

  const loadStudent = async (id: string) => {
    setStudentId(id)
    setAnalysisStudentId(id || null)
    setDetail(null)
    setError('')
    if (!id) return
    setLoadingDetail(true)
    try { setDetail(await getStudentDetail(id)) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not load this student’s analysis history.') }
    finally { setLoadingDetail(false) }
  }

  useEffect(() => {
    let active = true
    getStudents()
      .then(async (data) => {
        if (!active) return
        setStudents(data)
        if (analysisStudentId && data.some((student) => student.id === analysisStudentId)) {
          setStudentId(analysisStudentId)
          setLoadingDetail(true)
          try {
            const studentDetail = await getStudentDetail(analysisStudentId)
            if (active) setDetail(studentDetail)
          } catch (err) {
            if (active) setError(err instanceof Error ? err.message : 'Could not load this student’s analysis history.')
          } finally {
            if (active) setLoadingDetail(false)
          }
        } else {
          setStudentId('')
          setAnalysisStudentId(null)
        }
      })
      .catch((err: unknown) => { if (active) setError(err instanceof Error ? err.message : 'Could not load assigned students.') })
      .finally(() => { if (active) setLoadingStudents(false) })
    return () => { active = false }
  }, [analysisStudentId, setAnalysisStudentId])

  const summaries = useMemo(() => {
    const latest = new Map<string, PlatformSummary>()
    for (const session of detail?.analysis_sessions || []) {
      if (session.risk_score == null || !Number.isFinite(Number(session.risk_score))) continue
      for (const platform of session.platforms || []) {
        const key = platform.toLowerCase()
        if (latest.has(key)) continue
        latest.set(key, {
          platform,
          score: Number(session.risk_score),
          createdAt: session.created_at,
          posts: session.findings?.posts?.length || 0,
          sessionId: session.id,
        })
      }
    }
    return [...latest.values()].sort((a, b) => a.platform.localeCompare(b.platform))
  }, [detail])

  const selectedStudent = students.find((student) => student.id === studentId)
  const formatDate = (value: string) => {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString()
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-5 md:p-8">
      <header>
        <p className="text-xs font-bold uppercase tracking-[0.14em] text-teal-700">Assigned-student workspace</p>
        <h1 className="mt-1 text-2xl font-bold text-slate-900">Multi-platform report</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">Compare the latest recorded analysis session for each platform of a student assigned to you. Results are retrieved only through that student’s verified accounts and active consent.</p>
      </header>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <label htmlFor="report-student" className="mb-2 block text-sm font-semibold text-slate-800">Assigned student</label>
        <select id="report-student" value={studentId} onChange={(event) => void loadStudent(event.target.value)} disabled={loadingStudents} className="min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 focus:border-teal-700 focus:outline-none">
          <option value="">Select a student…</option>
          {students.map((student) => <option key={student.id} value={student.id}>{student.name} · {student.email}</option>)}
        </select>
        {loadingStudents && <p className="mt-2 text-sm text-slate-500">Loading assigned students…</p>}
        {selectedStudent && <p className="mt-2 text-sm text-slate-600">Showing recorded results for {selectedStudent.name}. This view refreshes from the student’s saved analysis history.</p>}
      </section>

      {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>}
      {loadingDetail && <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">Loading the student’s analysis history…</div>}
      {studentId && !loadingDetail && detail && <>
        {summaries.length === 0 ? <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-teal-50 text-teal-800"><i className="ti ti-chart-dots-3 text-xl" /></div>
          <h2 className="mt-3 font-bold text-slate-900">No platform results yet</h2>
          <p className="mx-auto mt-1 max-w-lg text-sm text-slate-600">Run one or more verified-account analyses from Batch Analysis. Successfully saved sessions will appear here.</p>
        </section> : <>
          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {summaries.map((summary) => {
              const score = Math.max(0, Math.min(1, summary.score))
              const color = score >= 0.75 ? 'bg-red-600' : score >= 0.5 ? 'bg-amber-500' : 'bg-emerald-600'
              const textColor = score >= 0.75 ? 'text-red-800' : score >= 0.5 ? 'text-amber-800' : 'text-emerald-800'
              return <article key={`${summary.sessionId}-${summary.platform}`} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex items-start justify-between gap-3"><h2 className="font-bold capitalize text-slate-900">{summary.platform}</h2><span className={`rounded-full bg-slate-100 px-2 py-1 text-xs font-bold ${textColor}`}>{(score * 100).toFixed(0)}% signal</span></div>
                <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100" role="img" aria-label={`${summary.platform} recorded signal ${(score * 100).toFixed(0)} percent`}><div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${score * 100}%` }} /></div>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-sm"><div><dt className="text-slate-500">Posts reviewed</dt><dd className="mt-0.5 font-semibold text-slate-900">{summary.posts}</dd></div><div><dt className="text-slate-500">Run date</dt><dd className="mt-0.5 font-semibold text-slate-900">{formatDate(summary.createdAt)}</dd></div></dl>
              </article>
            })}
          </section>
          <p className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm leading-6 text-blue-900">Signals are platform-specific decision-support information, not diagnoses. They are not averaged into a single cross-platform score. Review the underlying session and discuss context with the student before deciding on follow-up.</p>
        </>}
      </>}
    </main>
  )
}

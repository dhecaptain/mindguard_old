import { useEffect, useMemo, useState } from 'react'
import Plot from '../lib/plotly'
import api from '../api/client'
import SocioEconomicPanel from '../components/analysis/SocioEconomicPanel'
import type { SocioeconomicSignal } from '../types'
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

const mergeSignals = (
  target: Record<string, SocioeconomicSignal[]>,
  source: Record<string, SocioeconomicSignal[]> | undefined,
) => {
  if (!source) return
  for (const [category, items] of Object.entries(source)) {
    const existing = target[category] || []
    for (const item of items) {
      if (!existing.some((current) => current.keyword === item.keyword && current.snippet === item.snippet)) {
        existing.push(item)
      }
    }
    target[category] = existing
  }
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
      const platformPosts = new Map<string, Array<{ score: number; platform: string }>>()
      for (const post of session.findings?.posts || []) {
        const platform = String(post.platform || '').trim()
        if (post.risk_score == null) continue
        const score = Number(post.risk_score)
        if (!platform || !Number.isFinite(score)) continue
        const key = platform.toLowerCase()
        const current = platformPosts.get(key) || []
        current.push({ score, platform })
        platformPosts.set(key, current)
      }
      const platforms = session.platforms || []
      for (const platform of platforms) {
        const key = platform.toLowerCase()
        if (latest.has(key)) continue
        const posts = platformPosts.get(key) || []
        const sessionScore = session.risk_score == null ? Number.NaN : Number(session.risk_score)
        // Older multi-platform rows sometimes contain one overall score with no
        // platform-specific findings. Never present that combined value as if
        // it belonged to each platform.
        if (!posts.length && (platforms.length !== 1 || !Number.isFinite(sessionScore))) continue
        const score = posts.length ? posts.reduce((sum, post) => sum + post.score, 0) / posts.length : sessionScore
        latest.set(key, {
          platform,
          score,
          createdAt: session.created_at,
          posts: posts.length || session.findings?.posts?.length || 0,
          sessionId: session.id,
        })
      }
    }
    return [...latest.values()].sort((a, b) => a.platform.localeCompare(b.platform))
  }, [detail])

  const selectedStudent = students.find((student) => student.id === studentId)
  const combinedSignals = useMemo(() => {
    const signals: Record<string, SocioeconomicSignal[]> = {}
    for (const session of detail?.analysis_sessions || []) {
      mergeSignals(signals, session.findings?.result?.signals)
    }
    return signals
  }, [detail])
  const signalCount = Object.values(combinedSignals).reduce((sum, items) => sum + items.length, 0)
  const timeline = useMemo(() => (detail?.analysis_sessions || []).flatMap((session) => {
    const grouped = new Map<string, { platform: string; scores: number[] }>()
    for (const post of session.findings?.posts || []) {
      const platform = String(post.platform || '').trim()
      if (post.risk_score == null) continue
      const score = Number(post.risk_score)
      if (!platform || !Number.isFinite(score)) continue
      const key = platform.toLowerCase(); const current = grouped.get(key) || { platform, scores: [] }; current.scores.push(score); grouped.set(key, current)
    }
    const platforms = session.platforms || []
    const output = [...grouped.values()].map(item => ({ platform: item.platform, score: Math.max(0, Math.min(1, item.scores.reduce((sum, value) => sum + value, 0) / item.scores.length)), createdAt: session.created_at, sessionId: session.id }))
    if (!output.length && platforms.length === 1 && session.risk_score != null && Number.isFinite(Number(session.risk_score))) output.push({ platform: platforms[0], score: Math.max(0, Math.min(1, Number(session.risk_score))), createdAt: session.created_at, sessionId: session.id })
    return output
  }).sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()), [detail])
  const formatDate = (value: string) => {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString()
  }
  const auditExport = async (format: 'csv' | 'pdf') => {
    if (!studentId) return
    await api.post(`/counsellor/students/${studentId}/analysis-export-audit`, { format })
  }
  const exportCsv = async () => {
    try {
      await auditExport('csv')
      const rows = [['platform', 'signal_percent', 'items_reviewed', 'analysis_timestamp'], ...summaries.map(s => [s.platform, (s.score * 100).toFixed(1), String(s.posts), s.createdAt])]
      const csv = rows.map(row => row.map(value => `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\n')
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `mindguard-${studentId}-platform-report.csv`; anchor.click(); URL.revokeObjectURL(url)
    } catch (err) { setError(err instanceof Error ? err.message : 'Export audit failed; the report was not downloaded.') }
  }
  const printPdf = async () => { try { await auditExport('pdf'); window.print() } catch (err) { setError(err instanceof Error ? err.message : 'Export audit failed; the report was not printed.') } }

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
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-bold text-slate-900">Latest platform comparison</h2><p className="text-sm text-slate-500">Each bar is independent; MindGuard does not create a combined clinical score.</p></div><div className="flex gap-2 print:hidden"><button onClick={() => void exportCsv()} className="rounded-lg border px-3 py-2 text-sm font-semibold">Export CSV</button><button onClick={() => void printPdf()} className="rounded-lg border px-3 py-2 text-sm font-semibold">Print / save PDF</button></div></div>
            <Plot data={[{ type: 'bar', x: summaries.map(s => s.platform), y: summaries.map(s => Math.max(0, Math.min(1, s.score))), marker: { color: summaries.map(s => s.score >= .75 ? '#dc2626' : s.score >= .5 ? '#d97706' : '#059669') }, text: summaries.map(s => `${(s.score * 100).toFixed(0)}%`), textposition: 'outside' }]} layout={{ autosize: true, height: 340, margin: { l: 50, r: 20, t: 30, b: 50 }, yaxis: { range: [0, 1.1], tickformat: '.0%', title: { text: 'Platform signal' } }, paper_bgcolor: 'transparent', plot_bgcolor: '#fff' }} config={{ responsive: true, displaylogo: false, toImageButtonOptions: { filename: `mindguard-${studentId}-platform-comparison` } }} className="w-full" />
          </section>
          {timeline.length > 1 && <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="font-bold text-slate-900">Longitudinal platform trend</h2><p className="text-sm text-slate-500">Recorded sessions over time, separated by platform.</p><Plot data={[...new Set(timeline.map(v => v.platform))].map(platform => ({ type: 'scatter' as const, mode: 'lines+markers' as const, name: platform, x: timeline.filter(v => v.platform === platform).map(v => v.createdAt), y: timeline.filter(v => v.platform === platform).map(v => v.score) }))} layout={{ autosize: true, height: 350, margin: { l: 50, r: 20, t: 30, b: 60 }, yaxis: { range: [0, 1], tickformat: '.0%' }, paper_bgcolor: 'transparent', plot_bgcolor: '#fff', legend: { orientation: 'h' } }} config={{ responsive: true, displaylogo: false }} className="w-full" /></section>}
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
          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="border-b p-5"><h2 className="font-bold text-slate-900">Detailed authorized result table</h2></div><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-slate-600"><tr><th className="p-3">Platform</th><th className="p-3">Signal</th><th className="p-3">Items</th><th className="p-3">Timestamp</th></tr></thead><tbody>{summaries.map(s => <tr key={`table-${s.sessionId}-${s.platform}`} className="border-t"><td className="p-3 font-semibold capitalize">{s.platform}</td><td className="p-3">{(s.score * 100).toFixed(0)}%</td><td className="p-3">{s.posts}</td><td className="p-3">{formatDate(s.createdAt)}</td></tr>)}</tbody></table></div></section>
          {signalCount > 0 && <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="font-bold text-slate-900">Combined socio-economic context</h2>
            <p className="mt-1 text-sm text-slate-500">Interactive distribution across the student’s authorized platform results. Keyword matches provide context and are not proof of intent.</p>
            <div className="mt-4"><SocioEconomicPanel signals={combinedSignals} /></div>
          </section>}
          <p className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm leading-6 text-blue-900">Signals are platform-specific decision-support information, not diagnoses. They are not averaged into a single cross-platform score. Review the underlying session and discuss context with the student before deciding on follow-up.</p>
        </>}
      </>}
    </main>
  )
}

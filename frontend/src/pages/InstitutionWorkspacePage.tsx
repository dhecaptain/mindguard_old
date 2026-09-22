import { useEffect, useRef, useState } from 'react'
import { getInstitutionSetup, getInstitutionStaff, inviteInstitutionStaff, markInstitutionReady, commitRoster } from '../api/admin'
import type { InstitutionSetup, InstitutionStaff } from '../types'

const inputClass = 'w-full rounded-lg border border-[#dbe3ea] bg-white px-3 py-2 text-sm outline-none focus:border-[#0f766e]'

type RosterPreviewRow = {
  values: string[]
  name: string
  email: string
  isMinor: boolean
  parentEmail: string
  parentEmailIndex: number
}

type RosterPreview = { headers: string[]; rows: RosterPreviewRow[]; error?: string }

function parseCsvText(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = [], cell = '', quoted = false
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]
    if (char === '"' && quoted && text[i + 1] === '"') { cell += '"'; i += 1 }
    else if (char === '"') quoted = !quoted
    else if (char === ',' && !quoted) { row.push(cell.trim()); cell = '' }
    else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && text[i + 1] === '\n') i += 1
      row.push(cell.trim()); cell = ''
      if (row.some(Boolean)) rows.push(row)
      row = []
    } else cell += char
  }
  if (cell || row.length) { row.push(cell.trim()); if (row.some(Boolean)) rows.push(row) }
  return rows
}

function csvEscape(value: string) {
  return /[",\n\r]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value
}

function normalizedHeader(value: string) {
  return value.trim().replace(/^\ufeff/, '').toLowerCase().replaceAll(' ', '_')
}

function parseRosterDate(value: string) {
  const match = value.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/)
  if (!match) return value.match(/^\d{4}-\d{2}-\d{2}$/) ? new Date(`${value}T00:00:00`) : null
  const first = Number(match[1]), second = Number(match[2]), year = Number(match[3])
  const month = first > 12 ? second : first
  const day = first > 12 ? first : second
  return new Date(year, month - 1, day)
}

function isMinorFromRow(dateOfBirth: string, override: string) {
  const normalized = override.trim().toLowerCase()
  if (['true', '1', 'yes', 'minor'].includes(normalized)) return true
  if (['false', '0', 'no', 'adult'].includes(normalized)) return false
  const dob = parseRosterDate(dateOfBirth)
  if (!dob || Number.isNaN(dob.getTime())) return false
  const today = new Date()
  let age = today.getFullYear() - dob.getFullYear()
  if (today < new Date(today.getFullYear(), dob.getMonth(), dob.getDate())) age -= 1
  return age < 18
}

async function buildRosterPreview(file: File): Promise<RosterPreview> {
  const text = await file.text()
  const parsed = parseCsvText(text)
  if (parsed.length < 2) return { headers: [], rows: [], error: 'The CSV must contain a header row and at least one student.' }
  const headers = parsed[0]
  const normalized = headers.map(normalizedHeader)
  const indexOf = (...names: string[]) => names.map((name) => normalized.indexOf(name)).find((index) => index >= 0) ?? -1
  const firstNameIndex = indexOf('student_first_name', 'first_name', 'firstname')
  const emailIndex = indexOf('student_email', 'email', 'studentemail')
  const dobIndex = indexOf('date_of_birth', 'dob', 'dateofbirth')
  const parentEmailIndex = indexOf('parent_email', 'parentemail')
  const overrideIndex = indexOf('is_minor')
  if (indexOf('student_id', 'id') < 0 || firstNameIndex < 0 || emailIndex < 0 || dobIndex < 0) {
    return { headers, rows: [], error: 'Required columns are student_id, student_first_name, student_email, and date_of_birth.' }
  }
  const lastNameIndex = indexOf('last_name', 'lastname')
  const outputHeaders = parentEmailIndex >= 0 ? headers : [...headers, 'parent_email']
  const outputParentEmailIndex = parentEmailIndex >= 0 ? parentEmailIndex : outputHeaders.length - 1
  return {
    headers: outputHeaders,
    rows: parsed.slice(1).map((sourceValues) => {
      const values = parentEmailIndex >= 0 ? sourceValues : [...sourceValues, '']
      const firstName = values[firstNameIndex] || ''
      const lastName = lastNameIndex >= 0 ? values[lastNameIndex] || '' : ''
      return { values, name: `${firstName} ${lastName}`.trim(), email: values[emailIndex] || '', isMinor: isMinorFromRow(values[dobIndex] || '', overrideIndex >= 0 ? values[overrideIndex] || '' : ''), parentEmail: values[outputParentEmailIndex] || '', parentEmailIndex: outputParentEmailIndex }
    }),
  }
}

function RosterPreviewPanel({ preview, onChange, onCancel, onConfirm, busy }: { preview: RosterPreview; onChange: (row: number, value: string) => void; onCancel: () => void; onConfirm: () => void; busy: boolean }) {
  const missingParents = preview.rows.filter((row) => row.isMinor && !row.parentEmail.trim()).length
  return <div className="mt-4 rounded-xl border border-[#99f6e4] bg-[#f0fdfa] p-4"><div className="flex items-start justify-between gap-3"><div><h3 className="font-bold text-slate-800">Review roster before sending</h3><p className="mt-1 text-xs text-slate-600">{preview.rows.length} student(s) detected · {preview.rows.filter((row) => row.isMinor).length} minor(s) · {preview.rows.filter((row) => !row.isMinor).length} adult(s)</p></div><button type="button" onClick={onCancel} className="text-xs font-semibold text-slate-500">Cancel</button></div>{preview.error ? <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{preview.error}</p> : <><div className="mt-3 max-h-[240px] space-y-2 overflow-y-auto">{preview.rows.map((row, index) => <div key={`${row.email}-${index}`} className="rounded-lg border border-white bg-white p-3 text-xs"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold text-slate-700">Row {index + 2}: {row.name || 'Unnamed student'} · {row.email || 'No student email'}</span><span className={`rounded-full px-2 py-1 font-bold ${row.isMinor ? 'bg-amber-100 text-amber-800' : 'bg-blue-100 text-blue-800'}`}>{row.isMinor ? 'Minor — parent consent required' : '18+ — adult consent'}</span></div>{row.isMinor && <div className="mt-2 flex items-center gap-2"><label className="w-[105px] shrink-0 text-slate-600">Parent email</label><input type="email" value={row.parentEmail} onChange={(event) => onChange(index, event.target.value)} placeholder="parent@example.org (optional for now)" className="min-w-0 flex-1 rounded-md border border-slate-200 px-2 py-1.5 outline-none focus:border-[#0f766e]" /></div>}</div>)}</div>{missingParents > 0 && <p className="mt-3 rounded-lg bg-amber-100 px-3 py-2 text-xs text-amber-900">{missingParents} minor(s) will be imported now but will wait for parent details and consent. Adults will continue immediately.</p>}<button type="button" onClick={onConfirm} disabled={busy || preview.rows.length === 0} className="mt-3 w-full rounded-lg bg-[#0f766e] px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">{busy ? 'Uploading…' : `Upload ${preview.rows.length} student(s) and send available consent`}</button></>}</div>
}

const rosterHeaders = [
  'student_id', 'student_first_name', 'student_email', 'date_of_birth',
  'last_name', 'grade_level', 'parent_first_name', 'parent_email', 'is_minor', 'notes',
]

function downloadRosterTemplate() {
  const sample = [
    'STU-001,Amara,amara@example.org,2011-04-18,Njeri,Year 8,Grace,grace.parent@example.org,,',
    'STU-002,Daniel,daniel@example.org,2004-09-02,Otieno,Year 13,,,,',
  ]
  const csv = [rosterHeaders.join(','), ...sample].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'mindguard-student-roster-template.csv'
  link.click()
  URL.revokeObjectURL(url)
}

export default function InstitutionWorkspacePage() {
  const [setup, setSetup] = useState<InstitutionSetup | null>(null)
  const [staff, setStaff] = useState<InstitutionStaff[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadFileName, setUploadFileName] = useState('')
  const [uploadResult, setUploadResult] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [uploadErrors, setUploadErrors] = useState<Array<{ row_number?: number; error: string }>>([])
  const [rosterPreview, setRosterPreview] = useState<RosterPreview | null>(null)
  const uploadProgressTimer = useRef<number | null>(null)
  const [staffForm, setStaffForm] = useState({ name: '', email: '', role_type: 'counsellor' as 'school_admin' | 'counsellor' })

  const load = async () => {
    try {
      const [nextSetup, nextStaff] = await Promise.all([getInstitutionSetup(), getInstitutionStaff()])
      setSetup(nextSetup); setStaff(nextStaff); setError('')
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to load institution workspace') }
  }
  useEffect(() => { load() }, [])
  useEffect(() => () => {
    if (uploadProgressTimer.current) window.clearInterval(uploadProgressTimer.current)
  }, [])

  const inviteStaff = async () => {
    setBusy(true); setError(''); setMessage('')
    try {
      await inviteInstitutionStaff(staffForm)
      setStaffForm({ name: '', email: '', role_type: staffForm.role_type })
      setMessage('Invitation sent. The account will become active after the recipient sets a password.')
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to send invitation') }
    finally { setBusy(false) }
  }

  const uploadRoster = async (file: File) => {
    if (!setup || uploading) return
    setBusy(true); setError(''); setMessage('')
    setUploading(true); setUploadProgress(8); setUploadFileName(file.name); setUploadResult(null); setUploadErrors([])
    uploadProgressTimer.current = window.setInterval(() => {
      setUploadProgress((progress) => Math.min(progress + Math.max(2, Math.round((92 - progress) / 4)), 92))
    }, 450)
    try {
      const result = await commitRoster(file, setup.institution.id)
      const rosterIssue = result.roster.parse_error || (result.roster.errors.length ? `${result.roster.errors.length} row error(s)` : '')
      const dispatchIssue = result.dispatch.routing_errors?.length ? ` ${result.dispatch.routing_errors.length} consent issue(s) need attention.` : ''
      const text = `Roster processed: ${result.roster.created} created, ${result.roster.updated} updated, ${result.dispatch.dispatched} consent requests sent.${rosterIssue ? ` ${rosterIssue}.` : ''}${dispatchIssue}`
      setMessage(text); setUploadProgress(100); setUploadResult({ type: 'success', text }); setUploadErrors(result.roster.errors)
      await load()
    } catch (err) {
      const text = err instanceof Error ? err.message : 'Unable to process roster'
      setError(text); setUploadResult({ type: 'error', text })
    } finally {
      if (uploadProgressTimer.current) window.clearInterval(uploadProgressTimer.current)
      uploadProgressTimer.current = null
      setBusy(false); setUploading(false)
    }
  }

  const prepareRoster = async (file: File) => {
    if (busy) return
    setBusy(true); setError(''); setMessage(''); setUploadResult(null)
    try { setRosterPreview(await buildRosterPreview(file)) }
    catch { setRosterPreview({ headers: [], rows: [], error: 'Unable to read this CSV. Please save it as UTF-8 CSV and try again.' }) }
    finally { setBusy(false) }
  }

  const confirmRoster = () => {
    if (!rosterPreview) return
    const csv = [rosterPreview.headers, ...rosterPreview.rows.map((row) => row.values)].map((row) => row.map(csvEscape).join(',')).join('\n')
    setRosterPreview(null)
    uploadRoster(new File([csv], 'student-roster.csv', { type: 'text/csv' }))
  }

  const ready = async () => {
    setBusy(true); setError('')
    try { await markInstitutionReady(); setMessage('Institution marked ready.'); await load() }
    catch (err) { setError(err instanceof Error ? err.message : 'Complete the setup checklist first') }
    finally { setBusy(false) }
  }

  if (error && !setup) return <div className="p-8 text-red-700">{error}</div>
  if (!setup) return <div className="p-8 text-slate-500">Loading institution workspace…</div>

  return (
    <div className="mx-auto max-w-[1200px] p-6 md:p-9">
      <div className="mb-7 flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.14em] text-[#0f766e]">Institution workspace</p><h1 className="mt-1 text-3xl font-bold text-[#172033]">{setup.institution.name}</h1><p className="mt-1 text-sm text-slate-500">{setup.institution.type} · {setup.institution.status || 'PROVISIONING'}</p></div><button onClick={ready} disabled={busy || setup.next_action !== 'Institution is ready'} className="rounded-lg bg-[#0f766e] px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">Mark ready</button></div>
      {(error || message) && <div className={`mb-5 rounded-lg border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error || message}</div>}
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">{Object.entries(setup.counts).map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><div className="text-2xl font-bold text-[#172033]">{value}</div><div className="mt-1 text-xs capitalize text-slate-500">{label.replaceAll('_', ' ')}</div></div>)}</div>
      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="font-bold text-[#172033]">Setup checklist</h2><p className="mt-1 text-sm text-slate-500">Next action: {setup.next_action}</p><div className="mt-4 space-y-3">{setup.checks.map((check) => <div key={check.key} className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-3 text-sm"><span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${check.complete ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{check.complete ? '✓' : '!'}</span><span className={check.complete ? 'text-slate-600' : 'font-semibold text-slate-800'}>{check.label}</span></div>)}</div><div className="mt-6 rounded-xl border border-[#dbeafe] bg-[#f8fbff] p-4 text-sm text-slate-600"><div className="flex items-start justify-between gap-3"><div><h3 className="font-bold text-slate-800">Prepare the student CSV</h3><p className="mt-1 text-xs leading-5">Use one student per row. Required columns are <strong>student_id</strong>, <strong>student_first_name</strong>, <strong>student_email</strong>, and <strong>date_of_birth</strong>.</p></div><button type="button" onClick={downloadRosterTemplate} className="shrink-0 rounded-lg border border-[#0f766e] px-3 py-2 text-xs font-semibold text-[#0f766e] hover:bg-[#f0fdfa]">Download template</button></div><p className="mt-3 text-xs leading-5"><strong>Optional:</strong> last_name, grade_level, parent_first_name, parent_email, is_minor, notes.</p><p className="mt-2 text-xs leading-5 text-slate-500">Dates: YYYY-MM-DD, DD/MM/YYYY, or MM/DD/YYYY. For students under 18, parent_email is required. Leave parent fields blank for adults.</p></div><label className={`mt-4 block rounded-lg border border-dashed px-4 py-3 text-center text-sm font-semibold ${uploading ? 'cursor-wait border-slate-300 bg-slate-50 text-slate-500' : 'cursor-pointer border-[#0f766e] text-[#0f766e]'}`}>{uploading ? 'Uploading roster… please wait' : 'Choose CSV to review'}<input type="file" accept=".csv,text/csv" className="hidden" disabled={busy || uploading} onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ''; if (file) prepareRoster(file) }} /></label>{rosterPreview && <RosterPreviewPanel preview={rosterPreview} busy={busy || uploading} onCancel={() => setRosterPreview(null)} onChange={(rowIndex, value) => setRosterPreview((current) => current ? { ...current, rows: current.rows.map((row, index) => index === rowIndex ? { ...row, parentEmail: value, values: row.values.map((cell, cellIndex) => cellIndex === row.parentEmailIndex ? value : cell) } : row) } : current)} onConfirm={confirmRoster} />}{(uploading || uploadResult) && <div className={`mt-3 rounded-lg border p-3 text-xs ${uploadResult?.type === 'error' ? 'border-red-200 bg-red-50 text-red-700' : uploadResult?.type === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-[#bfdbfe] bg-[#f8fbff] text-slate-600'}`}><div className="flex items-center justify-between gap-3"><span className="truncate">{uploading ? `Processing ${uploadFileName}` : uploadResult?.text}</span>{uploading && <span className="shrink-0 font-semibold">{uploadProgress}%</span>}</div>{uploading && <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-[#0f766e] transition-[width] duration-300" style={{ width: `${uploadProgress}%` }} /></div>}</div>}{uploadErrors.length > 0 && <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"><p className="font-semibold">Rows needing attention</p><ul className="mt-2 list-disc space-y-1 pl-4">{uploadErrors.map((item, index) => <li key={`${item.row_number || 'row'}-${index}`}>Row {item.row_number || 'unknown'}: {item.error}</li>)}</ul></div>}</section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="font-bold text-[#172033]">Invite institution staff</h2><p className="mt-1 text-sm text-slate-500">Invite school administrators and counsellors. They activate through the secure email link.</p><div className="mt-4 space-y-3"><input className={inputClass} placeholder="Full name" value={staffForm.name} onChange={(e) => setStaffForm({ ...staffForm, name: e.target.value })} /><input className={inputClass} type="email" placeholder="Email address" value={staffForm.email} onChange={(e) => setStaffForm({ ...staffForm, email: e.target.value })} /><select className={inputClass} value={staffForm.role_type} onChange={(e) => setStaffForm({ ...staffForm, role_type: e.target.value as 'school_admin' | 'counsellor' })}><option value="school_admin">School administrator</option><option value="counsellor">Counsellor</option></select><button onClick={inviteStaff} disabled={busy || !staffForm.name || !staffForm.email} className="w-full rounded-lg bg-[#0f766e] px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{busy ? 'Working…' : 'Send invitation'}</button></div><div className="mt-6 space-y-2">{staff.map((member) => <div key={member.id} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2 text-sm"><div><div className="font-semibold text-slate-700">{member.name}</div><div className="text-xs text-slate-500">{member.email} · {member.role_type.replace('_', ' ')}</div></div><span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase ${member.status === 'approved' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{member.invitation_pending ? 'invited' : member.status}</span></div>)}</div></section>
      </div>
    </div>
  )
}

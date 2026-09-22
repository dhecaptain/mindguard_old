import { useEffect, useState } from 'react'
import { getInstitutionSetup, getInstitutionStaff, inviteInstitutionStaff, markInstitutionReady, commitRoster } from '../api/admin'
import type { InstitutionSetup, InstitutionStaff } from '../types'

const inputClass = 'w-full rounded-lg border border-[#dbe3ea] bg-white px-3 py-2 text-sm outline-none focus:border-[#0f766e]'

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
  const [staffForm, setStaffForm] = useState({ name: '', email: '', role_type: 'counsellor' as 'school_admin' | 'counsellor' })

  const load = async () => {
    try {
      const [nextSetup, nextStaff] = await Promise.all([getInstitutionSetup(), getInstitutionStaff()])
      setSetup(nextSetup); setStaff(nextStaff); setError('')
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to load institution workspace') }
  }
  useEffect(() => { load() }, [])

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
    if (!setup) return
    setBusy(true); setError(''); setMessage('')
    try {
      const result = await commitRoster(file, setup.institution.id)
      const rosterIssue = result.roster.parse_error || (result.roster.errors.length ? `${result.roster.errors.length} row error(s)` : '')
      const dispatchIssue = result.dispatch.routing_errors?.length ? ` ${result.dispatch.routing_errors.length} consent issue(s) need attention.` : ''
      setMessage(`Roster processed: ${result.roster.created} created, ${result.roster.updated} updated, ${result.dispatch.dispatched} consent requests sent.${rosterIssue ? ` ${rosterIssue}.` : ''}${dispatchIssue}`)
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to process roster') }
    finally { setBusy(false) }
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
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="font-bold text-[#172033]">Setup checklist</h2><p className="mt-1 text-sm text-slate-500">Next action: {setup.next_action}</p><div className="mt-4 space-y-3">{setup.checks.map((check) => <div key={check.key} className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-3 text-sm"><span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${check.complete ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{check.complete ? '✓' : '!'}</span><span className={check.complete ? 'text-slate-600' : 'font-semibold text-slate-800'}>{check.label}</span></div>)}</div><div className="mt-6 rounded-xl border border-[#dbeafe] bg-[#f8fbff] p-4 text-sm text-slate-600"><div className="flex items-start justify-between gap-3"><div><h3 className="font-bold text-slate-800">Prepare the student CSV</h3><p className="mt-1 text-xs leading-5">Use one student per row. Required columns are <strong>student_id</strong>, <strong>student_first_name</strong>, <strong>student_email</strong>, and <strong>date_of_birth</strong>.</p></div><button type="button" onClick={downloadRosterTemplate} className="shrink-0 rounded-lg border border-[#0f766e] px-3 py-2 text-xs font-semibold text-[#0f766e] hover:bg-[#f0fdfa]">Download template</button></div><p className="mt-3 text-xs leading-5"><strong>Optional:</strong> last_name, grade_level, parent_first_name, parent_email, is_minor, notes.</p><p className="mt-2 text-xs leading-5 text-slate-500">Dates: YYYY-MM-DD, DD/MM/YYYY, or MM/DD/YYYY. For students under 18, parent_email is required. Leave parent fields blank for adults.</p></div><label className="mt-4 block cursor-pointer rounded-lg border border-dashed border-[#0f766e] px-4 py-3 text-center text-sm font-semibold text-[#0f766e]">Upload CSV roster<input type="file" accept=".csv,text/csv" className="hidden" disabled={busy} onChange={(e) => e.target.files?.[0] && uploadRoster(e.target.files[0])} /></label></section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="font-bold text-[#172033]">Invite institution staff</h2><p className="mt-1 text-sm text-slate-500">Invite school administrators and counsellors. They activate through the secure email link.</p><div className="mt-4 space-y-3"><input className={inputClass} placeholder="Full name" value={staffForm.name} onChange={(e) => setStaffForm({ ...staffForm, name: e.target.value })} /><input className={inputClass} type="email" placeholder="Email address" value={staffForm.email} onChange={(e) => setStaffForm({ ...staffForm, email: e.target.value })} /><select className={inputClass} value={staffForm.role_type} onChange={(e) => setStaffForm({ ...staffForm, role_type: e.target.value as 'school_admin' | 'counsellor' })}><option value="school_admin">School administrator</option><option value="counsellor">Counsellor</option></select><button onClick={inviteStaff} disabled={busy || !staffForm.name || !staffForm.email} className="w-full rounded-lg bg-[#0f766e] px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{busy ? 'Working…' : 'Send invitation'}</button></div><div className="mt-6 space-y-2">{staff.map((member) => <div key={member.id} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2 text-sm"><div><div className="font-semibold text-slate-700">{member.name}</div><div className="text-xs text-slate-500">{member.email} · {member.role_type.replace('_', ' ')}</div></div><span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase ${member.status === 'approved' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{member.invitation_pending ? 'invited' : member.status}</span></div>)}</div></section>
      </div>
    </div>
  )
}

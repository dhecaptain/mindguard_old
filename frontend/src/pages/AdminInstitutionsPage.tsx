import { useEffect, useState } from 'react'
import { findRosterConflict, getInstitutions, inviteInstitutionStaff, purgeRosterConflict, updateInstitution, type RosterConflict } from '../api/admin'
import type { Institution } from '../types'

function RosterConflictResolver() {
  const [studentId, setStudentId] = useState('')
  const [conflict, setConflict] = useState<RosterConflict | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const find = async () => {
    if (!studentId.trim()) return
    setBusy(true); setError(''); setConflict(null)
    try { setConflict(await findRosterConflict(studentId.trim())) }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to find roster record') }
    finally { setBusy(false) }
  }
  const purge = async () => {
    if (!conflict || !window.confirm(`Remove the roster record for ${conflict.student_id}? The linked login account will be preserved.`)) return
    setBusy(true); setError('')
    try { await purgeRosterConflict(conflict.student_id); setConflict(null); setStudentId('') }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to remove roster record') }
    finally { setBusy(false) }
  }

  return <section className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 p-5"><h2 className="font-bold text-slate-800">Resolve roster ID conflict</h2><p className="mt-1 text-sm text-slate-600">For test data or an incorrectly imported student, find the blocking roster ID and remove only that roster record. The login account is preserved.</p><div className="mt-4 flex flex-col gap-2 sm:flex-row"><input value={studentId} onChange={(e) => setStudentId(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && find()} placeholder="Student ID, e.g. STU001" className="flex-1 rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm" /><button onClick={find} disabled={busy || !studentId.trim()} className="rounded-lg border border-amber-500 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">{busy ? 'Checking…' : 'Find record'}</button></div>{error && <p className="mt-3 text-sm text-red-700">{error}</p>}{conflict && <div className="mt-4 rounded-lg border border-amber-200 bg-white p-4 text-sm"><p><strong>{conflict.name}</strong> · {conflict.email}</p><p className="mt-1 text-slate-600">Currently in: {conflict.institution.name}</p><p className="mt-1 text-xs text-slate-500">Removing this frees {conflict.student_id} for re-import. {conflict.has_linked_account ? 'Its linked login account will remain.' : 'No linked login account exists.'}</p><button onClick={purge} disabled={busy} className="mt-3 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Remove roster record</button></div>}</section>
}

export default function AdminInstitutionsPage() {
  const [institutions, setInstitutions] = useState<Institution[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [invite, setInvite] = useState<Record<string, { name: string; email: string }>>({})
  const load = () => getInstitutions().then(setInstitutions).catch((e) => setError(e.message || 'Unable to load institutions'))
  useEffect(() => { load() }, [])
  const changeStatus = async (id: string, status: string) => { try { const updated = await updateInstitution(id, { status }); setInstitutions((items) => items.map((item) => item.id === id ? updated : item)) } catch (e) { setError(e instanceof Error ? e.message : 'Unable to update institution') } }
  const inviteAdmin = async (institutionId: string) => {
    const form = invite[institutionId]
    if (!form?.name || !form.email) return
    setError('')
    try {
      const result = await inviteInstitutionStaff({ ...form, role_type: 'school_admin', institution_id: institutionId })
      setInvite((items) => ({ ...items, [institutionId]: { name: '', email: '' } }))
      await load()
      if (result.email_sent) setMessage(`School administrator invitation email queued for ${form.email}.`)
      else setError(`School admin account created, but email delivery was not confirmed${result.email_error ? `: ${result.email_error}` : '; check delivery and resend the invitation.'}`)
    }
    catch (e) { setError(e instanceof Error ? e.message : 'Unable to invite school administrator') }
  }
  return <div className="mx-auto max-w-[1100px] p-6 md:p-9"><div className="mb-6 flex items-start justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-widest text-[#0f766e]">Global administration</p><h1 className="mt-1 text-2xl font-bold text-[#172033]">Institutions</h1><p className="mt-1 text-sm text-[#64748b]">Provision workspaces, invite their first school administrator, and control lifecycle.</p></div><button onClick={load} className="rounded-lg border border-[#cbd5e1] px-3 py-2 text-sm">Refresh</button></div><RosterConflictResolver />{(error || message) && <div className={`mb-4 rounded-lg border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error || message}</div>}<div className="grid gap-4">{institutions.map((institution) => { const form = invite[institution.id] || { name: '', email: '' }; return <article key={institution.id} className="rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-bold text-[#172033]">{institution.name}</h2><p className="mt-1 text-xs text-[#64748b]">{institution.type || 'other'} · {institution.status || 'PROVISIONING'}</p></div><span className="rounded-full bg-[#f1f5f9] px-3 py-1 text-xs font-bold uppercase text-[#475569]">{institution.status || 'PROVISIONING'}</span></div><div className="mt-5 flex flex-wrap gap-2"><button onClick={() => changeStatus(institution.id, 'ACTIVE')} className="rounded-lg bg-[#0f766e] px-3 py-2 text-xs font-semibold text-white">Activate</button><button onClick={() => changeStatus(institution.id, 'SUSPENDED')} className="rounded-lg border border-amber-300 px-3 py-2 text-xs font-semibold text-amber-700">Suspend</button><button onClick={() => changeStatus(institution.id, 'ARCHIVED')} className="rounded-lg border border-red-200 px-3 py-2 text-xs font-semibold text-red-700">Archive</button></div><div className="mt-5 grid gap-2 border-t border-slate-100 pt-4 sm:grid-cols-[1fr_1fr_auto]"><input className="rounded-lg border border-slate-200 px-3 py-2 text-sm" placeholder="First school admin name" value={form.name} onChange={(e) => setInvite((items) => ({ ...items, [institution.id]: { ...form, name: e.target.value } }))} /><input className="rounded-lg border border-slate-200 px-3 py-2 text-sm" type="email" placeholder="School admin email" value={form.email} onChange={(e) => setInvite((items) => ({ ...items, [institution.id]: { ...form, email: e.target.value } }))} /><button onClick={() => inviteAdmin(institution.id)} disabled={!form.name || !form.email} className="rounded-lg bg-slate-800 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">Invite school admin</button></div></article> })}{!institutions.length && <div className="rounded-2xl border border-dashed border-[#cbd5e1] bg-white p-10 text-center text-sm text-[#64748b]">No institutions provisioned yet.</div>}</div></div>
}

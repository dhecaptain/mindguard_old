import { useEffect, useState } from 'react'
import { createInstitution, findRosterConflict, getInstitutions, inviteInstitutionStaff, purgeRosterConflict, updateInstitution, type RosterConflict } from '../api/admin'
import type { Institution } from '../types'

const inputClass = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-100'

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
  return <section className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 p-5"><h2 className="font-bold text-slate-800">Resolve roster ID conflict</h2><p className="mt-1 text-sm text-slate-600">For test data or an incorrectly imported student, find the blocking roster ID and remove only that roster record. The login account is preserved.</p><div className="mt-4 flex flex-col gap-2 sm:flex-row"><input value={studentId} onChange={(e) => setStudentId(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void find()} placeholder="Student ID, e.g. STU001" className={`flex-1 ${inputClass}`} /><button onClick={() => void find()} disabled={busy || !studentId.trim()} className="rounded-lg border border-amber-500 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">{busy ? 'Checking…' : 'Find record'}</button></div>{error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}{conflict && <div className="mt-4 rounded-lg border border-amber-200 bg-white p-4 text-sm"><p><strong>{conflict.name}</strong> · {conflict.email}</p><p className="mt-1 text-slate-600">Currently in: {conflict.institution.name}</p><p className="mt-1 text-xs text-slate-500">Removing this frees {conflict.student_id} for re-import. {conflict.has_linked_account ? 'Its linked login account will remain.' : 'No linked login account exists.'}</p><button onClick={() => void purge()} disabled={busy} className="mt-3 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Remove roster record</button></div>}</section>
}

export default function AdminInstitutionsPage() {
  const [institutions, setInstitutions] = useState<Institution[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [invite, setInvite] = useState<Record<string, { name: string; email: string }>>({})
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newInstitution, setNewInstitution] = useState({ name: '', type: 'school', adminName: '', adminEmail: '' })
  const load = () => getInstitutions().then(setInstitutions).catch((e) => setError(e.message || 'Unable to load institutions'))
  useEffect(() => { void load() }, [])

  const changeStatus = async (institution: Institution, status: string) => {
    const action = status === 'ARCHIVED' ? 'Archive' : status === 'SUSPENDED' ? 'Suspend' : 'Activate'
    if (!window.confirm(`${action} ${institution.name}? ${status === 'ARCHIVED' ? 'This is a lifecycle action and does not delete retained records.' : status === 'SUSPENDED' ? 'Institution operations will be suspended.' : 'This activates the workspace; setup readiness is tracked separately.'}`)) return
    setError(''); setMessage('')
    try {
      const updated = await updateInstitution(institution.id, { status })
      setInstitutions((items) => items.map((item) => item.id === institution.id ? updated : item))
      setMessage(`${institution.name} is now ${status.toLowerCase()}.`)
    } catch (e) { setError(e instanceof Error ? e.message : `Unable to ${action.toLowerCase()} institution`) }
  }

  const inviteAdmin = async (institutionId: string) => {
    const form = invite[institutionId]
    if (!form?.name.trim() || !form.email.trim()) return
    setError(''); setMessage('')
    try {
      const result = await inviteInstitutionStaff({ name: form.name.trim(), email: form.email.trim(), role_type: 'school_admin', institution_id: institutionId })
      setInvite((items) => ({ ...items, [institutionId]: { name: '', email: '' } }))
      await load()
      if (result.email_sent) setMessage(`School administrator invitation queued for ${form.email}.`)
      else setError(`The admin account was provisioned, but email delivery was not confirmed${result.email_error ? `: ${result.email_error}` : '. Resend the invitation after checking delivery.'}`)
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to invite school administrator') }
  }

  const create = async () => {
    const form = newInstitution
    if (!form.name.trim() || !form.adminName.trim() || !form.adminEmail.trim()) {
      setError('Enter the institution name and first school administrator details.')
      return
    }
    setCreating(true); setError(''); setMessage('')
    let created: Institution | null = null
    try {
      created = await createInstitution(form.name.trim(), form.type)
      setInstitutions((items) => [...items, created as Institution].sort((a, b) => a.name.localeCompare(b.name)))
      try {
        const result = await inviteInstitutionStaff({ name: form.adminName.trim(), email: form.adminEmail.trim(), role_type: 'school_admin', institution_id: created.id })
        setShowCreate(false)
        setNewInstitution({ name: '', type: 'school', adminName: '', adminEmail: '' })
        if (result.email_sent) {
        setMessage(`${created.name} was created and the first school administrator invitation was queued for ${form.adminEmail}. The workspace remains in provisioning until its setup checklist is complete.`)
        } else {
          setError(`${created.name} was created and the school-admin account was provisioned, but email delivery was not confirmed${result.email_error ? `: ${result.email_error}` : '. Follow up with the administrator before proceeding.'}`)
        }
      } catch (inviteError) {
        setError(inviteError instanceof Error ? inviteError.message : 'Institution created but the first admin could not be invited. Use the invitation form on its institution card to retry.')
        await load()
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to create institution') }
    finally { setCreating(false) }
  }

  return <main className="mx-auto max-w-[1100px] p-6 md:p-9">
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-widest text-teal-700">Global administration</p><h1 className="mt-1 text-2xl font-bold text-slate-800">Institutions</h1><p className="mt-1 text-sm text-slate-600">Create an institution, provision its first school administrator, and oversee its lifecycle.</p></div><button onClick={() => { setShowCreate((open) => !open); setError('') }} className="rounded-lg bg-teal-800 px-4 py-2.5 text-sm font-semibold text-white hover:bg-teal-900">{showCreate ? 'Close setup' : 'Set up institution'}</button></header>
    {(error || message) && <div role={error ? 'alert' : 'status'} className={`mb-4 rounded-lg border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}>{error || message}</div>}
    {showCreate && <section className="mb-6 rounded-2xl border border-teal-200 bg-teal-50/60 p-5"><h2 className="font-bold text-slate-800">New institution setup</h2><p className="mt-1 text-sm text-slate-600">We’ll create the workspace in provisioning and send the first school admin a secure invitation. This does not mark the institution Ready.</p><div className="mt-4 grid gap-3 sm:grid-cols-2"><label className="text-xs font-semibold text-slate-700">Institution name<input className={`${inputClass} mt-1`} value={newInstitution.name} onChange={(e) => setNewInstitution({ ...newInstitution, name: e.target.value })} placeholder="e.g. Northview School" /></label><label className="text-xs font-semibold text-slate-700">Institution type<select className={`${inputClass} mt-1`} value={newInstitution.type} onChange={(e) => setNewInstitution({ ...newInstitution, type: e.target.value })}><option value="school">School</option><option value="university">University</option><option value="college">College</option><option value="other">Other</option></select></label><label className="text-xs font-semibold text-slate-700">First school administrator<input className={`${inputClass} mt-1`} value={newInstitution.adminName} onChange={(e) => setNewInstitution({ ...newInstitution, adminName: e.target.value })} placeholder="Full name" /></label><label className="text-xs font-semibold text-slate-700">Administrator email<input className={`${inputClass} mt-1`} type="email" value={newInstitution.adminEmail} onChange={(e) => setNewInstitution({ ...newInstitution, adminEmail: e.target.value })} placeholder="name@school.org" /></label></div><div className="mt-4 flex justify-end"><button onClick={() => void create()} disabled={creating} className="rounded-lg bg-teal-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{creating ? 'Creating and inviting…' : 'Create institution & invite admin'}</button></div></section>}
    <RosterConflictResolver />
    <div className="grid gap-4">{institutions.map((institution) => { const form = invite[institution.id] || { name: '', email: '' }; const status = institution.status || 'PROVISIONING'; return <article key={institution.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-bold text-slate-800">{institution.name}</h2><p className="mt-1 text-xs capitalize text-slate-500">{institution.type || 'other'} · Workspace status: {status.toLowerCase()}</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold uppercase text-slate-600">{status}</span></div><p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">Workspace lifecycle and setup readiness are separate. Use the school-admin checklist to complete onboarding and mark the institution Ready when eligible.</p><div className="mt-4 flex flex-wrap gap-2">{status !== 'ACTIVE' && status !== 'READY' && <button onClick={() => void changeStatus(institution, 'ACTIVE')} className="rounded-lg bg-teal-800 px-3 py-2 text-xs font-semibold text-white">Activate workspace</button>}{status !== 'SUSPENDED' && <button onClick={() => void changeStatus(institution, 'SUSPENDED')} className="rounded-lg border border-amber-300 px-3 py-2 text-xs font-semibold text-amber-800">Suspend</button>}{status === 'SUSPENDED' && <button onClick={() => void changeStatus(institution, 'ACTIVE')} className="rounded-lg bg-teal-800 px-3 py-2 text-xs font-semibold text-white">Reactivate workspace</button>}{status !== 'ARCHIVED' && <button onClick={() => void changeStatus(institution, 'ARCHIVED')} className="rounded-lg border border-red-200 px-3 py-2 text-xs font-semibold text-red-700">Archive institution</button>}</div><div className="mt-5 grid gap-2 border-t border-slate-100 pt-4 sm:grid-cols-[1fr_1fr_auto]"><input className={inputClass} placeholder="School administrator name" value={form.name} onChange={(e) => setInvite((items) => ({ ...items, [institution.id]: { ...form, name: e.target.value } }))} /><input className={inputClass} type="email" placeholder="School administrator email" value={form.email} onChange={(e) => setInvite((items) => ({ ...items, [institution.id]: { ...form, email: e.target.value } }))} /><button onClick={() => void inviteAdmin(institution.id)} disabled={!form.name.trim() || !form.email.trim()} className="rounded-lg bg-slate-800 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">Invite school admin</button></div></article>})}{!institutions.length && <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-600">No institutions provisioned yet. Start with “Set up institution”.</div>}</div>
  </main>
}

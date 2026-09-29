import { useCallback, useEffect, useState } from 'react'
import api from '../api/client'
import { useAuthStore } from '../store'
import { useUiStore } from '../store/uiStore'
import Plot from '../lib/plotly'
import { setToken } from '../lib/tokenStorage'
import { acceptTerms } from '../api/auth'

type Report = { suppressed: boolean; minimum_cohort?: number; message?: string; cohort_size?: string; checkins?: string; averages?: Record<string, number | null>; scope?: string }
type Provider = { id: string; name: string; title?: string; status?: string }

const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm'
const button = 'rounded-xl bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-50'

export function WorkplaceTermsPage() {
  const user = useAuthStore(s => s.user)
  const setTermsAccepted = useAuthStore(s => s.setTermsAccepted)
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const role = user?.role_type
  const employer = role === 'company_admin'
  const provider = role === 'workplace_provider'
  const clauses = employer ? [
    'Participation is voluntary; do not pressure employees to enroll or disclose participation.',
    'Do not seek to identify participants or request individual check-ins, referrals, appointments, or provider records.',
    'Use aggregate reporting only for supportive programme planning, never for employment decisions.',
    'Do not treat MindGuard as emergency care, diagnosis, or a substitute for qualified independent support.',
    'Employee enrollment remains locked until documented Kenyan legal/privacy review is complete.',
  ] : provider ? [
    'Access only cases employees explicitly share with you, and only for the purpose of the requested support.',
    'Maintain applicable professional confidentiality and safeguarding duties; do not disclose case information to the employer.',
    'The check-in is a self-reflection aid, not a diagnosis or substitute for your professional judgment.',
    'Respect withdrawal of sharing immediately and do not access workplace cases outside your active provider assignment.',
    'MindGuard is not an emergency response service; use appropriate local urgent-care pathways.',
  ] : [
    'Participation and check-ins are voluntary. You may withdraw from the programme.',
    'Your employer does not receive your identity, individual check-ins, support requests, appointments, or provider notes.',
    'A care provider receives information only when you request support and explicitly choose to share it.',
    'Check-ins are for reflection and support, not diagnosis or emergency care.',
    'If you may be in immediate danger, contact local emergency services or go to a health facility.',
  ]
  const accept = async () => {
    setBusy(true); setError('')
    try { await acceptTerms(); setTermsAccepted(true) }
    catch (e) { setError(e instanceof Error ? e.message : 'Unable to save acceptance.') }
    finally { setBusy(false) }
  }
  return <main className="min-h-screen bg-slate-50 px-4 py-10"><section className="mx-auto max-w-2xl rounded-2xl border bg-white p-6 shadow-sm sm:p-8"><p className="text-xs font-bold uppercase tracking-widest text-teal-700">Workplace wellbeing</p><h1 className="mt-2 text-2xl font-bold">{employer?'Responsible employer use':provider?'Independent provider responsibilities':'Your workplace wellbeing participation'}</h1><p className="mt-2 text-sm text-slate-600">Please review these role-specific commitments before continuing.</p><ul className="mt-6 space-y-3">{clauses.map(c=><li key={c} className="rounded-xl bg-slate-50 p-4 text-sm text-slate-700">{c}</li>)}</ul><label className="mt-6 flex gap-3 text-sm"><input type="checkbox" className="mt-1" checked={checked} onChange={e=>setChecked(e.target.checked)} /><span>I have read and agree to these workplace-specific commitments.</span></label>{error&&<p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}<button className={`${button} mt-5 w-full`} disabled={!checked||busy} onClick={accept}>{busy?'Saving…':'Accept and continue'}</button></section></main>
}

export function WorkplaceJoinPage() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [accepted, setAccepted] = useState(false)
  const [challenge, setChallenge] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const token = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token') || new URLSearchParams(window.location.search).get('token') || ''

  const start = async () => {
    setBusy(true); setMessage('')
    try {
      const res = await api.post('/v1/workplace/enrollment/start', { token, name, email, password, accepted_notice: accepted })
      setChallenge(res.data.challenge_id)
      setMessage(res.data.message)
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Could not start enrollment.') }
    finally { setBusy(false) }
  }
  const verify = async () => {
    setBusy(true); setMessage('')
    try {
      const result = await api.post('/v1/workplace/enrollment/verify', { challenge_id: challenge, code })
      setToken(result.data.access_token)
      setMessage('Your work email is verified. Taking you to your private wellbeing space…')
      window.setTimeout(() => { window.location.href = '/' }, 1800)
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Verification failed.') }
    finally { setBusy(false) }
  }
  if (!token) return <div className="mx-auto mt-16 max-w-xl rounded-2xl bg-white p-8 text-center shadow">This enrollment link is missing. Ask your workplace administrator for a current shared link.</div>
  return <main className="min-h-screen bg-slate-50 px-4 py-12"><section className="mx-auto max-w-xl space-y-5">
    <header><p className="text-sm font-bold uppercase tracking-widest text-teal-700">Workplace wellbeing · Kenya pilot</p><h1 className="mt-2 text-3xl font-bold text-slate-900">Your choice, your private space</h1><p className="mt-3 text-slate-600">Participation is voluntary. Your employer cannot see whether you join, your check-ins, support requests, appointments, or notes.</p></header>
    <div className={card}>
      {!challenge ? <div className="space-y-4"><label className="block text-sm font-medium">Name<input className="mt-1 w-full rounded-lg border p-3" value={name} onChange={e => setName(e.target.value)} autoComplete="name" /></label>
        <label className="block text-sm font-medium">Approved work email<input type="email" className="mt-1 w-full rounded-lg border p-3" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" /></label>
        <label className="block text-sm font-medium">Create a password<input type="password" className="mt-1 w-full rounded-lg border p-3" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" /></label>
        <label className="flex gap-3 text-sm text-slate-700"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} className="mt-1" /><span>I understand the notice: check-ins are private to me. My employer only sees fixed, broad group summaries when at least 10 distinct employees have responded. A provider sees information only if I request support and explicitly share it. I can withdraw from the programme.</span></label>
        <button disabled={busy || !name || !email || password.length < 10 || !accepted} className={button} onClick={start}>{busy ? 'Sending verification…' : 'Verify email and join'}</button>
      </div> : <div className="space-y-4"><h2 className="text-xl font-semibold">Check your work email</h2><p className="text-sm text-slate-600">Enter the six-digit code we sent. It expires in 15 minutes.</p><input inputMode="numeric" autoComplete="one-time-code" maxLength={6} className="w-full rounded-lg border p-3 tracking-[0.35em]" value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} /><button disabled={busy || code.length !== 6} className={button} onClick={verify}>{busy ? 'Verifying…' : 'Verify and finish'}</button></div>}
      {message && <p role="status" className="mt-4 text-sm text-slate-700">{message}</p>}
    </div>
    <p className="text-xs leading-relaxed text-slate-500">MindGuard workplace wellbeing is a pilot service, not emergency care. If you may be in immediate danger, contact local emergency services or a trusted person now. Review the local crisis resources in MindGuard after signing in.</p>
  </section></main>
}

export default function WorkplacePage() {
  const user = useAuthStore(s => s.user)
  const currentPage = useUiStore(s => s.currentPage)
  const role = user?.role_type
  const isCompanyAdmin = role === 'company_admin'
  const isProvider = role === 'workplace_provider'
  const [report, setReport] = useState<Report | null>(null)
  const [providers, setProviders] = useState<Provider[]>([])
  const [providerId, setProviderId] = useState('')
  const [companyProviders, setCompanyProviders] = useState<Provider[]>([])
  const [enrollmentLinks, setEnrollmentLinks] = useState<Array<{id:string;created_at:string;active:boolean}>>([])
  const [providerEmail, setProviderEmail] = useState('')
  const [link, setLink] = useState('')
  const [linkId, setLinkId] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [checkin, setCheckin] = useState({ mood: 3, stress: 3, support_access: 3 })
  const [shareConfirmed, setShareConfirmed] = useState(false)
  const [checkinHistory, setCheckinHistory] = useState<Array<{id:string;answers:Record<string,number>;created_at:string}>>([])
  const [supportHistory, setSupportHistory] = useState<Array<{id:string;status:string;created_at:string}>>([])
  const [supportUpdates, setSupportUpdates] = useState<Array<{id:string;message:string;shared_at:string}>>([])
  const [setup, setSetup] = useState<{readiness:string;checklist:Record<string,boolean>;administrators:Array<{id:string;name:string;email:string;status:string}>;policy:{privacy_notice_version:string;employee_population_range?:string;retention_days:number;status:string}}|null>(null)
  const [trends, setTrends] = useState<{scope:string;periods:Array<{period:string;suppressed:boolean;averages?:Record<string,number|null>}>}|null>(null)
  const [audit, setAudit] = useState<Array<{event_type:string;occurred_at:string}>>([])
  const [adminInvite, setAdminInvite] = useState({name:'',email:''})
  const [policy, setPolicy] = useState({privacy_contact_email:'',employee_population_range:'',retention_days:90,privacy_notice_version:'v1',confirm_aggregate_only:false})
  const refresh = useCallback(async () => {
    try {
      if (isCompanyAdmin) {
        const [reportResult, providerResult, linkResult, setupResult, trendResult, auditResult] = await Promise.all([api.get('/v1/workplace/admin/report'), api.get('/v1/workplace/admin/providers'), api.get('/v1/workplace/admin/enrollment-links'), api.get('/v1/workplace/admin/setup'), api.get('/v1/workplace/admin/report/trends'), api.get('/v1/workplace/admin/audit')])
        setReport(reportResult.data); setCompanyProviders(providerResult.data); setEnrollmentLinks(linkResult.data)
        setSetup(setupResult.data); setTrends(trendResult.data); setAudit(auditResult.data)
        setPolicy(current => ({ ...current, privacy_contact_email: current.privacy_contact_email || setupResult.data.policy?.privacy_contact_email || '', employee_population_range: current.employee_population_range || setupResult.data.policy?.employee_population_range || '', retention_days: current.retention_days || setupResult.data.policy?.retention_days || 365, privacy_notice_version: current.privacy_notice_version || setupResult.data.policy?.privacy_notice_version || 'v1' }))
      }
      else if (!isProvider) {
        const [providerResult, checkinResult, supportResult] = await Promise.all([
          api.get('/v1/workplace/providers'), api.get('/v1/workplace/checkins'), api.get('/v1/workplace/support-requests'),
        ])
        setProviders(providerResult.data); setCheckinHistory(checkinResult.data); setSupportHistory(supportResult.data)
        const updateResult = await api.get('/v1/workplace/support-updates')
        setSupportUpdates(updateResult.data)
      }
    } catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to load this workspace.') }
  }, [isCompanyAdmin, isProvider])
  // Loading API data here is an external synchronization; state updates happen after the requests settle.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void refresh() }, [refresh])

  const createLink = async () => {
    setBusy(true); setNotice('')
    try {
      const res = await api.post('/v1/workplace/admin/enrollment-link')
      const url = `${window.location.origin}/workplace/join#token=${encodeURIComponent(res.data.token)}`
      setLink(url); setLinkId(res.data.id)
      try { await navigator.clipboard?.writeText(url); setNotice('Shared enrollment link created and copied. Store and distribute it securely.') }
      catch { setNotice('Shared enrollment link created. Copy it below and distribute it securely.') }
    } catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to create link.') }
    finally { setBusy(false) }
  }
  const attachProvider = async () => {
    setBusy(true); setNotice('')
    try { await api.post('/v1/workplace/admin/providers', { provider_email: providerEmail }); setProviderEmail(''); setNotice('Verified independent provider connected to this workplace.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to connect provider.') }
    finally { setBusy(false) }
  }
  const deactivateProvider = async (id:string) => {
    if (!window.confirm('Deactivate this provider for this company? They will lose access to this company’s workplace cases.')) return
    try { await api.post(`/v1/workplace/admin/providers/${id}/deactivate`); setNotice('Provider deactivated.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to deactivate provider.') }
  }
  const revokeLink = async () => {
    if (!linkId || !window.confirm('Revoke this shared enrollment link? Anyone who has it will no longer be able to join.')) return
    try { await api.post(`/v1/workplace/admin/enrollment-link/${linkId}/revoke`); setLink(''); setLinkId(''); setNotice('Enrollment link revoked.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to revoke link.') }
  }
  const saveCheckin = async () => {
    setBusy(true); setNotice('')
    try { await api.post('/v1/workplace/checkins', checkin); setNotice('Your check-in is saved privately. Your employer cannot see it.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to save check-in.') }
    finally { setBusy(false) }
  }
  const requestSupport = async () => {
    if (!providerId || !shareConfirmed) return
    setBusy(true); setNotice('')
    try { await api.post('/v1/workplace/support-requests', { provider_id: providerId, share_latest_checkin: true }); setNotice('Support request sent. The selected provider can see the check-in you shared; your employer is not notified.'); setShareConfirmed(false); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to request support.') }
    finally { setBusy(false) }
  }
  const withdraw = async () => {
    if (!window.confirm('Withdraw from the workplace programme? Future check-ins stop and provider access is revoked.')) return
    try { await api.post('/v1/workplace/withdraw'); setNotice('Participation withdrawn. Sign out to finish.') }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to withdraw.') }
  }
  const inviteAdministrator = async () => {
    setBusy(true); setNotice('')
    try { await api.post('/v1/workplace/admin/administrators', adminInvite); setAdminInvite({name:'',email:''}); setNotice('Company administrator invitation sent.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to invite administrator.') }
    finally { setBusy(false) }
  }
  const savePolicy = async () => {
    setBusy(true); setNotice('')
    try { await api.put('/v1/workplace/admin/policy', policy); setNotice('Privacy and retention policy approved and saved.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to save workplace policy.') }
    finally { setBusy(false) }
  }

  if (role === 'workplace_employee' && currentPage === 'workplace-messages') return <EmployeeMessagesPage />
  if (isProvider && currentPage === 'workplace-appointments') return <ProviderAppointmentsPage />

  return <main className="mx-auto w-full max-w-5xl space-y-6 text-slate-900">
    <header><p className="text-xs font-bold uppercase tracking-widest text-teal-700">MindGuard workplace</p><h1 className="mt-1 text-3xl font-bold">{isCompanyAdmin ? 'Company wellbeing programme' : isProvider ? 'Workplace care cases' : 'Your private wellbeing space'}</h1>
      <p className="mt-2 max-w-3xl text-slate-600">{isCompanyAdmin ? 'Manage the shared opt-in link and view broad programme insights. This workspace never exposes employee identities or individual wellbeing data.' : isProvider ? 'Only employees who explicitly requested support and shared information with you appear here.' : 'Your participation is voluntary. Check-ins are private to you and are not visible to your employer.'}</p></header>
    {isCompanyAdmin ? <>
      {(currentPage==='workplace'||currentPage==='workplace-setup')&&<section className={card}><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">Operational readiness</h2><p className="text-sm text-slate-600">Workplace readiness is independent from school roster and consent readiness.</p></div><span className="rounded-full bg-teal-50 px-3 py-1 text-xs font-bold uppercase text-teal-800">{setup?.readiness?.replaceAll('_',' ')||'loading'}</span></div><div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">{Object.entries(setup?.checklist||{}).map(([key,ok])=><div key={key} className={`rounded-xl p-3 text-sm ${ok?'bg-emerald-50 text-emerald-900':'bg-amber-50 text-amber-950'}`}><i className={`ti ${ok?'ti-circle-check':'ti-clock'} mr-2`}/>{key.replaceAll('_',' ')}</div>)}</div></section>}
      {currentPage==='workplace-setup'&&<><section className={card}><h2 className="text-lg font-semibold">Privacy, retention and reporting policy</h2><div className="mt-4 grid gap-3 sm:grid-cols-2"><input className="rounded-lg border p-3" type="email" placeholder="Privacy contact email" value={policy.privacy_contact_email} onChange={e=>setPolicy({...policy,privacy_contact_email:e.target.value})}/><input className="rounded-lg border p-3" placeholder="Employee population range" value={policy.employee_population_range} onChange={e=>setPolicy({...policy,employee_population_range:e.target.value})}/><input className="rounded-lg border p-3" type="number" min={30} max={3650} value={policy.retention_days} onChange={e=>setPolicy({...policy,retention_days:Number(e.target.value)})}/><input className="rounded-lg border p-3" placeholder="Privacy notice version" value={policy.privacy_notice_version} onChange={e=>setPolicy({...policy,privacy_notice_version:e.target.value})}/></div><label className="mt-4 flex gap-2 text-sm"><input type="checkbox" checked={policy.confirm_aggregate_only} onChange={e=>setPolicy({...policy,confirm_aggregate_only:e.target.checked})}/><span>I confirm employer reporting remains aggregate-only and never exposes participation or care cases.</span></label><button className={`${button} mt-4`} disabled={busy||!policy.privacy_contact_email||!policy.confirm_aggregate_only} onClick={savePolicy}>Approve and save policy</button></section><section className={card}><h2 className="text-lg font-semibold">Company administrators</h2><div className="mt-3 grid gap-2 sm:grid-cols-2"><input className="rounded-lg border p-3" placeholder="Full name" value={adminInvite.name} onChange={e=>setAdminInvite({...adminInvite,name:e.target.value})}/><input className="rounded-lg border p-3" type="email" placeholder="Approved work email" value={adminInvite.email} onChange={e=>setAdminInvite({...adminInvite,email:e.target.value})}/></div><button className={`${button} mt-3`} disabled={busy||!adminInvite.name||!adminInvite.email} onClick={inviteAdministrator}>Send administrator invitation</button><ul className="mt-4 divide-y">{setup?.administrators.map(a=><li className="py-3 text-sm" key={a.id}><strong>{a.name}</strong> · {a.email} · {a.status}</li>)}</ul></section></>}
      {(currentPage==='workplace'||currentPage==='workplace-enrollment')&&<section className={card}><h2 className="text-lg font-semibold">Voluntary employee enrollment</h2><p className="my-2 text-sm text-slate-600">Share a revocable link. This page never shows who opened or used it.</p><button className={button} disabled={busy} onClick={createLink}>{busy ? 'Creating…' : 'Create shared enrollment link'}</button>{link && <div className="mt-3 space-y-2"><p className="break-all rounded-lg bg-slate-50 p-3 text-sm">{link}</p><button className="text-sm font-semibold text-rose-700 underline" onClick={revokeLink}>Revoke this newly created link</button></div>}{enrollmentLinks.length>0&&<ul className="mt-4 divide-y border-t">{enrollmentLinks.map(l=><li key={l.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm"><span>Shared link · created {new Date(l.created_at).toLocaleDateString()} · {l.active?'active':'revoked or expired'}</span>{l.active&&<button className="font-semibold text-rose-700 underline" onClick={async()=>{if(!window.confirm('Revoke this enrollment link?'))return;try{await api.post(`/v1/workplace/admin/enrollment-link/${l.id}/revoke`);setNotice('Enrollment link revoked.');await refresh()}catch(e){setNotice(e instanceof Error?e.message:'Unable to revoke link.')}}}>Revoke</button>}</li>)}</ul>}</section>}
      {(currentPage==='workplace'||currentPage==='workplace-providers')&&<section className={card}><h2 className="text-lg font-semibold">Independent care providers</h2><p className="my-2 text-sm text-slate-600">Connect providers whose credentials have been reviewed by MindGuard. Employers cannot access provider case notes or case lists.</p><div className="flex flex-col gap-2 sm:flex-row"><input className="min-w-0 flex-1 rounded-lg border p-3" type="email" placeholder="Verified provider's email" value={providerEmail} onChange={e=>setProviderEmail(e.target.value)} /><button className={button} disabled={busy||!providerEmail} onClick={attachProvider}>Connect provider</button></div>{companyProviders.length>0&&<ul className="mt-4 divide-y">{companyProviders.map(p=><li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-3"><span><strong>{p.name}</strong>{p.title&&<span className="text-sm text-slate-600"> · {p.title}</span>}<span className="ml-2 text-xs text-slate-500">{p.status}</span></span>{p.status==='active'&&<button className="text-sm font-semibold text-rose-700 underline" onClick={()=>deactivateProvider(p.id)}>Deactivate</button>}</li>)}</ul>}</section>}
      {(currentPage==='workplace'||currentPage==='workplace-reports')&&<section className={card}><h2 className="text-lg font-semibold">Protected group insights</h2>{report?.suppressed ? <p className="mt-3 rounded-lg bg-amber-50 p-4 text-sm text-amber-900">{report.message}</p> : report ? <><p className="mt-2 text-sm text-slate-600">Fixed whole-company view · respondent group {report.cohort_size}</p><div className="mt-4 grid gap-3 sm:grid-cols-3">{Object.entries(report.averages || {}).map(([key, value]) => <div key={key} className="rounded-xl bg-slate-50 p-4"><p className="text-xs uppercase text-slate-500">{key.replace('_', ' ')}</p><p className="mt-1 text-2xl font-bold">{value ?? 'Suppressed'}</p><p className="text-xs text-slate-500">average, 1–5 scale</p></div>)}</div><p className="mt-3 text-xs text-slate-500">{report.scope}. No individual data, filters, or export.</p></> : <p className="mt-3 text-sm text-slate-500">Loading protected aggregate…</p>}{trends&&trends.periods.some(p=>!p.suppressed)&&<Plot data={['mood','stress','support_access'].map(key=>({type:'scatter' as const,mode:'lines+markers' as const,name:key.replace('_',' '),x:trends.periods.filter(p=>!p.suppressed&&p.averages?.[key]!=null).map(p=>p.period),y:trends.periods.filter(p=>!p.suppressed&&p.averages?.[key]!=null).map(p=>p.averages?.[key])}))} layout={{height:350,margin:{l:45,r:20,t:30,b:50},yaxis:{range:[1,5]},paper_bgcolor:'transparent',plot_bgcolor:'#fff'}} config={{responsive:true,displaylogo:false}} className="w-full"/>}</section>}
      {currentPage==='workplace-audit'&&<section className={card}><h2 className="text-lg font-semibold">Workplace audit history</h2><p className="mt-1 text-sm text-slate-600">Operational events only. Employee participation and care activity are intentionally excluded.</p><ul className="mt-4 divide-y">{audit.map((event,index)=><li className="py-3 text-sm" key={`${event.occurred_at}-${index}`}><strong>{event.event_type.replaceAll('_',' ')}</strong><span className="ml-2 text-slate-500">{new Date(event.occurred_at).toLocaleString()}</span></li>)}</ul></section>}
      <section className="rounded-2xl border border-amber-300 bg-amber-50 p-5"><h2 className="font-semibold text-amber-950">Pilot launch gate</h2><p className="mt-2 text-sm text-amber-900">Before a live pilot, obtain Kenyan legal/privacy review covering controller and processor roles, employee notice and consent, DPIA, provider confidentiality, retention, and cross-border processing. MindGuard is not represented as legally certified.</p></section>
    </> : isProvider ? <ProviderCaseList /> : <>
      {(currentPage==='workplace'||currentPage==='workplace-checkins')&&<section className={card}><h2 className="text-lg font-semibold">Private check-in</h2><p className="mt-1 text-sm text-slate-600">A short self-reflection, visible only to you unless you explicitly choose to share it with a provider.</p><div className="mt-4 grid gap-4 sm:grid-cols-3">{([['mood','How are you feeling?'],['stress','How manageable does stress feel?'],['support_access','How supported do you feel?']] as const).map(([key,label]) => <label key={key} className="text-sm font-medium">{label}<select className="mt-1 block w-full rounded-lg border p-3" value={checkin[key]} onChange={e => setCheckin(c => ({...c,[key]:Number(e.target.value)}))}>{[1,2,3,4,5].map(v=><option key={v} value={v}>{v} — {v===1?'not at all':v===5?'very much':'somewhat'}</option>)}</select></label>)}</div><button className={`${button} mt-4`} disabled={busy} onClick={saveCheckin}>Save private check-in</button></section>}
      {(currentPage==='workplace'||currentPage==='workplace-support')&&<section className={card}><h2 className="text-lg font-semibold">Request independent support</h2><p className="my-2 text-sm text-slate-600">The provider receives your identity and only the specific latest check-in selected when you make this request. Your employer is not notified.</p>{providers.length ? <div className="space-y-3"><select className="w-full rounded-lg border p-3 sm:w-auto" value={providerId} onChange={e=>setProviderId(e.target.value)}><option value="">Choose a provider…</option>{providers.map(p=><option key={p.id} value={p.id}>{p.name}{p.title ? ` · ${p.title}` : ''}</option>)}</select><label className="flex items-start gap-2 text-sm text-slate-700"><input type="checkbox" checked={shareConfirmed} onChange={e=>setShareConfirmed(e.target.checked)} className="mt-1" /><span>I want this provider to receive my identity and most recent check-in with this support request. My employer will not receive it.</span></label><button className={button} disabled={busy || !providerId || !shareConfirmed} onClick={requestSupport}>Request support and share selected check-in</button></div> : <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">An independent provider is not currently configured for this programme. You can still use private check-ins and local resources.</p>}{supportHistory.length>0&&<div className="mt-4 border-t pt-4"><h3 className="font-medium">Your support requests</h3><ul className="mt-2 space-y-2 text-sm">{supportHistory.map(c=><li className="flex justify-between gap-3 rounded-lg bg-slate-50 p-3" key={c.id}><span>{new Date(c.created_at).toLocaleDateString()} · {c.status.replaceAll('_',' ')}</span>{c.status==='open'&&<button className="font-semibold text-rose-700 underline" onClick={async()=>{try{await api.post(`/v1/workplace/support-requests/${c.id}/withdraw`);setNotice('Provider access to this shared check-in has been withdrawn.');await refresh()}catch(e){setNotice(e instanceof Error?e.message:'Unable to withdraw sharing.')}}}>Withdraw sharing</button>}</li>)}</ul></div>}{supportUpdates.length>0&&<div className="mt-4 border-t pt-4"><h3 className="font-semibold">Updates shared with you</h3><ul className="mt-2 space-y-2">{supportUpdates.map(update=><li key={update.id} className="rounded-lg bg-teal-50 p-3 text-sm"><p>{update.message}</p><time className="mt-2 block text-xs text-slate-500">{new Date(update.shared_at).toLocaleString()}</time></li>)}</ul></div>}</section>}
      {(currentPage==='workplace'||currentPage==='workplace-checkins')&&checkinHistory.length>0&&<section className={card}><h2 className="text-lg font-semibold">Your private check-in history</h2><ul className="mt-3 space-y-2">{checkinHistory.map(c=><li key={c.id} className="rounded-lg bg-slate-50 p-3 text-sm"><p className="font-medium">{new Date(c.created_at).toLocaleString()}</p><p className="mt-1 text-slate-600">Mood {c.answers.mood}/5 · Stress {c.answers.stress}/5 · Support {c.answers.support_access}/5</p></li>)}</ul></section>}
      <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5"><h2 className="font-semibold text-rose-900">Need urgent help?</h2><p className="mt-2 text-sm text-rose-900">This service is not emergency care. If you are in immediate danger in Kenya, call <a className="font-bold underline" href="tel:999">999</a>, <a className="font-bold underline" href="tel:911">911</a>, or <a className="font-bold underline" href="tel:112">112</a>, or go to the nearest health facility. Your employer is not automatically alerted.</p><a className="mt-3 inline-block text-sm font-semibold text-rose-800 underline" href="https://mental.health.go.ke/resources/" target="_blank" rel="noreferrer">Kenya Ministry of Health mental-health resources</a></section>
      <button className="text-sm text-slate-500 underline" onClick={withdraw}>Withdraw from workplace participation</button>
    </>}
    {notice && <p role="status" className="rounded-xl bg-slate-100 p-3 text-sm text-slate-700">{notice}</p>}
  </main>
}

export function WorkplaceAdminPage() {
  const [companies, setCompanies] = useState<Array<{id:string;name:string;status:string;approved_work_email_domains:string[];legal_review_complete:boolean;legal_review_reference?:string;employee_population_range?:string;retention_days:number;policy_status:string;administrators:Array<{id:string;name:string;email:string;status:string}>}>>([])
  const [companyLeads, setCompanyLeads] = useState<Array<{id:string;full_name:string;work_email:string;organisation:string;organisation_type:string;status:string;employee_population_range?:string;institution_id?:string}>>([])
  const [selectedLead, setSelectedLead] = useState('')
  const [name, setName] = useState('')
  const [adminName, setAdminName] = useState('')
  const [adminEmail, setAdminEmail] = useState('')
  const [domains, setDomains] = useState('')
  const [privacyContact, setPrivacyContact] = useState('')
  const [populationRange, setPopulationRange] = useState('')
  const [retentionDays, setRetentionDays] = useState(365)
  const [reference, setReference] = useState('')
  const [providerEmail, setProviderEmail] = useState('')
  const [providerTitle, setProviderTitle] = useState('')
  const [qualification, setQualification] = useState('')
  const [registration, setRegistration] = useState('')
  const [credentialReference, setCredentialReference] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => { try { const [companyResult,leadResult]=await Promise.all([api.get('/v1/workplace/admin/companies'),api.get('/v1/admin/demo-requests')]);setCompanies(companyResult.data);setCompanyLeads((leadResult.data.demo_requests||[]).filter((lead:{organisation_type:string;status:string;institution_id?:string})=>lead.organisation_type==='company'&&!lead.institution_id&&['qualified','demo_scheduled','closed_won'].includes(lead.status))) } catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to load companies and qualified leads.') } }, [])
  // Loading API data here is an external synchronization; state updates happen after the request settles.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])
  const create = async () => {
    setBusy(true); setNotice('')
    try { const result=await api.post('/v1/workplace/admin/companies', { name, admin_name:adminName, admin_email: adminEmail, work_email_domains: domains.split(',').map(v=>v.trim()).filter(Boolean), privacy_contact_email:privacyContact||adminEmail, employee_population_range:populationRange||null, retention_days:retentionDays }); setName(''); setAdminName(''); setAdminEmail(''); setDomains(''); setPrivacyContact(''); setPopulationRange(''); setRetentionDays(365); const status=result.data.administrator_invitation_status; setNotice(status==='active'?'Company created and the existing active account was assigned as its first administrator; no invitation email was needed.':result.data.invitation_sent===false?'Company created, but the invitation email could not be delivered. Use Resend invitation below after refreshing.':'Company created and the first administrator invitation was sent. Provider setup and the privacy review still need completion.'); await load() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to create company.') }
    finally { setBusy(false) }
  }
  const recordReview = async (id:string) => {
    setBusy(true); setNotice('')
    try { await api.post(`/v1/workplace/admin/companies/${id}/legal-review`, { reviewed: true, reference }); setReference(''); setNotice('Review record saved. Enrollment remains disabled until the company policy is approved and an independent provider is configured.'); await load() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to record review.') }
    finally { setBusy(false) }
  }
  const provisionProvider = async () => {
    setBusy(true); setNotice('')
    try { await api.post('/v1/workplace/admin/provider-credentials', { provider_email: providerEmail, professional_title: providerTitle, qualification, registration_number: registration, verification_reference: credentialReference }); setProviderEmail(''); setProviderTitle(''); setQualification(''); setRegistration(''); setCredentialReference(''); setNotice('Provider account enabled. The credential verification reference was recorded; verify credentials against the relevant professional register before submitting.'); }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to provision provider.') }
    finally { setBusy(false) }
  }
  const lifecycle = async (id:string,action:'activate'|'suspend'|'archive') => {
    const reason=window.prompt(`Reason to ${action} this workplace company:`)
    if(!reason||reason.trim().length<3)return
    if(action==='archive'&&!window.confirm('Archive this company? Active enrollment links will be revoked and providers deactivated. This cannot be undone.'))return
    setBusy(true);setNotice('')
    try{await api.post(`/v1/workplace/admin/companies/${id}/lifecycle`,{action,reason});setNotice(`Company ${action}d.`);await load()}catch(e){setNotice(e instanceof Error?e.message:`Unable to ${action} company.`)}finally{setBusy(false)}
  }
  const resendInvite = async(companyId:string,adminId:string) => {
    setBusy(true);setNotice('')
    try{const {data}=await api.post(`/v1/workplace/admin/companies/${companyId}/administrators/${adminId}/resend`);setNotice(data.email_sent?'Administrator invitation resent.':`Invitation could not be sent: ${data.email_error||'email delivery failed'}`)}catch(e){setNotice(e instanceof Error?e.message:'Unable to resend invitation.')}finally{setBusy(false)}
  }
  const selectCompanyLead=(id:string)=>{setSelectedLead(id);const lead=companyLeads.find(item=>item.id===id);if(!lead)return;const domain=lead.work_email.split('@')[1]||'';setName(lead.organisation);setAdminName(lead.full_name);setAdminEmail(lead.work_email);setDomains(domain);setPrivacyContact(lead.work_email);setPopulationRange(lead.employee_population_range||'')}
  const convertLead=async()=>{if(!selectedLead)return;setBusy(true);setNotice('');try{const {data}=await api.post(`/v1/workplace/admin/demo-requests/${selectedLead}/convert`,{admin_name:adminName,admin_email:adminEmail,work_email_domains:domains.split(',').map(v=>v.trim()).filter(Boolean),privacy_contact_email:privacyContact,employee_population_range:populationRange||null,retention_days:retentionDays});setNotice(data.invitation_sent?'Qualified company demo converted and first administrator invitation sent.':'Company created, but the administrator email failed; use Resend invitation in the company list.');setSelectedLead('');await load()}catch(e){setNotice(e instanceof Error?e.message:'Unable to convert company demo.')}finally{setBusy(false)}}
  return <main className="mx-auto w-full max-w-5xl space-y-6 text-slate-900"><header><p className="text-xs font-bold uppercase tracking-widest text-teal-700">Global administration</p><h1 className="mt-1 text-3xl font-bold">Workplace pilot setup</h1><p className="mt-2 text-slate-600">Create a separate company tenant and enforce the Kenya privacy-review gate before enrollment. Never upload an employee roster.</p></header>
    {companyLeads.length>0&&<section className={card}><h2 className="text-lg font-semibold">Convert a qualified company demo</h2><p className="my-2 text-sm text-slate-600">Converts the company lead into a workplace tenant, records approved work domains and privacy contact, and invites the first company administrator.</p><label className="block text-sm font-medium">Qualified company request<select className="mt-1 w-full rounded-lg border p-3" value={selectedLead} onChange={e=>selectCompanyLead(e.target.value)}><option value="">Select a qualified company demo…</option>{companyLeads.map(lead=><option key={lead.id} value={lead.id}>{lead.organisation} · {lead.full_name} · {lead.status}</option>)}</select></label>{selectedLead&&<div className="mt-4 grid gap-3 sm:grid-cols-2"><input className="rounded-lg border p-3" placeholder="Company name" value={name} onChange={e=>setName(e.target.value)}/><input className="rounded-lg border p-3" placeholder="First company admin name" value={adminName} onChange={e=>setAdminName(e.target.value)}/><input className="rounded-lg border p-3" type="email" placeholder="Admin email (must not already have an account)" value={adminEmail} onChange={e=>setAdminEmail(e.target.value)}/><input className="rounded-lg border p-3" placeholder="Approved work domains" value={domains} onChange={e=>setDomains(e.target.value)}/><input className="rounded-lg border p-3" type="email" placeholder="Privacy contact" value={privacyContact} onChange={e=>setPrivacyContact(e.target.value)}/><input className="rounded-lg border p-3" placeholder="Employee population range" value={populationRange} onChange={e=>setPopulationRange(e.target.value)}/></div>}{selectedLead&&<button disabled={busy||!name||!adminName||!adminEmail||!domains||!privacyContact} onClick={()=>void convertLead()} className={`${button} mt-4`}>{busy?'Converting…':'Create workplace and invite administrator'}</button>}</section>}
    <section className={card}><h2 className="text-lg font-semibold">Create company tenant</h2><p className="my-2 text-sm text-slate-600">Create the workplace boundary and invite its first administrator. Enrollment stays disabled until privacy review, company policy, and an approved independent provider are ready.</p><div className="grid gap-3 sm:grid-cols-2"><input className="rounded-lg border p-3" placeholder="Company legal / display name" value={name} onChange={e=>setName(e.target.value)} /><input className="rounded-lg border p-3" placeholder="First administrator full name" value={adminName} onChange={e=>setAdminName(e.target.value)} /><input className="rounded-lg border p-3" type="email" placeholder="First administrator work email" value={adminEmail} onChange={e=>setAdminEmail(e.target.value)} /><input className="rounded-lg border p-3" placeholder="Approved work email domains (comma-separated)" value={domains} onChange={e=>setDomains(e.target.value)} /><input className="rounded-lg border p-3" type="email" placeholder="Company privacy contact email" value={privacyContact} onChange={e=>setPrivacyContact(e.target.value)} /><input className="rounded-lg border p-3" placeholder="Approximate employee population range" value={populationRange} onChange={e=>setPopulationRange(e.target.value)} /><label className="text-sm text-slate-600">Default retention (days)<input className="mt-1 w-full rounded-lg border p-3" type="number" min={30} max={3650} value={retentionDays} onChange={e=>setRetentionDays(Number(e.target.value))}/></label></div><button className={`${button} mt-4`} disabled={busy || !name || !adminName || !adminEmail || !domains} onClick={create}>Create tenant and invite administrator</button></section>
    <section className={card}><h2 className="text-lg font-semibold">Review an independent provider</h2><p className="my-2 text-sm text-slate-600">Use an existing independent adult account. Confirm the current professional registration through the relevant Kenyan register and retain a reference to the review. This form does not perform registry verification itself.</p><div className="grid gap-3 sm:grid-cols-2"><input className="rounded-lg border p-3" type="email" placeholder="Provider's existing account email" value={providerEmail} onChange={e=>setProviderEmail(e.target.value)} /><input className="rounded-lg border p-3" placeholder="Professional title" value={providerTitle} onChange={e=>setProviderTitle(e.target.value)} /><input className="rounded-lg border p-3" placeholder="Qualification" value={qualification} onChange={e=>setQualification(e.target.value)} /><input className="rounded-lg border p-3" placeholder="Registration number" value={registration} onChange={e=>setRegistration(e.target.value)} /><input className="rounded-lg border p-3 sm:col-span-2" placeholder="Credential check reference / date" value={credentialReference} onChange={e=>setCredentialReference(e.target.value)} /></div><button className={`${button} mt-4`} disabled={busy||!providerEmail||!providerTitle||!qualification||!registration||credentialReference.trim().length<4} onClick={provisionProvider}>Record review and enable provider</button></section>
    <section className="space-y-3"><h2 className="text-xl font-semibold">Companies and launch gates</h2>{companies.map(c=><article key={c.id} className={card}><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-lg font-semibold">{c.name}</h3><p className="text-sm text-slate-600">Approved work domains: {c.approved_work_email_domains.join(', ')}</p><p className="mt-1 text-xs text-slate-500">Employees: {c.employee_population_range||'not recorded'} · retention: {c.retention_days} days · company policy: {c.policy_status}</p></div><span className={`rounded-full px-3 py-1 text-xs font-semibold ${c.status==='ACTIVE'?'bg-emerald-100 text-emerald-800':c.status==='SUSPENDED'?'bg-amber-100 text-amber-900':'bg-slate-200 text-slate-700'}`}>{c.status}</span></div><div className="mt-3 space-y-2 border-t pt-3">{c.administrators.map(a=><div key={a.id} className="flex flex-wrap items-center justify-between gap-2 text-sm"><span><strong>{a.name}</strong> · {a.email} · {a.status}</span>{!['active','approved'].includes(a.status.toLowerCase())&&<button disabled={busy} onClick={()=>void resendInvite(c.id,a.id)} className="font-semibold text-teal-800 underline">Resend invitation</button>}</div>)}</div>{!c.legal_review_complete && <div className="mt-4 rounded-xl bg-amber-50 p-4"><p className="text-sm text-amber-950">Record the completed legal/privacy review and its internal reference only after review by qualified Kenyan counsel and privacy professionals. This operational record does not certify legal compliance.</p><div className="mt-3 flex flex-col gap-2 sm:flex-row"><input className="min-w-0 flex-1 rounded-lg border p-3" placeholder="Review / DPIA record reference" value={reference} onChange={e=>setReference(e.target.value)} /><button className={button} disabled={busy || reference.trim().length<4} onClick={()=>recordReview(c.id)}>Record completed review</button></div></div>}{c.legal_review_reference && <p className="mt-3 text-xs text-slate-500">Review record: {c.legal_review_reference}</p>}<div className="mt-4 flex flex-wrap gap-2 border-t pt-3">{c.status==='SUSPENDED'&&<button disabled={busy} onClick={()=>void lifecycle(c.id,'activate')} className="rounded-lg border px-3 py-2 text-sm font-semibold">Reactivate</button>}{c.status==='ACTIVE'&&<button disabled={busy} onClick={()=>void lifecycle(c.id,'suspend')} className="rounded-lg border border-amber-300 px-3 py-2 text-sm font-semibold text-amber-900">Suspend</button>}{c.status!=='ARCHIVED'&&<button disabled={busy} onClick={()=>void lifecycle(c.id,'archive')} className="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-800">Archive company</button>}</div></article>)}{companies.length===0&&<div className={card}>No workplace company tenants yet.</div>}</section>
    {notice && <p role="status" className="rounded-xl bg-slate-100 p-3 text-sm">{notice}</p>}
  </main>
}

function ProviderCaseList() {
  const [cases, setCases] = useState<Array<{case_id:string;employee_name:string;employee_email:string;status:string;created_at:string;shared_checkin?:Record<string,number>}>>([])
  const [selected, setSelected] = useState<string>('')
  const [detail, setDetail] = useState<{case:{name:string;email:string;status:string};notes:Array<{id:string;private_note:string;employee_update?:string;created_at:string}>}|null>(null)
  const [messages, setMessages] = useState<Array<{id:string;from_me:boolean;message:string;created_at:string}>>([])
  const [privateNote, setPrivateNote] = useState('')
  const [employeeUpdate, setEmployeeUpdate] = useState('')
  const [reply, setReply] = useState('')
  const [appointment, setAppointment] = useState({starts_at:'',mode:'online',location_or_link:''})
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const load=async()=>{try{setCases((await api.get('/v1/workplace/provider/cases')).data)}catch(e){setError(e instanceof Error?e.message:'Unable to load shared cases.')}}
  useEffect(()=>{let active=true;api.get('/v1/workplace/provider/cases').then(({data})=>{if(active)setCases(data)}).catch(e=>{if(active)setError(e instanceof Error?e.message:'Unable to load shared cases.')});return()=>{active=false}},[])
  const open=async(id:string)=>{setSelected(id);setNotice('');try{const [d,m]=await Promise.all([api.get(`/v1/workplace/provider/cases/${id}`),api.get(`/v1/workplace/provider/cases/${id}/messages`)]);setDetail(d.data);setMessages(m.data)}catch(e){setError(e instanceof Error?e.message:'Unable to open this case.')}}
  const saveNote=async()=>{if(!selected||!privateNote.trim())return;setBusy(true);setNotice('');try{await api.post(`/v1/workplace/provider/cases/${selected}/notes`,{private_note:privateNote,employee_update:employeeUpdate||null});setPrivateNote('');setEmployeeUpdate('');setNotice('Private case note saved. The employee update was shared only because you entered one.');await open(selected)}catch(e){setNotice(e instanceof Error?e.message:'Unable to save case note.')}finally{setBusy(false)}}
  const sendReply=async()=>{if(!selected||!reply.trim())return;setBusy(true);try{await api.post(`/v1/workplace/provider/cases/${selected}/messages`,{message:reply});setReply('');setMessages((await api.get(`/v1/workplace/provider/cases/${selected}/messages`)).data)}catch(e){setNotice(e instanceof Error?e.message:'Unable to send message.')}finally{setBusy(false)}}
  const schedule=async()=>{if(!selected||!appointment.starts_at||!appointment.location_or_link.trim())return;setBusy(true);try{await api.post(`/v1/workplace/provider/cases/${selected}/appointments`,{...appointment,starts_at:new Date(appointment.starts_at).toISOString()});setAppointment({starts_at:'',mode:'online',location_or_link:''});setNotice('Appointment scheduled and the employee was notified.')}catch(e){setNotice(e instanceof Error?e.message:'Unable to schedule appointment.')}finally{setBusy(false)}}
  const close=async()=>{if(!selected||!window.confirm('Close this support case? Future provider access ends, and the employee can request support again later.'))return;try{await api.post(`/v1/workplace/provider/cases/${selected}/close`);setNotice('Support case closed.');setSelected('');setDetail(null);await load()}catch(e){setNotice(e instanceof Error?e.message:'Unable to close case.') }}
  return <section className="grid gap-5 xl:grid-cols-[.8fr_1.2fr]">{error&&<p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800 xl:col-span-2">{error}</p>}<div className="space-y-3">{!cases.length&&!error&&<div className={card}>No employees have requested support and shared a check-in with you.</div>}{cases.map(c=><button key={c.case_id} onClick={()=>void open(c.case_id)} className={`w-full rounded-2xl border bg-white p-4 text-left shadow-sm ${selected===c.case_id?'border-teal-700':'border-slate-200'}`}><div className="flex flex-wrap justify-between gap-2"><strong>{c.employee_name}</strong><span className="text-xs font-semibold uppercase text-teal-800">{c.status}</span></div><p className="text-sm text-slate-600">{c.employee_email}</p><p className="mt-2 text-xs text-slate-500">Support shared {new Date(c.created_at).toLocaleDateString()}</p></button>)}</div>
    {detail&&selected?<div className="space-y-4"><article className={card}><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-bold">{detail.case.name}</h2><p className="text-sm text-slate-600">{detail.case.email}</p></div><span className="text-sm font-semibold capitalize text-teal-800">{detail.case.status}</span></div><p className="mt-3 text-xs text-slate-500">This employee explicitly requested support and shared the following check-in with you.</p>{cases.find(c=>c.case_id===selected)?.shared_checkin&&<dl className="mt-3 grid gap-2 sm:grid-cols-3">{Object.entries(cases.find(c=>c.case_id===selected)?.shared_checkin||{}).map(([key,value])=><div key={key} className="rounded-lg bg-slate-50 p-3"><dt className="text-xs capitalize text-slate-500">{key.replace('_',' ')}</dt><dd className="font-semibold">{value}/5</dd></div>)}</dl>}</article>
      <section className={card}><h3 className="font-bold">Case notes</h3><p className="mt-1 text-xs text-slate-500">Private notes stay in the provider workspace. Enter a separate plain-language update only when you want the employee to see it.</p><div className="mt-3 space-y-2"><textarea className="min-h-24 w-full rounded-lg border p-3" placeholder="Private care note" value={privateNote} onChange={e=>setPrivateNote(e.target.value)}/><textarea className="min-h-20 w-full rounded-lg border p-3" placeholder="Optional employee-safe update" value={employeeUpdate} onChange={e=>setEmployeeUpdate(e.target.value)}/><button disabled={busy||!privateNote.trim()} onClick={()=>void saveNote()} className={button}>Save case note</button></div>{detail.notes.map(note=><article key={note.id} className="mt-3 rounded-lg bg-slate-50 p-3 text-sm"><time className="text-xs text-slate-500">{new Date(note.created_at).toLocaleString()}</time><p className="mt-1"><strong>Private:</strong> {note.private_note}</p>{note.employee_update&&<p className="mt-1 text-teal-900"><strong>Shared:</strong> {note.employee_update}</p>}</article>)}</section>
      <section className={card}><h3 className="font-bold">Private communication</h3><div className="mt-3 max-h-52 space-y-2 overflow-y-auto">{messages.map(m=><p key={m.id} className={`max-w-[90%] rounded-xl p-3 text-sm ${m.from_me?'ml-auto bg-teal-50':'bg-slate-50'}`}>{m.message}<time className="mt-1 block text-[10px] text-slate-500">{new Date(m.created_at).toLocaleString()}</time></p>)}</div>{detail.case.status==='open'&&<div className="mt-3 flex flex-col gap-2 sm:flex-row"><input className="min-w-0 flex-1 rounded-lg border p-3" value={reply} onChange={e=>setReply(e.target.value)} placeholder="Message the employee"/><button className={button} disabled={busy||!reply.trim()} onClick={()=>void sendReply()}>Send</button></div>}</section>
      {detail.case.status==='open'&&<section className={card}><h3 className="font-bold">Schedule an appointment</h3><div className="mt-3 grid gap-3 sm:grid-cols-2"><input type="datetime-local" className="rounded-lg border p-3" value={appointment.starts_at} onChange={e=>setAppointment({...appointment,starts_at:e.target.value})}/><select className="rounded-lg border p-3" value={appointment.mode} onChange={e=>setAppointment({...appointment,mode:e.target.value})}><option value="online">Online</option><option value="physical">In person</option></select><input className="rounded-lg border p-3 sm:col-span-2" placeholder={appointment.mode==='online'?'Secure HTTPS meeting link':'Meeting location'} value={appointment.location_or_link} onChange={e=>setAppointment({...appointment,location_or_link:e.target.value})}/></div><button className={`${button} mt-3`} disabled={busy||!appointment.starts_at||!appointment.location_or_link} onClick={()=>void schedule()}>Schedule and notify</button></section>}
      {notice&&<p role="status" className="rounded-xl bg-slate-100 p-3 text-sm">{notice}</p>}{detail.case.status==='open'&&<button onClick={()=>void close()} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800">Close support case</button>}</div>:<div className={`${card} flex items-center justify-center text-center text-sm text-slate-500`}>Select a shared case to review consented information and provide support.</div>}</section>
}

function EmployeeMessagesPage(){
  const [cases,setCases]=useState<Array<{id:string;status:string;created_at:string}>>([]);const [caseId,setCaseId]=useState('');const [messages,setMessages]=useState<Array<{id:string;from_me:boolean;message:string;created_at:string}>>([]);const [draft,setDraft]=useState('');const [notice,setNotice]=useState('')
  const load=async()=>{try{const [c,m]=await Promise.all([api.get('/v1/workplace/support-requests'),api.get('/v1/workplace/support/messages')]);const active=c.data.filter((item:{status:string})=>['open','active'].includes(item.status));setCases(active);setCaseId((current:string)=>active.some((item:{id:string})=>item.id===current)?current:active[0]?.id||'');setMessages(m.data)}catch(e){setNotice(e instanceof Error?e.message:'Unable to load private messages.')}}
  useEffect(()=>{let active=true;const refresh=()=>Promise.all([api.get('/v1/workplace/support-requests'),api.get('/v1/workplace/support/messages')]).then(([c,m])=>{if(!active)return;const activeCases=c.data.filter((item:{status:string})=>['open','active'].includes(item.status));setCases(activeCases);setCaseId(current=>activeCases.some((item:{id:string})=>item.id===current)?current:activeCases[0]?.id||'');setMessages(m.data)}).catch(e=>{if(active)setNotice(e instanceof Error?e.message:'Unable to load private messages.')});void refresh();const timer=window.setInterval(()=>void refresh(),15000);return()=>{active=false;window.clearInterval(timer)}},[])
  const send=async()=>{if(!caseId||!draft.trim())return;try{await api.post('/v1/workplace/support/messages',{case_id:caseId,message:draft});setDraft('');await load()}catch(e){setNotice(e instanceof Error?e.message:'Unable to send message.')}}
  return <main className="mx-auto max-w-4xl space-y-5"><header><p className="text-xs font-bold uppercase tracking-widest text-teal-700">Private care communication</p><h1 className="mt-1 text-3xl font-bold">Messages with your provider</h1><p className="mt-2 text-sm text-slate-600">These messages are visible only to you and the independent provider for the support case you opened. Your employer cannot read them.</p></header>{!cases.length?<section className={card}>There is no active shared support case yet. Request support and explicitly share information with a provider to open a private conversation.</section>:<section className={card}><label className="text-sm font-semibold">Support request<select className="mt-1 block w-full rounded-lg border p-3" value={caseId} onChange={e=>setCaseId(e.target.value)}>{cases.map(c=><option key={c.id} value={c.id}>Request from {new Date(c.created_at).toLocaleDateString()} · {c.status}</option>)}</select></label><div className="mt-4 max-h-[55vh] min-h-48 space-y-3 overflow-y-auto rounded-xl bg-slate-50 p-4" aria-live="polite">{messages.filter(m=>m.created_at).map(m=><article key={m.id} className={`max-w-[88%] rounded-xl p-3 text-sm ${m.from_me?'ml-auto bg-teal-100':'bg-white shadow-sm'}`}><p>{m.message}</p><time className="mt-1 block text-[10px] text-slate-500">{new Date(m.created_at).toLocaleString()}</time></article>)}</div><div className="mt-3 flex flex-col gap-2 sm:flex-row"><input className="min-w-0 flex-1 rounded-lg border p-3" value={draft} onChange={e=>setDraft(e.target.value)} placeholder="Write a private message"/><button className={button} disabled={!draft.trim()||!caseId} onClick={()=>void send()}>Send message</button></div></section>}{notice&&<p role="status" className="rounded-xl bg-slate-100 p-3 text-sm">{notice}</p>}</main>
}

function ProviderAppointmentsPage(){
  const [items,setItems]=useState<Array<{id:string;starts_at:string;mode:string;location_or_link?:string;status:string;employee_name:string}>>([]);const [notice,setNotice]=useState('')
  const load=async()=>{try{setItems((await api.get('/v1/workplace/provider/appointments')).data)}catch(e){setNotice(e instanceof Error?e.message:'Unable to load appointments.')}}
  useEffect(()=>{let active=true;api.get('/v1/workplace/provider/appointments').then(({data})=>{if(active)setItems(data)}).catch(e=>{if(active)setNotice(e instanceof Error?e.message:'Unable to load appointments.')});return()=>{active=false}},[])
  const update=async(id:string,status:'completed'|'cancelled')=>{try{await api.post(`/v1/workplace/provider/appointments/${id}/status`,{status});await load()}catch(e){setNotice(e instanceof Error?e.message:'Unable to update appointment.')}}
  return <main className="mx-auto max-w-5xl space-y-5"><header><p className="text-xs font-bold uppercase tracking-widest text-teal-700">Independent provider workspace</p><h1 className="mt-1 text-3xl font-bold">Workplace appointments</h1><p className="mt-2 text-sm text-slate-600">Appointments appear only to the employee and their active independent provider.</p></header>{items.length===0?<section className={card}>No appointments have been scheduled.</section>:items.map(item=><article key={item.id} className={card}><div className="flex flex-wrap justify-between gap-3"><div><h2 className="font-bold">{item.employee_name}</h2><p className="text-sm text-slate-600">{new Date(item.starts_at).toLocaleString()} · {item.mode==='online'?'Online':'In person'}</p>{item.location_or_link&&<p className="mt-1 break-all text-sm">{item.location_or_link}</p>}</div><span className="text-sm font-semibold capitalize">{item.status}</span></div>{item.status==='scheduled'&&<div className="mt-3 flex gap-2"><button onClick={()=>void update(item.id,'completed')} className={button}>Mark completed</button><button onClick={()=>void update(item.id,'cancelled')} className="rounded-xl border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800">Cancel</button></div>}</article>)}{notice&&<p role="status" className="rounded-xl bg-slate-100 p-3 text-sm">{notice}</p>}</main>
}

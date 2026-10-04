import { useCallback, useEffect, useState } from 'react'
import api from '../api/client'
import { useAuthStore } from '../store'
import { useUiStore } from '../store/uiStore'
import { setToken } from '../lib/tokenStorage'
import { acceptTerms } from '../api/auth'
import WorkplaceInsightsDashboard, { type Insights } from '../components/workplace/WorkplaceInsightsDashboard'
import { WorkplaceStatus } from '../components/workplace/WorkplaceStatus'
import { workplaceStatusLabel } from '../components/workplace/workplaceStatusUtils'
import WorkplaceAppointmentsPage from '../components/workplace/WorkplaceAppointmentsPage'
import { CompanyOverview, ProviderOverview, WorkerOverview } from '../components/workplace/WorkplaceHome'
import WorkplaceConfirmDialog from '../components/workplace/WorkplaceConfirmDialog'
type Provider = { id: string; name: string; title?: string; status?: string; association_status?: string }
type ManagedProvider = {id:string;name:string;email:string;credential_status:string;credential_valid:boolean;expires_at?:string|null;expires_soon?:boolean;access_status:string;availability:string;professional_type?:string|null;title?:string;license_state?:string|null;demo_only?:boolean;associations:Array<{id:string;name:string;status:string}>;pending_reviews:Array<{id:string;professional_type?:string|null;title:string;qualification:string;registration_number:string;license_state?:string|null;submitted_at:string}>}
type CommercialView = {status:string;plan_key:string;plan_name:string;pilot_state:string|null;contract_start_date:string|null;contract_end_date:string|null;billing_cycle:string|null;population_band:string;renewal_date:string|null;grace_period_end:string|null;cancellation_effective_date:string|null;terminated_at:string|null;renewal_state:string|null;action_required:boolean;enabled_capabilities:Record<string,boolean>;internal_reference?:string|null;internal_notes?:string|null;cancellation_reason?:string|null;external_customer_reference?:string|null;external_subscription_reference?:string|null;billing_provider?:string|null;administrator_limit?:number|null;provider_limit?:number|null}
type OffboardingView = {status:string;effective_date?:string|null;retention_deadline?:string|null;continuity_deadline?:string|null;active_support_obligations?:number;provider_relationships_ending_or_ended?:number;completion_ready?:boolean;message?:string;commercial_status?:string|null}

const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm'
const button = 'rounded-xl bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-50'
const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function validateCompanyProvisioning(input: { name: string; adminName: string; adminEmail: string; domains: string; privacyContact: string; retentionDays: number }) {
  const domains = [...new Set(input.domains.split(',').map(domain => domain.trim().toLowerCase().replace(/^@/, '')).filter(Boolean))]
  if (input.name.trim().length < 2) return 'Enter a company name with at least 2 characters.'
  if (input.adminName.trim().length < 2) return 'Enter the first administrator’s full name.'
  if (!emailPattern.test(input.adminEmail.trim())) return 'Enter a valid first administrator email address.'
  if (!domains.length || domains.some(domain => !/^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(domain))) return 'Enter one or more valid organization-owned email domains, separated by commas.'
  if (!domains.includes(input.adminEmail.trim().toLowerCase().split('@').pop() || '')) return 'The first administrator’s email must use one of the approved work domains.'
  if (!emailPattern.test(input.privacyContact.trim())) return 'Enter a valid company privacy contact email address.'
  if (!Number.isInteger(input.retentionDays) || input.retentionDays < 30 || input.retentionDays > 3650) return 'Choose a retention period between 30 and 3,650 days.'
  return ''
}

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
    'Live customer enrollment requires the company’s privacy review and an approved provider. Demo workspaces are clearly marked and kept separate.',
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
  const signedInUser = useAuthStore(s => s.user)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [accepted, setAccepted] = useState(false)
  const [acceptedWorkplaceTerms, setAcceptedWorkplaceTerms] = useState(false)
  const [challenge, setChallenge] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [existingJoin, setExistingJoin] = useState(false)
  const [joinInfo, setJoinInfo] = useState<{company_name:string;demo_mode:boolean}|null>(null)
  const token = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token') || new URLSearchParams(window.location.search).get('token') || ''

  useEffect(() => {
    if (!token) return
    let active = true
    api.get(`/v1/workplace/enrollment/resolve?token=${encodeURIComponent(token)}`)
      .then(({data}) => { if (active) setJoinInfo(data) })
      .catch(() => { if (active) setJoinInfo(null) })
    return () => { active = false }
  }, [token])

  const start = async () => {
    setBusy(true); setMessage('')
    try {
      const res = existingJoin
        ? await api.post('/v1/workplace/enrollment/existing/start', { token, accepted_notice: accepted, accepted_workplace_terms: acceptedWorkplaceTerms })
        : await api.post('/v1/workplace/enrollment/start', { token, name, email, password, accepted_notice: accepted, accepted_workplace_terms: acceptedWorkplaceTerms })
      setChallenge(res.data.challenge_id)
      setMessage(res.data.message)
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Could not start enrollment.') }
    finally { setBusy(false) }
  }
  const verify = async () => {
    setBusy(true); setMessage('')
    try {
      const result = await api.post(existingJoin ? '/v1/workplace/enrollment/existing/verify' : '/v1/workplace/enrollment/verify', { challenge_id: challenge, code })
      setToken(result.data.access_token)
      setMessage('Your work email is verified. Taking you to your private wellbeing space…')
      window.setTimeout(() => { window.location.href = '/' }, 1800)
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Verification failed.') }
    finally { setBusy(false) }
  }
  if (!token) return <div className="mx-auto mt-16 max-w-xl rounded-2xl bg-white p-8 text-center shadow">This enrollment link is missing. Ask your workplace administrator for a current shared link.</div>
  return <main className="min-h-screen bg-slate-50 px-4 py-12"><section className="mx-auto max-w-xl space-y-5">
    <header><p className="text-sm font-bold uppercase tracking-widest text-teal-700">MindGuard workplace{joinInfo?.demo_mode?' · demo':''}</p><h1 className="mt-2 text-3xl font-bold text-slate-900">Your choice, your private space</h1><p className="mt-3 text-slate-600">Participation is voluntary. Your employer cannot see whether you join, your check-ins, support requests, appointments, or notes.</p>{joinInfo?.demo_mode&&<p className="mt-3 rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900"><strong>Demo workspace.</strong> Use test information only. The sample counsellor is not a real provider and this demo is not monitored for care.</p>}</header>
    <div className={card}>
      {!challenge ? <div className="space-y-4">{signedInUser?.role_type === 'student' && signedInUser.user_category === 'adult' && !existingJoin && <button type="button" className="text-sm font-semibold text-teal-800 underline" onClick={() => setExistingJoin(true)}>Already have a MindGuard account? Verify your registered email to join</button>}{existingJoin ? <p className="rounded-lg bg-teal-50 p-3 text-sm text-teal-900">We’ll send a one-time code to your registered MindGuard email. Your account will be connected to this workplace without creating a duplicate account.</p> : <><label className="block text-sm font-medium">Name<input className="mt-1 w-full rounded-lg border p-3" value={name} onChange={e => setName(e.target.value)} autoComplete="name" /></label>
        <label className="block text-sm font-medium">{joinInfo?.demo_mode?'Email address to verify':'Approved company email'}<input type="email" className="mt-1 w-full rounded-lg border p-3" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" /><span className="mt-1 block text-xs font-normal text-slate-500">{joinInfo?.demo_mode?'Use an inbox you can access; no company domain is needed.':'Use an email address from your company’s approved domain.'}</span></label>
        <label className="block text-sm font-medium">Create a password<input type="password" className="mt-1 w-full rounded-lg border p-3" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" /></label></>}
        <label className="flex gap-3 text-sm text-slate-700"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} className="mt-1" /><span>I understand the notice: check-ins are private to me. My employer only sees fixed, broad group summaries when at least 10 distinct employees have responded. A provider sees information only if I request support and explicitly share it. I can withdraw from the programme.</span></label>
        <label className="flex gap-3 text-sm text-slate-700"><input type="checkbox" checked={acceptedWorkplaceTerms} onChange={e => setAcceptedWorkplaceTerms(e.target.checked)} className="mt-1" /><span>I agree to the workplace participation terms: enrollment is voluntary, my employer does not see my individual records, and information is shared with a provider only when I request support and choose to share.</span></label>
        <button disabled={busy || (!existingJoin && (!name || !email || password.length < 10)) || !accepted || !acceptedWorkplaceTerms} className={button} onClick={start}>{busy ? 'Sending verification…' : existingJoin ? 'Verify and join workplace' : 'Verify email and join'}</button>
      </div> : <div className="space-y-4"><h2 className="text-xl font-semibold">Check your work email</h2><p className="text-sm text-slate-600">Enter the six-digit code we sent. It expires in 15 minutes.</p><input inputMode="numeric" autoComplete="one-time-code" maxLength={6} className="w-full rounded-lg border p-3 tracking-[0.35em]" value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} /><button disabled={busy || code.length !== 6} className={button} onClick={verify}>{busy ? 'Verifying…' : 'Verify and finish'}</button></div>}
      {message && <p role="status" className="mt-4 text-sm text-slate-700">{message}</p>}
    </div>
    <p className="text-xs leading-relaxed text-slate-500">MindGuard is not emergency care. In the United States, call 911 for immediate danger. For crisis support, call or text 988 or chat at 988lifeline.org. Demo accounts are not monitored for support.</p>
  </section></main>
}

export default function WorkplacePage() {
  const user = useAuthStore(s => s.user)
  const currentPage = useUiStore(s => s.currentPage)
  const setPage = useUiStore(s => s.setPage)
  const role = user?.role_type
  const isCompanyAdmin = role === 'company_admin'
  const isProvider = role === 'workplace_provider'
  const [insights, setInsights] = useState<Insights | null>(null)
  const [insightsError, setInsightsError] = useState('')
  const [providers, setProviders] = useState<Provider[]>([])
  const [providerId, setProviderId] = useState('')
  const [companyProviders, setCompanyProviders] = useState<Provider[]>([])
  const [enrollmentLinks, setEnrollmentLinks] = useState<Array<{id:string;created_at:string;active:boolean;expires_at?:string|null;revoked_at?:string|null}>>([])
  const [providerEmail, setProviderEmail] = useState('')
  const [link, setLink] = useState('')
  const [linkId, setLinkId] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmation, setConfirmation] = useState<{message:string;resolve:(confirmed:boolean)=>void}|null>(null)
  const [checkin, setCheckin] = useState({ mood: 3, stress: 3, support_access: 3 })
  const [shareConfirmed, setShareConfirmed] = useState(false)
  const [checkinHistory, setCheckinHistory] = useState<Array<{id:string;answers:Record<string,number>;created_at:string}>>([])
  const [supportHistory, setSupportHistory] = useState<Array<{id:string;status:string;assignment_status?:string;created_at:string}>>([])
  const [supportUpdates, setSupportUpdates] = useState<Array<{id:string;message:string;shared_at:string}>>([])
  const [setup, setSetup] = useState<{company:{id:string;name:string;status:string;demo_mode?:boolean};demo_mode?:boolean;commercial?:CommercialView;readiness:string;current_admin_role:'owner'|'admin';approved_domains:string[];checklist:Record<string,boolean>;administrators:Array<{id:string;name:string;email:string;status:string;workplace_admin_role:'owner'|'admin';invitation_state:string}>;policy:{privacy_notice_version:string;privacy_contact_email:string;employee_population_range?:string;retention_days:number;status:string}}|null>(null)
  const [setupLoading, setSetupLoading] = useState(isCompanyAdmin)
  const [workerLoading, setWorkerLoading] = useState(!isCompanyAdmin&&!isProvider)
  const [workerError, setWorkerError] = useState('')
  const [workerContext, setWorkerContext] = useState<{company_name:string;demo_mode:boolean}|null>(null)
  const [setupError, setSetupError] = useState('')
  const [offboarding, setOffboarding] = useState<OffboardingView | null>(null)
  const [audit, setAudit] = useState<Array<{event_type:string;occurred_at:string}>>([])
  const [adminInvite, setAdminInvite] = useState({name:'',email:''})
  const [domainDraft, setDomainDraft] = useState('')
  const [ownershipTarget, setOwnershipTarget] = useState('')
  const [policy, setPolicy] = useState({privacy_contact_email:'',employee_population_range:'',retention_days:90,privacy_notice_version:'v1',confirm_aggregate_only:false})
  const confirmAction = (message:string) => new Promise<boolean>(resolve => setConfirmation({message,resolve}))
  const refresh = useCallback(async () => {
    try {
      if (isCompanyAdmin) {
        setSetupLoading(true); setSetupError('')
        const results = await Promise.allSettled([
          api.get('/v1/workplace/admin/providers'), api.get('/v1/workplace/admin/enrollment-links'),
          api.get('/v1/workplace/admin/setup'), api.get('/v1/workplace/admin/audit'),
          api.get('/v1/workplace/admin/offboarding-status'), api.get('/v1/workplace/admin/insights'),
        ] as const)
        const [providerResult, linkResult, setupResult, auditResult, offboardingResult, insightsResult] = results
        if (providerResult.status === 'fulfilled') setCompanyProviders(providerResult.value.data)
        if (linkResult.status === 'fulfilled') setEnrollmentLinks(linkResult.value.data)
        if (auditResult.status === 'fulfilled') setAudit(auditResult.value.data)
        if (offboardingResult.status === 'fulfilled') setOffboarding(offboardingResult.value.data)
        if (insightsResult.status === 'fulfilled') { setInsights(insightsResult.value.data); setInsightsError('') }
        else setInsightsError(insightsResult.reason instanceof Error ? insightsResult.reason.message : 'Workplace Insights are unavailable. Check commercial and workplace status.')
        if (setupResult.status === 'rejected') throw setupResult.reason
        setSetup(setupResult.value.data)
        setPolicy(current => ({ ...current, privacy_contact_email: setupResult.value.data.policy?.privacy_contact_email || '', employee_population_range: setupResult.value.data.policy?.employee_population_range || '', retention_days: setupResult.value.data.policy?.retention_days ?? 365, privacy_notice_version: setupResult.value.data.policy?.privacy_notice_version || 'v1' }))
        if (results.some(result => result.status === 'rejected')) setNotice('Some company workspace information could not be loaded. Setup is available; retry to refresh the other panels.')
      }
      else if (!isProvider) {
        setWorkerLoading(true); setWorkerError('')
        const [providerResult, checkinResult, supportResult, contextResult] = await Promise.all([
          api.get('/v1/workplace/providers'), api.get('/v1/workplace/checkins'), api.get('/v1/workplace/support-requests'), api.get('/v1/workplace/member/context'),
        ])
        setProviders(providerResult.data); setCheckinHistory(checkinResult.data); setSupportHistory(supportResult.data)
        setWorkerContext(contextResult.data)
        const updateResult = await api.get('/v1/workplace/support-updates')
        setSupportUpdates(updateResult.data)
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Unable to load this workspace.'
      setNotice(message)
      if (isCompanyAdmin) setSetupError(message)
      else if (!isProvider) setWorkerError(message)
    } finally {
      if (isCompanyAdmin) setSetupLoading(false)
      if (!isCompanyAdmin&&!isProvider) setWorkerLoading(false)
    }
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
    if (!await confirmAction('Deactivate this provider for the company? They will lose access to this company’s workplace cases.')) return
    try { await api.post(`/v1/workplace/admin/providers/${id}/deactivate`); setNotice('Provider deactivated.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to deactivate provider.') }
  }
  const revokeLink = async () => {
    if (!linkId || !await confirmAction('Revoke this shared enrollment link? Anyone who has it will no longer be able to join.')) return
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
    if (!await confirmAction('Withdraw from the workplace programme? Future check-ins stop and provider access is revoked.')) return
    try { await api.post('/v1/workplace/withdraw'); setNotice('Participation withdrawn. Sign out to finish.') }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to withdraw.') }
  }
  const inviteAdministrator = async () => {
    setBusy(true); setNotice('')
    try { await api.post('/v1/workplace/admin/administrators', adminInvite); setAdminInvite({name:'',email:''}); setNotice('Company administrator invitation sent.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to invite administrator.') }
    finally { setBusy(false) }
  }
  const addDomain = async () => {
    setBusy(true); setNotice('')
    try { await api.post('/v1/workplace/admin/domains', {domain:domainDraft}); setDomainDraft(''); setNotice('Approved work domain added for future enrollment.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to add domain.') }
    finally { setBusy(false) }
  }
  const removeDomain = async (domain:string) => {
    if (!await confirmAction(`Remove ${domain} from approved domains? This affects future enrollment only; existing workplace relationships are unchanged.`)) return
    setBusy(true); setNotice('')
    try { await api.delete('/v1/workplace/admin/domains', {data:{domain}}); setNotice('Domain removed. Existing worker relationships were not changed.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to remove domain.') }
    finally { setBusy(false) }
  }
  const resendAdministrator = async (id:string) => {
    setBusy(true); setNotice('')
    try { await api.post(`/v1/workplace/admin/administrators/${id}/resend`); setNotice('A fresh invitation was sent. Earlier invitation links are no longer valid.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to resend invitation.') }
    finally { setBusy(false) }
  }
  const removeAdministrator = async (id:string, pending:boolean) => {
    if (!await confirmAction(pending ? 'Revoke this pending invitation? Its link will stop working immediately.' : 'Remove this company administrator? Their company access will end immediately.')) return
    setBusy(true); setNotice('')
    try { await api.delete(`/v1/workplace/admin/administrators/${id}`); setNotice(pending ? 'Invitation revoked.' : 'Administrator removed.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to remove administrator.') }
    finally { setBusy(false) }
  }
  const transferOwnership = async () => {
    if (!ownershipTarget || !await confirmAction('Transfer company ownership? You will remain an administrator but lose owner-only controls.')) return
    setBusy(true); setNotice('')
    try { await api.post('/v1/workplace/admin/ownership/transfer', {administrator_id:ownershipTarget}); setOwnershipTarget(''); setNotice('Company ownership transferred.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to transfer ownership.') }
    finally { setBusy(false) }
  }
  const savePolicy = async () => {
    setBusy(true); setNotice('')
    try { await api.put('/v1/workplace/admin/policy', policy); setNotice('Privacy and retention policy approved and saved.'); await refresh() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to save workplace policy.') }
    finally { setBusy(false) }
  }

  if (role === 'workplace_employee' && currentPage === 'workplace-messages') return <EmployeeMessagesPage />
  if ((isProvider||role==='workplace_employee') && currentPage === 'workplace-appointments') return <WorkplaceAppointmentsPage />
  if (isProvider && currentPage === 'workplace') return <ProviderOverview onNavigate={setPage}/>

  const companySetupSteps = setup?.demo_mode ? [
    { key: 'workplace_terms', title: 'Accept administrator terms', detail: 'Confirm the privacy rules for managing this demo.', page: null },
    { key: 'provider', title: 'Sample counsellor included', detail: 'A fictional sample provider is already connected for walkthrough purposes.', page: 'workplace-providers' as const },
    { key: 'enrollment_link', title: 'Create a test enrollment link', detail: 'Share the link with a test email inbox you can access. Company domains are not needed.', page: 'workplace-enrollment' as const },
  ] : [
    { key: 'company_profile', title: 'Company profile', detail: 'Your company workspace is set up and associated with this administrator.', page: null },
    { key: 'workplace_terms', title: 'Workplace administrator terms', detail: 'Accept the rules for protecting employee privacy.', page: null },
    { key: 'privacy_contact', title: 'Privacy contact', detail: 'Set a company contact for privacy questions.', page: 'workplace-setup' as const },
    { key: 'domains', title: 'Approved company email domains', detail: 'Add a domain the company owns so workers can verify their company email.', page: 'workplace-setup' as const },
    { key: 'policy', title: 'Workplace policy', detail: 'Set retention and notice information and confirm group-only employer reporting.', page: 'workplace-setup' as const },
    { key: 'provider', title: 'Provider review', detail: 'For a real launch, MindGuard records a human review of a provider’s state license.', page: 'workplace-providers' as const },
    { key: 'privacy_review', title: 'US privacy and legal review', detail: 'MindGuard records that the company’s qualified privacy/legal review is complete before live enrollment.', page: null },
    { key: 'enrollment_link', title: 'Employee enrollment', detail: 'Create a revocable shared link after launch checks are complete.', page: 'workplace-enrollment' as const },
  ]
  const firstIncompleteStep = companySetupSteps.find(step => !setup?.checklist?.[step.key])
  const policyValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(policy.privacy_contact_email.trim())
    && policy.employee_population_range.trim().length > 0
    && policy.retention_days >= 30 && policy.retention_days <= 3650
    && policy.privacy_notice_version.trim().length >= 3
  const privacyContactInvalid = Boolean(policy.privacy_contact_email) && !emailPattern.test(policy.privacy_contact_email.trim())
  const canCreateEnrollmentLink = Boolean(setup?.demo_mode
    ? setup.checklist.administrator && setup.checklist.workplace_terms && setup.checklist.provider
    : setup?.checklist.privacy_review && setup.checklist.policy && setup.checklist.provider && setup.checklist.administrator && setup.checklist.domains && setup.checklist.privacy_contact && setup.checklist.workplace_terms)
  const pageTitle = currentPage==='workplace-cases'?'Shared workplace cases':currentPage==='workplace-plan'?'Plan & subscription':currentPage==='workplace-setup'?'Setup & privacy':currentPage==='workplace-providers'?'Independent providers':currentPage==='workplace-enrollment'?'Employee enrollment':currentPage==='workplace-reports'?'Workplace Insights':currentPage==='workplace-audit'?'Audit history':currentPage==='workplace-checkins'?'Private check-ins':currentPage==='workplace-support'?'Request support':currentPage==='workplace-appointments'?'Appointments':'Workplace overview'
  const pageContext = isCompanyAdmin?'Company workspace':isProvider?'Independent provider workspace':'Your private wellbeing space'
  const pageDescription = isCompanyAdmin?'Manage programme readiness and organization-wide information. This workspace never exposes employee identities or individual wellbeing data.':isProvider?'Only employees who explicitly request support and share information with you appear in this provider workspace.':'Your participation is voluntary. Your employer receives aggregated organizational insights, not your individual wellbeing information.'

  if (isCompanyAdmin && setup?.demo_mode && currentPage === 'workplace-setup') return <main className="mx-auto w-full max-w-5xl space-y-6 text-slate-900"><header><p className="text-xs font-bold uppercase tracking-widest text-emerald-700">Demo company workspace</p><h1 className="mt-1 text-3xl font-bold">Setup & privacy</h1><p className="mt-2 text-slate-600">The demo is preconfigured. No company domain, license paperwork, or legal-review documents are needed to explore it.</p></header><section className="rounded-xl border border-sky-200 bg-sky-50 p-5 text-sky-950"><h2 className="font-semibold">Use test information only</h2><p className="mt-2 text-sm">A fictional sample counsellor is included, but is not a real provider and does not monitor requests. Demo workplaces cannot be converted to customer accounts.</p><button className={`${button} mt-4`} onClick={()=>setPage('workplace-enrollment')}>Continue to test enrollment</button></section></main>

  if (isCompanyAdmin && setup?.demo_mode && currentPage === 'workplace-providers') return <main className="mx-auto w-full max-w-5xl space-y-6 text-slate-900"><header><p className="text-xs font-bold uppercase tracking-widest text-emerald-700">Demo company workspace</p><h1 className="mt-1 text-3xl font-bold">Sample provider</h1><p className="mt-2 text-slate-600">A fictional counsellor is preconnected so you can explore the worker flow without collecting license documents.</p></header><section className="rounded-xl border border-sky-200 bg-sky-50 p-5"><p className="font-semibold text-sky-950">Demo only · not a real licensed provider</p><p className="mt-2 text-sm text-sky-900">Do not use this profile for real support. Demo requests are not monitored. Real customer workplaces require a human review of the provider’s state license.</p>{companyProviders.map(provider=><p key={provider.id} className="mt-4 rounded-lg bg-white p-3 text-sm"><strong>{provider.name}</strong>{provider.title?` · ${provider.title}`:''} · Demo sample</p>)}</section></main>

  if (isCompanyAdmin && setup?.demo_mode && currentPage === 'workplace-enrollment') return <main className="mx-auto w-full max-w-5xl space-y-6 text-slate-900"><header><p className="text-xs font-bold uppercase tracking-widest text-emerald-700">Demo company workspace</p><h1 className="mt-1 text-3xl font-bold">Test enrollment</h1><p className="mt-2 text-slate-600">Create a 90-day link and try joining with an email inbox you can access. No company domain is needed; the email verification code still confirms inbox access.</p></header><section className={card}><div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-950"><strong>Demo only.</strong> Use test information. The sample counsellor and support experience are not real care and are not monitored.</div><button className={`${button} mt-4`} disabled={busy||setupLoading||!canCreateEnrollmentLink} onClick={createLink}>{busy?'Creating…':'Create and copy test enrollment link'}</button>{link&&<div className="mt-4 space-y-2"><label className="block text-sm font-medium">Copy this test link<textarea readOnly className="mt-1 min-h-24 w-full break-all rounded-lg border bg-slate-50 p-3 text-sm" value={link}/></label><button className="text-sm font-semibold text-rose-700 underline" onClick={revokeLink}>Revoke this link</button></div>}{enrollmentLinks.length>0&&<div className="mt-5 border-t pt-4"><h2 className="font-semibold">Link history</h2><ul className="mt-2 divide-y">{enrollmentLinks.map(item=><li key={item.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm"><span>{item.active?'Active':'Inactive'} · created {new Date(item.created_at).toLocaleDateString()}{item.expires_at?` · expires ${new Date(item.expires_at).toLocaleDateString()}`:''}</span>{item.active&&<button className="font-semibold text-rose-700 underline" onClick={async()=>{if(!await confirmAction('Revoke this demo enrollment link?'))return;try{await api.post(`/v1/workplace/admin/enrollment-link/${item.id}/revoke`);setNotice('Demo enrollment link revoked.');await refresh()}catch(e){setNotice(e instanceof Error?e.message:'Unable to revoke link.')}}}>Revoke</button>}</li>)}</ul></div>}{notice&&<p role="status" className="mt-4 rounded-lg bg-slate-100 p-3 text-sm">{notice}</p>}</section></main>

  return <main className="mx-auto w-full max-w-5xl space-y-6 text-slate-900">
    <header><p className="text-xs font-bold uppercase tracking-widest text-emerald-700">{pageContext}</p><h1 className="mt-1 text-3xl font-bold">{pageTitle}</h1>
      <p className="mt-2 max-w-3xl text-slate-600">{pageDescription}</p></header>
    {isCompanyAdmin&&setup?.demo_mode&&<section role="status" className="rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-950"><p className="font-semibold">Demo workplace · synthetic provider · test information only</p><p className="mt-1">No company domain or licensing documents are needed here. This workspace is not a real customer programme, is not monitored for care, and cannot be converted into a live workplace.</p></section>}
    {!isCompanyAdmin&&!isProvider&&workerContext?.demo_mode&&<section role="status" className="rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-950"><p className="font-semibold">Demo workplace · test information only</p><p className="mt-1">You joined {workerContext.company_name} for a product walkthrough. This is not a live customer programme; the sample provider is fictional and support requests are not monitored. Do not enter real wellbeing information.</p></section>}
    {isCompanyAdmin&&setupError&&<div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"><span>{setupError}</span><button className="font-semibold underline focus-visible:outline focus-visible:outline-2" onClick={()=>void refresh()}>Retry loading workplace</button></div>}
    {isCompanyAdmin&&currentPage==='workplace'&&<CompanyOverview companyName={setup?.company.name} companyStatus={setup?.company.status} readiness={setup?.readiness} loading={setupLoading} providerReady={Boolean(setup?.checklist.provider)} enrollmentReady={canCreateEnrollmentLink} activeLink={enrollmentLinks.some(item=>item.active)} commercial={setup?.commercial} pendingInvites={setup?.administrators.filter(item=>['pending','invited'].includes(item.status.toLowerCase())).length||0} offboarding={offboarding} nextAction={firstIncompleteStep?{title:firstIncompleteStep.title,page:firstIncompleteStep.page}:null} insightsState={insights?.state} onNavigate={setPage}/>}
    {!isCompanyAdmin&&!isProvider&&currentPage==='workplace'&&(workerError?<div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"><span>{workerError}</span><button className="font-semibold underline" onClick={()=>void refresh()}>Retry</button></div>:workerLoading?<div role="status" className={`${card} animate-pulse text-sm text-slate-500`}>Loading your private workplace…</div>:<WorkerOverview checkins={checkinHistory} cases={supportHistory} providers={providers} onNavigate={setPage}/>)}
    {isCompanyAdmin&&currentPage==='workplace-plan'&&setup?.commercial&&<section className={card} aria-labelledby="commercial-status-title"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-wider text-emerald-700">Plan & subscription</p><h2 id="commercial-status-title" className="text-xl font-semibold">{setup.commercial.plan_name}</h2><p className="mt-1 text-sm text-slate-600">{setup.commercial.contract_start_date||'Start date not recorded'}{setup.commercial.contract_end_date?` – ${setup.commercial.contract_end_date}`:' · no end date recorded'}</p></div><WorkplaceStatus value={setup.commercial.status} label={setup.commercial.pilot_state||undefined}/></div><div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div className="rounded-xl bg-slate-50 p-3"><p className="text-xs uppercase text-slate-500">Workforce band</p><p className="mt-1 font-semibold">{setup.commercial.population_band}</p></div><div className="rounded-xl bg-slate-50 p-3"><p className="text-xs uppercase text-slate-500">Billing cycle</p><p className="mt-1 font-semibold capitalize">{setup.commercial.billing_cycle?.replaceAll('_',' ')||'To be agreed'}</p></div><div className="rounded-xl bg-slate-50 p-3"><p className="text-xs uppercase text-slate-500">Renewal</p><p className="mt-1 font-semibold">{setup.commercial.renewal_date||'Not scheduled'}</p></div><div className="rounded-xl bg-slate-50 p-3"><p className="text-xs uppercase text-slate-500">Enabled services</p><p className="mt-1 font-semibold">{[setup.commercial.enabled_capabilities.enrollment&&'Enrollment',setup.commercial.enabled_capabilities.aggregate_analytics&&'Aggregate insights',setup.commercial.enabled_capabilities.provider_services&&'Provider support'].filter(Boolean).join(' · ')||'No premium services'}</p></div></div>{setup.commercial.action_required&&<p role="status" className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">{workplaceStatusLabel(setup.commercial.status)}{setup.commercial.grace_period_end?` through ${setup.commercial.grace_period_end}`:''}. Contact your MindGuard representative if this status is unexpected.</p>}</section>}
    {isCompanyAdmin&&currentPage==='workplace-setup'&&setup&&<section className={card}><div className="grid gap-6 lg:grid-cols-2"><div><h2 className="text-lg font-semibold">Approved work domains</h2><p className="mt-1 text-sm text-slate-600">Changes apply to future enrollment only. Existing workplace relationships are unchanged.</p><ul className="mt-3 divide-y">{setup.approved_domains.map(domain=><li key={domain} className="flex items-center justify-between gap-3 py-2 text-sm"><span>{domain}</span>{setup.current_admin_role==='owner'&&<button className="text-rose-700 underline disabled:opacity-50" disabled={busy} onClick={()=>void removeDomain(domain)}>Remove</button>}</li>)}{setup.approved_domains.length===0&&<li className="py-2 text-sm text-slate-500">No approved domains configured.</li>}</ul>{setup.current_admin_role==='owner'?<div className="mt-3 flex flex-col gap-2 sm:flex-row"><input className="min-w-0 flex-1 rounded-lg border p-3" placeholder="example.com" aria-label="Add an approved work domain" value={domainDraft} onChange={e=>setDomainDraft(e.target.value)}/><button className={button} disabled={busy||domainDraft.trim().length<3} onClick={addDomain}>Add domain</button></div>:<p className="mt-3 text-xs text-slate-500">Only the company owner can change approved domains.</p>}</div><div><h2 className="text-lg font-semibold">Ownership</h2><p className="mt-1 text-sm text-slate-600">Current role: <strong>{setup.current_admin_role==='owner'?'Owner':'Administrator'}</strong>. Only the owner can transfer ownership or remove administrators.</p>{setup.current_admin_role==='owner'&&<div className="mt-3 flex flex-col gap-2 sm:flex-row"><select className="min-w-0 flex-1 rounded-lg border p-3" aria-label="Select new company owner" value={ownershipTarget} onChange={e=>setOwnershipTarget(e.target.value)}><option value="">Select an active administrator</option>{setup.administrators.filter(a=>a.id!==user?.id&&['active','approved'].includes(a.status.toLowerCase())).map(a=><option key={a.id} value={a.id}>{a.name} · {a.email}</option>)}</select><button className={button} disabled={busy||!ownershipTarget} onClick={transferOwnership}>Transfer ownership</button></div>}</div></div><div className="mt-5 border-t pt-3"><h3 className="font-semibold">Administrator access</h3><ul className="mt-2 divide-y">{setup.administrators.map(a=>{const pending=['pending','invited'].includes(a.status.toLowerCase());const state=a.invitation_state==='expired'?'Invitation expired':a.invitation_state==='revoked'?'Invitation revoked':pending?'Invitation pending':a.status;return <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm"><span><strong>{a.name}</strong> · {a.email} <span className="ml-2 rounded-full bg-slate-100 px-2 py-1 text-xs">{a.workplace_admin_role==='owner'?'Owner':'Administrator'} · {state}</span></span><span className="flex gap-3">{pending&&a.invitation_state!=='revoked'&&<button disabled={busy} className="font-semibold text-teal-800 underline" onClick={()=>void resendAdministrator(a.id)}>Resend</button>}{setup.current_admin_role==='owner'&&a.workplace_admin_role!=='owner'&&<button disabled={busy} className="font-semibold text-rose-700 underline" onClick={()=>void removeAdministrator(a.id,pending)}>{pending?'Revoke invitation':'Remove admin'}</button>}</span></li>})}{setup.administrators.length===0&&<li className="py-3 text-sm text-slate-500">No company administrators yet.</li>}</ul></div></section>}
    {isCompanyAdmin ? <>
      {offboarding&&offboarding.status!=='NOT_STARTED'&&<section className="rounded-2xl border border-amber-300 bg-amber-50 p-5" role="status"><p className="text-xs font-bold uppercase tracking-wider text-amber-900">Workplace service ending</p><h2 className="mt-1 text-lg font-semibold text-slate-900">{offboarding.status==='SCHEDULED'?'Cancellation scheduled':offboarding.status==='IN_PROGRESS'?'Service ending':offboarding.status==='RETENTION_PERIOD'?'Privacy and retention period':'Workplace service ended'}</h2><p className="mt-2 text-sm text-slate-700">{offboarding.message||'Your workplace service is ending. Participation and wellbeing records remain private and are not exposed to your employer.'}</p>{offboarding.effective_date&&<p className="mt-2 text-sm text-slate-700">Service end date: <strong>{offboarding.effective_date}</strong></p>}{offboarding.retention_deadline&&<p className="mt-1 text-sm text-slate-700">Read-only status access through: <strong>{new Date(offboarding.retention_deadline).toLocaleDateString()}</strong></p>}</section>}
      {currentPage==='workplace-setup'&&<section className={card} aria-labelledby="company-readiness-title"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-wider text-emerald-700">{setup?.company?.name || 'Company setup'}</p><h2 id="company-readiness-title" className="text-lg font-semibold">Launch readiness</h2><p className="text-sm text-slate-600">Enrollment remains locked until every privacy, policy, and provider gate is complete.</p></div>{setupLoading?<span role="status" className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-600">Checking setup…</span>:<WorkplaceStatus value={setup?.readiness||'unavailable'} />}</div>
        {setupError&&<div role="alert" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900"><span>{setupError}</span><button className="font-semibold underline" onClick={()=>void refresh()}>Try again</button></div>}
        {setupLoading&&!setupError&&<div className="mt-4 animate-pulse rounded-xl bg-slate-100 p-6 text-sm text-slate-500" role="status">Loading company setup and launch requirements…</div>}
        {!setupLoading&&setup&&<div className="mt-5 grid gap-3 sm:grid-cols-2">{companySetupSteps.map((step,index)=>{const complete=Boolean(setup.checklist[step.key]);const isNext=firstIncompleteStep?.key===step.key;return <article key={step.key} className={`rounded-xl border p-4 ${complete?'border-emerald-200 bg-emerald-50/70':'border-amber-200 bg-amber-50/70'}`}><div className="flex items-start gap-3"><span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold ${complete?'bg-emerald-700 text-white':'bg-amber-200 text-amber-950'}`} aria-hidden="true">{complete?'✓':index+1}</span><div className="min-w-0"><h3 className="font-semibold">{step.title}<span className="ml-2 text-xs font-medium uppercase tracking-wide">{complete?'Complete':isNext?'Next step':'To do'}</span></h3><p className="mt-1 text-sm text-slate-600">{step.detail}</p>{!complete&&step.page&&<button className="mt-3 text-sm font-semibold text-teal-800 underline underline-offset-2" onClick={()=>setPage(step.page!)}>{step.key==='policy'?'Complete company policy':step.key==='provider'?'Manage providers':step.key==='domains'?'Manage domains':step.key==='privacy_contact'?'Configure privacy contact':'Open enrollment'}<span aria-hidden="true"> →</span></button>}{!complete&&step.key==='privacy_review'&&<p className="mt-3 text-sm font-medium text-amber-900">This gate is managed by MindGuard operations; ask your MindGuard contact for the review process.</p>}</div></div></article>})}</div>}
      </section>}
      {currentPage==='workplace-setup'&&<><section className={card}><h2 className="text-lg font-semibold">Company privacy and retention policy</h2><p className="mt-1 text-sm text-slate-600">Provide the company contact and policy settings used for the voluntary programme. These settings do not grant employers access to individual check-ins or care records.</p><div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="block text-sm font-medium" htmlFor="workplace-privacy-contact">Privacy contact email <span className="text-rose-700">*</span><input id="workplace-privacy-contact" className="mt-1 w-full rounded-lg border border-slate-300 p-3 focus:border-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-700/20" type="email" autoComplete="email" required aria-invalid={privacyContactInvalid} value={policy.privacy_contact_email} onChange={e=>setPolicy({...policy,privacy_contact_email:e.target.value})}/>{privacyContactInvalid&&<span className="mt-1 block text-xs font-normal text-rose-700">Enter a valid email address.</span>}</label>
        <label className="block text-sm font-medium" htmlFor="workplace-population">Approximate employee population range <span className="text-rose-700">*</span><input id="workplace-population" className="mt-1 w-full rounded-lg border border-slate-300 p-3 focus:border-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-700/20" placeholder="For example, 50–199" maxLength={80} required value={policy.employee_population_range} onChange={e=>setPolicy({...policy,employee_population_range:e.target.value})}/>{policy.employee_population_range.length>0&&policy.employee_population_range.trim().length===0&&<span className="mt-1 block text-xs font-normal text-rose-700">Please enter an employee population range.</span>}</label>
        <label className="block text-sm font-medium" htmlFor="workplace-retention">Check-in retention period (days) <span className="text-rose-700">*</span><input id="workplace-retention" className="mt-1 w-full rounded-lg border border-slate-300 p-3 focus:border-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-700/20" type="number" min={30} max={3650} required value={policy.retention_days} onChange={e=>setPolicy({...policy,retention_days:Number(e.target.value)})}/><span className="mt-1 block text-xs font-normal text-slate-500">Choose 30–3,650 days, consistent with your approved retention policy.</span></label>
        <label className="block text-sm font-medium" htmlFor="workplace-notice-version">Privacy notice version <span className="text-rose-700">*</span><input id="workplace-notice-version" className="mt-1 w-full rounded-lg border border-slate-300 p-3 focus:border-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-700/20" placeholder="For example, v1.0" minLength={3} maxLength={80} required value={policy.privacy_notice_version} onChange={e=>setPolicy({...policy,privacy_notice_version:e.target.value})}/></label>
      </div><label className="mt-4 flex items-start gap-3 rounded-xl bg-slate-50 p-4 text-sm"><input type="checkbox" className="mt-1 accent-teal-700" checked={policy.confirm_aggregate_only} onChange={e=>setPolicy({...policy,confirm_aggregate_only:e.target.checked})}/><span>I confirm employer reporting remains aggregate-only and never exposes participation, individual check-ins, or care cases. <span className="font-semibold text-rose-700">Required</span></span></label><button className={`${button} mt-4 w-full sm:w-auto`} disabled={busy||setupLoading||!policyValid||!policy.confirm_aggregate_only} onClick={savePolicy}>{busy?'Saving policy…':setup?.policy.status==='approved'?'Save policy changes':'Approve and save policy'}</button></section><section className={card}><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">Company administrators</h2><p className="mt-1 text-sm text-slate-600">Only use approved company work-email domains. Pending administrators must accept their invitation before launch.</p></div></div><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-sm font-medium" htmlFor="workplace-admin-name">Full name<input id="workplace-admin-name" className="mt-1 w-full rounded-lg border border-slate-300 p-3" autoComplete="name" value={adminInvite.name} onChange={e=>setAdminInvite({...adminInvite,name:e.target.value})}/></label><label className="text-sm font-medium" htmlFor="workplace-admin-email">Approved work email<input id="workplace-admin-email" className="mt-1 w-full rounded-lg border border-slate-300 p-3" type="email" autoComplete="email" value={adminInvite.email} onChange={e=>setAdminInvite({...adminInvite,email:e.target.value})}/></label></div><button className={`${button} mt-3 w-full sm:w-auto`} disabled={busy||adminInvite.name.trim().length<2||! /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(adminInvite.email.trim())} onClick={inviteAdministrator}>{busy?'Sending invitation…':'Send administrator invitation'}</button><ul className="mt-4 divide-y">{setup?.administrators.map(a=><li className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm" key={a.id}><span><strong>{a.name}</strong> · {a.email}</span><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${['active','approved'].includes(a.status.toLowerCase())?'bg-emerald-100 text-emerald-800':'bg-amber-100 text-amber-900'}`}>{a.status}</span></li>)}{setup?.administrators.length===0&&<li className="py-3 text-sm text-slate-600">No administrators have been added yet.</li>}</ul></section></>}
      {currentPage==='workplace-enrollment'&&<section className={card}><h2 className="text-lg font-semibold">Voluntary employee enrollment</h2><p className="my-2 text-sm text-slate-600">Create a 90-day shared link and distribute it securely. Participation is voluntary; this page never shows who opened or used a link.</p>{!canCreateEnrollmentLink&&<p className="mb-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">Enrollment links are locked until the administrator, privacy review, company policy, and independent provider checks are complete. Review the setup checklist for the remaining steps.</p>}<button className={button} disabled={busy||setupLoading||!canCreateEnrollmentLink} onClick={createLink}>{busy ? 'Creating…' : 'Create shared enrollment link'}</button>{link && <div className="mt-3 space-y-2"><p className="break-all rounded-lg bg-slate-50 p-3 text-sm">{link}</p><button className="text-sm font-semibold text-rose-700 underline" onClick={revokeLink}>Revoke this newly created link</button></div>}{enrollmentLinks.length>0&&<ul className="mt-4 divide-y border-t">{enrollmentLinks.map(l=><li key={l.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm"><span>Shared link · created {new Date(l.created_at).toLocaleDateString()} · {l.active?'Active':'Inactive'}{l.expires_at ? ` · expires ${new Date(l.expires_at).toLocaleDateString()}` : ''}</span>{l.active&&<button className="font-semibold text-rose-700 underline" onClick={async()=>{if(!await confirmAction('Revoke this enrollment link? Anyone with it will no longer be able to join.'))return;try{await api.post(`/v1/workplace/admin/enrollment-link/${l.id}/revoke`);setNotice('Enrollment link revoked.');await refresh()}catch(e){setNotice(e instanceof Error?e.message:'Unable to revoke link.')}}}>Revoke</button>}</li>)}</ul>}{!setupLoading&&enrollmentLinks.length===0&&<p className="mt-4 text-sm text-slate-500">No shared links have been created yet.</p>}</section>}
      {currentPage==='workplace-providers'&&<section className={card}><h2 className="text-lg font-semibold">Independent care providers</h2><p className="my-2 text-sm text-slate-600">Connect providers whose credentials have been reviewed by MindGuard. Employers cannot access provider case notes or case lists.</p><div className="flex flex-col gap-2 sm:flex-row"><input className="min-w-0 flex-1 rounded-lg border p-3" type="email" placeholder="Verified provider's email" value={providerEmail} onChange={e=>setProviderEmail(e.target.value)} /><button className={button} disabled={busy||!providerEmail} onClick={attachProvider}>Connect provider</button></div>{companyProviders.length>0&&<ul className="mt-4 divide-y">{companyProviders.map(p=><li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-3"><span><strong>{p.name}</strong>{p.title&&<span className="text-sm text-slate-600"> · {p.title}</span>}<span className="ml-2 text-xs font-semibold capitalize text-slate-500">{p.status?.replaceAll('_',' ')||'status unavailable'}</span></span>{p.association_status==='active'&&<button className="text-sm font-semibold text-rose-700 underline" onClick={()=>deactivateProvider(p.id)}>Deactivate</button>}</li>)}</ul>}{!companyProviders.length&&!setupLoading&&<p className="mt-3 text-sm text-slate-500">No providers are connected to this workplace yet.</p>}</section>}
      {currentPage==='workplace-reports'&&<WorkplaceInsightsDashboard data={insights} loading={setupLoading} error={insightsError} onRetry={()=>void refresh()}/>}
      {currentPage==='workplace-audit'&&<section className={card}><h2 className="text-lg font-semibold">Workplace audit history</h2><p className="mt-1 text-sm text-slate-600">Operational events only. Employee participation and care activity are intentionally excluded.</p><ul className="mt-4 divide-y">{audit.map((event,index)=><li className="py-3 text-sm" key={`${event.occurred_at}-${index}`}><strong>{event.event_type.replaceAll('_',' ')}</strong><span className="ml-2 text-slate-500">{new Date(event.occurred_at).toLocaleString()}</span></li>)}</ul></section>}
      {currentPage==='workplace-setup'&&<section className="rounded-2xl border border-amber-300 bg-amber-50 p-5"><h2 className="font-semibold text-amber-950">Live workplace launch review</h2><p className="mt-2 text-sm text-amber-900">Before a live US workplace pilot, the company should complete an appropriate privacy and legal review covering employee notice and consent, data handling and retention, provider confidentiality, and any applicable state requirements. MindGuard does not certify legal compliance. These reviews are not needed to explore a clearly marked demo.</p></section>}
    </> : isProvider ? <ProviderCaseList /> : <>
      {currentPage==='workplace-checkins'&&<section className={card}><h2 className="text-lg font-semibold">Private check-in</h2><p className="mt-1 text-sm text-slate-600">A short self-reflection, visible only to you unless you explicitly choose to share it with a provider.</p><div className="mt-4 grid gap-4 sm:grid-cols-3">{([['mood','How are you feeling?'],['stress','How manageable does stress feel?'],['support_access','How supported do you feel?']] as const).map(([key,label]) => <label key={key} className="text-sm font-medium">{label}<select className="mt-1 block w-full rounded-lg border p-3" value={checkin[key]} onChange={e => setCheckin(c => ({...c,[key]:Number(e.target.value)}))}>{[1,2,3,4,5].map(v=><option key={v} value={v}>{v} — {v===1?'not at all':v===5?'very much':'somewhat'}</option>)}</select></label>)}</div><button className={`${button} mt-4`} disabled={busy} onClick={saveCheckin}>Save private check-in</button></section>}
      {currentPage==='workplace-support'&&<section className={card}><h2 className="text-lg font-semibold">Request independent support</h2><p className="my-2 text-sm text-slate-600">The provider receives your identity and only the specific latest check-in selected when you make this request. Your employer is not notified.</p>{providers.length ? <div className="space-y-3"><select className="w-full rounded-lg border p-3 sm:w-auto" value={providerId} onChange={e=>setProviderId(e.target.value)}><option value="">Choose a provider…</option>{providers.map(p=><option key={p.id} value={p.id}>{p.name}{p.title ? ` · ${p.title}` : ''}</option>)}</select><label className="flex items-start gap-2 text-sm text-slate-700"><input type="checkbox" checked={shareConfirmed} onChange={e=>setShareConfirmed(e.target.checked)} className="mt-1" /><span>I want this provider to receive my identity and most recent check-in with this support request. My employer will not receive it.</span></label><button className={button} disabled={busy || !providerId || !shareConfirmed} onClick={requestSupport}>Request support and share selected check-in</button></div> : <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">An independent provider is not currently configured for this programme. You can still use private check-ins and local resources.</p>}{supportHistory.length>0&&<div className="mt-4 border-t pt-4"><h3 className="font-medium">Your support requests</h3><ul className="mt-2 space-y-2 text-sm">{supportHistory.map(c=><li className="flex justify-between gap-3 rounded-lg bg-slate-50 p-3" key={c.id}><span>{new Date(c.created_at).toLocaleDateString()} · {c.status.replaceAll('_',' ')}</span>{c.status==='open'&&<button className="font-semibold text-rose-700 underline" onClick={async()=>{try{await api.post(`/v1/workplace/support-requests/${c.id}/withdraw`);setNotice('Provider access to this shared check-in has been withdrawn.');await refresh()}catch(e){setNotice(e instanceof Error?e.message:'Unable to withdraw sharing.')}}}>Withdraw sharing</button>}</li>)}</ul></div>}{supportUpdates.length>0&&<div className="mt-4 border-t pt-4"><h3 className="font-semibold">Updates shared with you</h3><ul className="mt-2 space-y-2">{supportUpdates.map(update=><li key={update.id} className="rounded-lg bg-teal-50 p-3 text-sm"><p>{update.message}</p><time className="mt-2 block text-xs text-slate-500">{new Date(update.shared_at).toLocaleString()}</time></li>)}</ul></div>}</section>}
      {currentPage==='workplace-checkins'&&checkinHistory.length>0&&<section className={card}><h2 className="text-lg font-semibold">Your private check-in history</h2><ul className="mt-3 space-y-2">{checkinHistory.map(c=><li key={c.id} className="rounded-lg bg-slate-50 p-3 text-sm"><p className="font-medium">{new Date(c.created_at).toLocaleString()}</p><p className="mt-1 text-slate-600">Mood {c.answers.mood}/5 · Stress {c.answers.stress}/5 · Support {c.answers.support_access}/5</p></li>)}</ul></section>}
      {currentPage==='workplace-support'&&<WorkerCaseReassignment cases={supportHistory} providers={providers} onChanged={refresh} onNotice={setNotice} />}
      {(currentPage==='workplace'||currentPage==='workplace-support')&&<section className="rounded-2xl border border-rose-200 bg-rose-50 p-5"><h2 className="font-semibold text-rose-900">Need urgent help?</h2><p className="mt-2 text-sm text-rose-900">MindGuard is not emergency care. If you are in immediate danger in the United States, call <a className="font-bold underline" href="tel:911">911</a>. For emotional distress or suicidal thoughts, call or text <a className="font-bold underline" href="tel:988">988</a> or visit <a className="font-bold underline" href="https://988lifeline.org/get-help/" target="_blank" rel="noreferrer">988lifeline.org</a>. Your employer is not automatically alerted.</p></section>}
      {currentPage==='workplace'&&<button className="text-sm text-slate-500 underline" onClick={withdraw}>Withdraw from workplace participation</button>}
    </>}
    {notice && <p role="status" className="rounded-xl bg-slate-100 p-3 text-sm text-slate-700">{notice}</p>}
    {confirmation&&<WorkplaceConfirmDialog message={confirmation.message} onCancel={()=>{confirmation.resolve(false);setConfirmation(null)}} onConfirm={()=>{confirmation.resolve(true);setConfirmation(null)}}/>}
  </main>
}

function WorkerCaseReassignment({cases,providers,onChanged,onNotice}:{cases:Array<{id:string;status:string;assignment_status?:string;created_at:string}>;providers:Provider[];onChanged:()=>Promise<void>;onNotice:(message:string)=>void}) {
  const [providerByCase,setProviderByCase]=useState<Record<string,string>>({})
  const [confirmed,setConfirmed]=useState<Record<string,boolean>>({})
  const [busyCase,setBusyCase]=useState('')
  const pending=cases.filter(item=>item.assignment_status==='reassignment_required')
  if(!pending.length)return null
  const reassign=async(caseId:string)=>{
    const providerId=providerByCase[caseId]
    if(!providerId||!confirmed[caseId])return
    setBusyCase(caseId)
    try{await api.post(`/v1/workplace/support-requests/${caseId}/reassign`,{provider_id:providerId,confirm_shared_history:true});onNotice('Your case has been shared with the new provider you selected. Your employer is not notified.');await onChanged()}
    catch(e){onNotice(e instanceof Error?e.message:'Unable to confirm a new provider.')}
    finally{setBusyCase('')}
  }
  return <section className={`${card} border-amber-200 bg-amber-50/60`}><h2 className="text-lg font-semibold">Choose a new provider</h2><p className="mt-1 text-sm text-slate-700">Your previous provider is no longer available for this case. Your case stays private while you decide what to do next.</p>{pending.map(item=><article key={item.id} className="mt-4 rounded-xl border border-amber-200 bg-white p-4"><p className="text-sm font-medium">Support request from {new Date(item.created_at).toLocaleDateString()}</p>{providers.length?<><label className="mt-3 block text-sm font-medium">Available provider<select className="mt-1 w-full rounded-lg border p-3" value={providerByCase[item.id]||''} onChange={e=>setProviderByCase(current=>({...current,[item.id]:e.target.value}))}><option value="">Choose a provider…</option>{providers.map(provider=><option key={provider.id} value={provider.id}>{provider.name}{provider.title?` · ${provider.title}`:''}</option>)}</select></label><label className="mt-3 flex items-start gap-2 text-sm text-slate-700"><input type="checkbox" className="mt-1" checked={Boolean(confirmed[item.id])} onChange={e=>setConfirmed(current=>({...current,[item.id]:e.target.checked}))}/><span>I confirm that the provider I selected may access the information I previously shared for this support case, including its history.</span></label><button className={`${button} mt-3 w-full sm:w-auto`} disabled={busyCase===item.id||!providerByCase[item.id]||!confirmed[item.id]} onClick={()=>void reassign(item.id)}>{busyCase===item.id?'Confirming…':'Confirm and share with selected provider'}</button></>:<p className="mt-3 text-sm text-slate-600">No provider is currently available. Your existing case history remains private; please check again later or contact MindGuard support.</p>}</article>)}</section>
}

function WorkplaceCommercialEditor({company,onSaved}:{company:{id:string;name:string;commercial?:CommercialView};onSaved:()=>void}) {
  const current=company.commercial
  const [plan,setPlan]=useState(current?.plan_key||'pilot')
  const [status,setStatus]=useState(current?.status||'PILOT')
  const [start,setStart]=useState(current?.contract_start_date||'')
  const [end,setEnd]=useState(current?.contract_end_date||'')
  const [renewal,setRenewal]=useState(current?.renewal_date||'')
  const [graceEnd,setGraceEnd]=useState(current?.grace_period_end||'')
  const [billingCycle,setBillingCycle]=useState(current?.billing_cycle||'')
  const [populationBand,setPopulationBand]=useState(current?.population_band||'not_recorded')
  const [reference,setReference]=useState(current?.internal_reference||'')
  const [notes,setNotes]=useState(current?.internal_notes||'')
  const [reason,setReason]=useState('')
  const [cancelDate,setCancelDate]=useState(current?.cancellation_effective_date||'')
  const [cancelReason,setCancelReason]=useState(current?.cancellation_reason||'')
  const [capabilities,setCapabilities]=useState({enrollment:current?.enabled_capabilities.enrollment??true,aggregate_analytics:current?.enabled_capabilities.aggregate_analytics??true,provider_services:current?.enabled_capabilities.provider_services??true})
  const [busy,setBusy]=useState(false)
  const [notice,setNotice]=useState('')
  const save=async()=>{
    if(status!==current?.status&&reason.trim().length<3){setNotice('Enter a reason of at least 3 characters for the status transition.');return}
    if(status==='CANCELLED'&&(!cancelDate||cancelReason.trim().length<3)){setNotice('Cancellation needs an effective date and reason.');return}
    setBusy(true);setNotice('')
    const payload:Record<string,unknown>={plan_key:plan,contract_start_date:start||null,contract_end_date:end||null,renewal_date:renewal||null,grace_period_end:graceEnd||null,billing_cycle:billingCycle||null,population_band:populationBand,internal_reference:reference||null,internal_notes:notes||null,enabled_capabilities:{...capabilities,voice_support:false},reason:reason||undefined}
    if(status!==current?.status)payload.status=status
    if(status==='CANCELLED'){payload.cancellation_effective_date=cancelDate;payload.cancellation_reason=cancelReason}
    try{await api.put(`/v1/workplace/admin/companies/${company.id}/commercial`,payload);setNotice('Commercial account saved.');onSaved()}
    catch(e){setNotice(e instanceof Error?e.message:'Unable to save commercial account.')}
    finally{setBusy(false)}
  }
  const transitionOptions=['PILOT','TRIAL','ACTIVE','GRACE_PERIOD','SUSPENDED','CANCELLED','TERMINATED']
  return <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50"><summary className="cursor-pointer px-4 py-3 font-semibold">Manage commercial account</summary><div className="grid gap-3 border-t p-4 sm:grid-cols-2 lg:grid-cols-3">
    <label className="text-sm font-medium">Commercial status<select className="mt-1 w-full rounded-lg border bg-white p-2.5" value={status} onChange={e=>setStatus(e.target.value)}>{transitionOptions.map(value=><option key={value} value={value}>{value.replaceAll('_',' ')}</option>)}</select></label>
    <label className="text-sm font-medium">Plan<select className="mt-1 w-full rounded-lg border bg-white p-2.5" value={plan} onChange={e=>setPlan(e.target.value)}>{[['pilot','Workplace pilot'],['trial','Workplace trial'],['team','Workplace team'],['enterprise','Workplace enterprise'],['legacy_pilot','Legacy pilot']].map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
    <label className="text-sm font-medium">Workforce band<select className="mt-1 w-full rounded-lg border bg-white p-2.5" value={populationBand} onChange={e=>setPopulationBand(e.target.value)}>{[['1-50','1–50'],['51-200','51–200'],['201-500','201–500'],['501-1000','501–1,000'],['1000+','1,000+'],['not_recorded','Not recorded']].map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
    <label className="text-sm font-medium">Contract / pilot starts<input type="date" className="mt-1 w-full rounded-lg border bg-white p-2.5" value={start} onChange={e=>setStart(e.target.value)}/></label>
    <label className="text-sm font-medium">Contract / pilot ends<input type="date" className="mt-1 w-full rounded-lg border bg-white p-2.5" value={end} onChange={e=>setEnd(e.target.value)}/></label>
    <label className="text-sm font-medium">Renewal date<input type="date" className="mt-1 w-full rounded-lg border bg-white p-2.5" value={renewal} onChange={e=>setRenewal(e.target.value)}/></label>
    <label className="text-sm font-medium">Grace period ends<input type="date" className="mt-1 w-full rounded-lg border bg-white p-2.5" value={graceEnd} onChange={e=>setGraceEnd(e.target.value)}/></label>
    <label className="text-sm font-medium">Billing cycle<select className="mt-1 w-full rounded-lg border bg-white p-2.5" value={billingCycle} onChange={e=>setBillingCycle(e.target.value)}><option value="">To be agreed</option><option value="monthly">Monthly</option><option value="annual">Annual</option><option value="one_time">One time</option><option value="custom">Custom contract</option></select></label>
    <label className="text-sm font-medium">Internal contract reference<input className="mt-1 w-full rounded-lg border bg-white p-2.5" value={reference} onChange={e=>setReference(e.target.value)}/></label>
    <label className="text-sm font-medium sm:col-span-2">Internal commercial notes<textarea className="mt-1 w-full rounded-lg border bg-white p-2.5" rows={2} value={notes} onChange={e=>setNotes(e.target.value)}/></label>
    <fieldset className="rounded-lg border bg-white p-3"><legend className="px-1 text-sm font-medium">Capabilities</legend>{[['enrollment','Employee enrollment'],['aggregate_analytics','Employer aggregate insights'],['provider_services','Provider services']].map(([key,label])=><label key={key} className="mt-2 flex gap-2 text-sm"><input type="checkbox" checked={Boolean(capabilities[key as keyof typeof capabilities])} onChange={e=>setCapabilities(old=>({...old,[key]:e.target.checked}))}/>{label}</label>)}<p className="mt-2 text-xs text-slate-500">Voice support remains disabled pending separate launch approval.</p></fieldset>
    {status==='CANCELLED'&&<><label className="text-sm font-medium">Cancellation effective date<input type="date" className="mt-1 w-full rounded-lg border bg-white p-2.5" value={cancelDate} onChange={e=>setCancelDate(e.target.value)}/></label><label className="text-sm font-medium">Cancellation reason<input className="mt-1 w-full rounded-lg border bg-white p-2.5" value={cancelReason} onChange={e=>setCancelReason(e.target.value)}/></label></>}
    {status!==current?.status&&<label className="text-sm font-medium sm:col-span-2">Reason for status change<input className="mt-1 w-full rounded-lg border bg-white p-2.5" value={reason} onChange={e=>setReason(e.target.value)}/></label>}
    <div className="sm:col-span-2 lg:col-span-3"><button className={button} disabled={busy} onClick={()=>void save()}>{busy?'Saving…':'Save commercial account'}</button>{notice&&<p role="status" className="mt-2 text-sm text-slate-700">{notice}</p>}</div>
  </div></details>
}

export function WorkplaceAdminPage() {
  const conversionLeadIntent = useUiStore((s) => s.workplaceConversionLeadId)
  const clearConversionLeadIntent = useUiStore((s) => s.clearWorkplaceConversion)
  const [companies, setCompanies] = useState<Array<{id:string;name:string;status:string;demo_mode?:boolean;approved_work_email_domains:string[];legal_review_complete:boolean;legal_review_reference?:string;employee_population_range?:string;retention_days:number;policy_status:string;commercial?:CommercialView;offboarding?:OffboardingView;administrators:Array<{id:string;name:string;email:string;status:string}>}>>([])
  const [demoCompanies, setDemoCompanies] = useState<Array<{id:string;name:string;status:string;demo_mode?:boolean;approved_work_email_domains:string[];legal_review_complete:boolean;legal_review_reference?:string;employee_population_range?:string;retention_days:number;policy_status:string;commercial?:CommercialView;offboarding?:OffboardingView;administrators:Array<{id:string;name:string;email:string;status:string}>}>>([])
  const [companyLeads, setCompanyLeads] = useState<Array<{id:string;full_name:string;work_email:string;organisation:string;organisation_type:string;status:string;population_range?:string;employee_population_range?:string;institution_id?:string}>>([])
  const [selectedLead, setSelectedLead] = useState('')
  const [name, setName] = useState('')
  const [adminName, setAdminName] = useState('')
  const [adminEmail, setAdminEmail] = useState('')
  const [demoName, setDemoName] = useState('')
  const [demoAdminName, setDemoAdminName] = useState('')
  const [demoAdminEmail, setDemoAdminEmail] = useState('')
  const [domains, setDomains] = useState('')
  const [privacyContact, setPrivacyContact] = useState('')
  const [populationRange, setPopulationRange] = useState('')
  const [retentionDays, setRetentionDays] = useState(365)
  const [reference, setReference] = useState('')
  const [providerEmail, setProviderEmail] = useState('')
  const [providerTitle, setProviderTitle] = useState('')
  const [professionalType, setProfessionalType] = useState('')
  const [qualification, setQualification] = useState('')
  const [registration, setRegistration] = useState('')
  const [credentialReference, setCredentialReference] = useState('')
  const [licenseState, setLicenseState] = useState('')
  const [credentialValidFrom, setCredentialValidFrom] = useState('')
  const [credentialExpiresAt, setCredentialExpiresAt] = useState('')
  const [notice, setNotice] = useState('')
  const [confirmation, setConfirmation] = useState<{message:string;resolve:(confirmed:boolean)=>void}|null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const createFormStarted = Boolean(name || adminName || adminEmail || domains || privacyContact || populationRange)
  const createFormError = validateCompanyProvisioning({ name, adminName, adminEmail, domains, privacyContact: privacyContact || adminEmail, retentionDays })
  const convertFormError = validateCompanyProvisioning({ name, adminName, adminEmail, domains, privacyContact, retentionDays })
  const selectedCompanyLead = companyLeads.find(lead => lead.id === selectedLead)
  const confirmAction=(message:string)=>new Promise<boolean>(resolve=>setConfirmation({message,resolve}))
  const load = useCallback(async () => { setLoading(true); setLoadError(''); try { const [companyResult,leadResult]=await Promise.all([api.get('/v1/workplace/admin/companies'),api.get('/v1/admin/demo-requests')]);const rows=companyResult.data;setCompanies(rows.filter((company:{demo_mode?:boolean})=>!company.demo_mode));setDemoCompanies(rows.filter((company:{demo_mode?:boolean})=>Boolean(company.demo_mode)));setCompanyLeads((leadResult.data.demo_requests||[]).filter((lead:{organisation_type:string;status:string;institution_id?:string})=>lead.organisation_type==='company'&&!lead.institution_id&&['qualified','demo_scheduled','closed_won'].includes(lead.status))) } catch (e) { setLoadError(e instanceof Error ? e.message : 'Unable to load companies and qualified leads.') } finally { setLoading(false) } }, [])
  // Loading API data here is an external synchronization; state updates happen after the request settles.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load() }, [load])
  // Consume the one-time admin navigation intent after the selected lead list loads.
  useEffect(() => {
    if (!conversionLeadIntent || !companyLeads.length) return
    const lead = companyLeads.find((item) => item.id === conversionLeadIntent)
    if (lead) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedLead(lead.id)
      setName(lead.organisation)
      setAdminName(lead.full_name)
      setAdminEmail(lead.work_email)
      const domain = lead.work_email.split('@')[1] || ''
      setDomains(domain)
      setPrivacyContact(lead.work_email)
      setPopulationRange(lead.population_range || lead.employee_population_range || '')
    }
    clearConversionLeadIntent()
  }, [companyLeads, conversionLeadIntent, clearConversionLeadIntent])
  const privacyReviewCount = companies.filter(company => !company.demo_mode && !company.legal_review_complete).length
  const policyReviewCount = companies.filter(company => company.policy_status.toLowerCase() !== 'approved').length
  const commercialAttentionCount = companies.filter(company => company.commercial?.action_required).length
  const offboardingCount = companies.filter(company => company.offboarding && !['NOT_STARTED', 'COMPLETED'].includes(company.offboarding.status)).length
  const create = async () => {
    const validationError = validateCompanyProvisioning({ name, adminName, adminEmail, domains, privacyContact: privacyContact || adminEmail, retentionDays })
    if (validationError) { setNotice(validationError); return }
    setBusy(true); setNotice('')
    try { const result=await api.post('/v1/workplace/admin/companies', { name, admin_name:adminName, admin_email: adminEmail, work_email_domains: domains.split(',').map(v=>v.trim()).filter(Boolean), privacy_contact_email:privacyContact||adminEmail, employee_population_range:populationRange||null, retention_days:retentionDays }); setName(''); setAdminName(''); setAdminEmail(''); setDomains(''); setPrivacyContact(''); setPopulationRange(''); setRetentionDays(365); const status=result.data.administrator_invitation_status; setNotice(status==='active'?'Company created and the existing active account was assigned as its first administrator; no invitation email was needed.':result.data.invitation_sent===false?'Company created, but the invitation email could not be delivered. Use Resend invitation below after refreshing.':'Company created and the first administrator invitation was sent. Provider setup and the privacy review still need completion.'); await load() }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to create company.') }
    finally { setBusy(false) }
  }
  const createDemo = async () => {
    if (demoName.trim().length < 2 || demoAdminName.trim().length < 2 || !emailPattern.test(demoAdminEmail.trim())) {
      setNotice('Enter a demo workplace name, administrator name, and valid invitation email.')
      return
    }
    setBusy(true); setNotice('')
    try {
      const {data} = await api.post('/v1/workplace/admin/demo-workplaces', {name:demoName.trim(),admin_name:demoAdminName.trim(),admin_email:demoAdminEmail.trim()})
      setDemoName(''); setDemoAdminName(''); setDemoAdminEmail('')
      setNotice(data.invitation_sent ? 'Demo workplace created. Check the administrator inbox for its invitation.' : `Demo workplace created, but the invitation was not delivered${data.invitation_error ? `: ${data.invitation_error}` : '.'} Use Resend invitation below.`)
      await load()
    } catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to create demo workplace.') }
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
    try { await api.post('/v1/workplace/admin/provider-credentials', { provider_email: providerEmail, professional_type:professionalType||null, professional_title: providerTitle, qualification, registration_number: registration, license_state:licenseState, verification_reference: credentialReference, valid_from:credentialValidFrom||null, expires_at:credentialExpiresAt||null }); setProviderEmail(''); setProviderTitle(''); setProfessionalType(''); setQualification(''); setRegistration(''); setLicenseState(''); setCredentialReference(''); setCredentialValidFrom(''); setCredentialExpiresAt(''); setNotice('Provider enabled after a human review of their state license.'); }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Unable to provision provider.') }
    finally { setBusy(false) }
  }
  const lifecycle = async (id:string,action:'activate'|'suspend'|'archive') => {
    const reason=window.prompt(`Reason to ${action} tenant access (separate from commercial status):`)
    if(!reason||reason.trim().length<3)return
    if(action==='archive'&&!await confirmAction('Archive this workplace tenant? Active enrollment links will be revoked and provider relationships deactivated. This is separate from commercial termination and cannot be undone.'))return
    setBusy(true);setNotice('')
    try{await api.post(`/v1/workplace/admin/companies/${id}/lifecycle`,{action,reason});setNotice(`Company ${action}d.`);await load()}catch(e){setNotice(e instanceof Error?e.message:`Unable to ${action} company.`)}finally{setBusy(false)}
  }
  const resendInvite = async(companyId:string,adminId:string) => {
    setBusy(true);setNotice('')
    try{const {data}=await api.post(`/v1/workplace/admin/companies/${companyId}/administrators/${adminId}/resend`);setNotice(data.email_sent?'Administrator invitation resent.':`Invitation could not be sent: ${data.email_error||'email delivery failed'}`)}catch(e){setNotice(e instanceof Error?e.message:'Unable to resend invitation.')}finally{setBusy(false)}
  }
  const completeOffboarding=async(company:{id:string;name:string})=>{
    if(!await confirmAction(`Finalize offboarding for ${company.name}? This is a consequential lifecycle action.`))return
    setBusy(true);setNotice('')
    try{await api.post(`/v1/workplace/admin/companies/${company.id}/offboarding`,{action:'complete'});setNotice('Workplace offboarding completed.');await load()}
    catch(e){setNotice(e instanceof Error?e.message:'Unable to complete workplace offboarding.')}
    finally{setBusy(false)}
  }
  const selectCompanyLead=(id:string)=>{setSelectedLead(id);const lead=companyLeads.find(item=>item.id===id);if(!lead)return;const domain=lead.work_email.split('@')[1]||'';setName(lead.organisation);setAdminName(lead.full_name);setAdminEmail(lead.work_email);setDomains(domain);setPrivacyContact(lead.work_email);setPopulationRange(lead.population_range||lead.employee_population_range||'')}
  const convertLead=async()=>{if(!selectedLead)return;const validationError=validateCompanyProvisioning({name,adminName,adminEmail,domains,privacyContact,retentionDays});if(validationError){setNotice(validationError);return}setBusy(true);setNotice('');try{const {data}=await api.post(`/v1/workplace/admin/demo-requests/${selectedLead}/convert`,{company_name:name,admin_name:adminName,admin_email:adminEmail,work_email_domains:domains.split(',').map(v=>v.trim()).filter(Boolean),privacy_contact_email:privacyContact,population_range:populationRange||null,retention_days:retentionDays});setNotice(data.invitation_sent?'Qualified company demo converted and first administrator invitation sent.':'Company created, but the administrator email failed; use Resend invitation in the company list.');setSelectedLead('');await load()}catch(e){setNotice(e instanceof Error?e.message:'Unable to convert company demo.')}finally{setBusy(false)}}
  return <main className="mx-auto w-full max-w-5xl space-y-6 text-slate-900"><header><p className="text-xs font-bold uppercase tracking-widest text-teal-700">Global administration</p><h1 className="mt-1 text-3xl font-bold">Workplace operations</h1><p className="mt-2 text-slate-600">Try the product with a demo workplace now. Live customer enrollment stays off until its privacy, company-domain, and provider checks are complete.</p></header>
    {loadError&&<div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"><span>{loadError}</span><button className="font-semibold underline" onClick={()=>void load()}>Try again</button></div>}
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Workplace operations summary">{[{label:'Company tenants',value:loading?'…':companies.length,detail:'Provisioned workplaces'},{label:'Privacy reviews',value:loading?'…':privacyReviewCount,detail:'Still required'},{label:'Policy approvals',value:loading?'…':policyReviewCount,detail:'Company action needed'},{label:'Lifecycle attention',value:loading?'…':commercialAttentionCount+offboardingCount,detail:'Commercial or offboarding'}].map(item=><article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" key={item.label}><p className="text-xs font-bold uppercase tracking-wide text-slate-500">{item.label}</p><p className="mt-2 text-2xl font-bold text-slate-900">{item.value}</p><p className="mt-1 text-xs text-slate-600">{item.detail}</p></article>)}</section>
    <section className={card}><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">Demo workplaces</h2><p className="mt-1 text-sm text-slate-600">Clearly marked test tenants. They are excluded from customer privacy-review counts and cannot be converted into live accounts.</p></div><span className="rounded-full bg-sky-100 px-3 py-1 text-xs font-bold text-sky-900">{demoCompanies.length} demo</span></div>{demoCompanies.length? <ul className="mt-3 divide-y">{demoCompanies.map(company=><li key={company.id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div><p className="font-semibold">{company.name} <span className="ml-2 rounded-full bg-sky-100 px-2 py-1 text-xs font-bold text-sky-900">DEMO ONLY</span></p><p className="text-sm text-slate-600">{company.administrators.map(admin=>`${admin.name} · ${admin.email} · ${admin.status}`).join(' · ')||'Administrator invitation pending'}</p></div><div className="flex items-center gap-3"><span className="text-xs text-slate-500">{company.status}</span>{company.administrators.filter(admin=>!['active','approved'].includes(admin.status.toLowerCase())).map(admin=><button key={admin.id} disabled={busy} onClick={()=>void resendInvite(company.id,admin.id)} className="text-sm font-semibold text-teal-800 underline">Resend invite</button>)}</div></li>)}</ul>:<p className="mt-3 text-sm text-slate-500">No demo workplaces yet. Create one below to try the experience.</p>}</section>
    <section className="rounded-2xl border border-teal-200 bg-teal-50/60 p-5 shadow-sm" aria-labelledby="demo-workplace-title">
      <p className="text-xs font-bold uppercase tracking-wider text-teal-800">Try the workplace experience</p>
      <h2 id="demo-workplace-title" className="mt-1 text-xl font-semibold">Create a demo workplace</h2>
      <p className="mt-2 max-w-3xl text-sm text-slate-700">Quick setup: enter a name, your name, and an email inbox you can open. We send you an invitation and include a clearly labeled sample counsellor. No company domain, license documents, or privacy paperwork is needed to explore the demo.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium">Demo company name<input className="mt-1 w-full rounded-lg border p-3" value={demoName} onChange={e=>setDemoName(e.target.value)} placeholder="Example Company" autoComplete="organization" /></label>
        <label className="text-sm font-medium">Your name<input className="mt-1 w-full rounded-lg border p-3" value={demoAdminName} onChange={e=>setDemoAdminName(e.target.value)} placeholder="Full name" autoComplete="name" /></label>
        <label className="text-sm font-medium sm:col-span-2">Email inbox for the demo administrator invitation<input className="mt-1 w-full rounded-lg border p-3" type="email" value={demoAdminEmail} onChange={e=>setDemoAdminEmail(e.target.value)} placeholder="you@example.com" autoComplete="email" /><span className="mt-1 block text-xs font-normal text-slate-600">Use an address you can open. It does not need to match a company domain.</span></label>
      </div>
      <button className={`${button} mt-4`} disabled={busy||demoName.trim().length<2||demoAdminName.trim().length<2||!emailPattern.test(demoAdminEmail.trim())} onClick={()=>void createDemo()}>{busy?'Creating demo…':'Create demo workplace and send invite'}</button>
      <p className="mt-3 text-xs text-slate-600">Demo workspaces and records are permanently marked as tests and cannot be turned into live customer workplaces. Use test information only; the sample provider is fictional and this is not real care.</p>
    </section>
    {companyLeads.length>0&&<section className={card}>
      <h2 className="text-lg font-semibold">Set up a company from a demo</h2>
      <p className="mt-1 text-sm text-slate-600">Choose the company request, check the details, then create its workplace and invite the first administrator.</p>
      <ol className="mt-3 grid gap-2 text-sm text-slate-700 sm:grid-cols-3">
        <li><span className="font-semibold">1.</span> Select a qualified request.</li>
        <li><span className="font-semibold">2.</span> Confirm the company, admin, domains and privacy contact.</li>
        <li><span className="font-semibold">3.</span> Create the company and send the admin invite.</li>
      </ol>
      <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">This creates a live-customer tenant, not a test demo. It does not add workers or open enrollment. Before launch, the company’s approved email domain, privacy and legal review, company policy, and a human review of the provider’s state license must be recorded.</p>
      <label className="mt-4 block text-sm font-medium">Qualified company demo request
        <select className="mt-1 w-full rounded-lg border p-3" value={selectedLead} onChange={e=>selectCompanyLead(e.target.value)}>
          <option value="">Choose a company request…</option>
          {companyLeads.map(lead=><option key={lead.id} value={lead.id}>{lead.organisation} · {lead.full_name} · {lead.status.replaceAll('_',' ')}</option>)}
        </select>
        <span className="mt-1 block text-xs font-normal text-slate-500">Only requests marked qualified, demo scheduled or closed won appear here.</span>
      </label>
      {selectedCompanyLead&&<p className="mt-2 text-xs text-slate-500">Request from {selectedCompanyLead.full_name} · {selectedCompanyLead.work_email} · {selectedCompanyLead.status.replaceAll('_',' ')}</p>}
      {selectedLead&&<div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium">Company name<input className="mt-1 w-full rounded-lg border p-3" required value={name} onChange={e=>setName(e.target.value)}/><span className="mt-1 block text-xs font-normal text-slate-500">Pre-filled from the request; edit if needed.</span></label>
        <label className="text-sm font-medium">First administrator’s name<input className="mt-1 w-full rounded-lg border p-3" required value={adminName} onChange={e=>setAdminName(e.target.value)}/></label>
        <label className="text-sm font-medium">First administrator’s work email<input className="mt-1 w-full rounded-lg border p-3" type="email" required value={adminEmail} onChange={e=>setAdminEmail(e.target.value)}/><span className="mt-1 block text-xs font-normal text-slate-500">We send the company setup invitation to this address.</span></label>
        <label className="text-sm font-medium">Approved company email domains<input className="mt-1 w-full rounded-lg border p-3" placeholder="company.com, subsidiary.com" required value={domains} onChange={e=>setDomains(e.target.value)}/><span className="mt-1 block text-xs font-normal text-slate-500">Use domains the company owns. Separate multiple domains with commas. The admin email must match one.</span></label>
        <label className="text-sm font-medium">Company privacy contact email<input className="mt-1 w-full rounded-lg border p-3" type="email" required value={privacyContact} onChange={e=>setPrivacyContact(e.target.value)}/><span className="mt-1 block text-xs font-normal text-slate-500">The company contact for privacy questions.</span></label>
        <label className="text-sm font-medium">Approximate employee population<input className="mt-1 w-full rounded-lg border p-3" placeholder="For example, 50–199" value={populationRange} onChange={e=>setPopulationRange(e.target.value)}/></label>
        <label className="text-sm font-medium">Default record retention (days)<input className="mt-1 w-full rounded-lg border p-3" type="number" min={30} max={3650} value={retentionDays} onChange={e=>setRetentionDays(Number(e.target.value))}/><span className="mt-1 block text-xs font-normal text-slate-500">Choose 30 to 3,650 days.</span></label>
      </div>}
      {selectedLead&&convertFormError&&<p role="status" className="mt-3 text-sm text-rose-700">{convertFormError}</p>}
      {selectedLead&&<button disabled={busy||Boolean(convertFormError)} onClick={()=>void convertLead()} className={`${button} mt-4`}>{busy?'Creating company…':'Create company and invite admin'}</button>}
    </section>}
    <section className={card}><h2 className="text-lg font-semibold">Create a real customer workplace</h2><p className="my-2 text-sm text-slate-600">Use this after a company is ready to move toward a real launch. It requires an approved company domain and keeps enrollment locked until privacy, policy, and provider reviews are recorded. For testing, use the demo option above.</p><div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium">Company name<input className="mt-1 w-full rounded-lg border p-3" autoComplete="organization" required value={name} onChange={e=>setName(e.target.value)} /></label><label className="text-sm font-medium">First administrator full name<input className="mt-1 w-full rounded-lg border p-3" autoComplete="name" required value={adminName} onChange={e=>setAdminName(e.target.value)} /></label><label className="text-sm font-medium">First administrator work email<input className="mt-1 w-full rounded-lg border p-3" type="email" autoComplete="email" required value={adminEmail} onChange={e=>setAdminEmail(e.target.value)} /></label><label className="text-sm font-medium">Approved company email domains<input className="mt-1 w-full rounded-lg border p-3" placeholder="company.com, subsidiary.com" required value={domains} onChange={e=>setDomains(e.target.value)} /><span className="mt-1 block text-xs font-normal text-slate-500">Company-owned domains only; the administrator email must use one.</span></label><label className="text-sm font-medium">Company privacy contact email<input className="mt-1 w-full rounded-lg border p-3" type="email" autoComplete="email" value={privacyContact} onChange={e=>setPrivacyContact(e.target.value)} /><span className="mt-1 block text-xs font-normal text-slate-500">If blank, the administrator email is used.</span></label><label className="text-sm font-medium">Approximate employee population range<input className="mt-1 w-full rounded-lg border p-3" placeholder="For example, 50–199" maxLength={80} value={populationRange} onChange={e=>setPopulationRange(e.target.value)} /></label><label className="text-sm font-medium">Default retention (days)<input className="mt-1 w-full rounded-lg border p-3" type="number" min={30} max={3650} value={retentionDays} onChange={e=>setRetentionDays(Number(e.target.value))}/><span className="mt-1 block text-xs font-normal text-slate-500">Allowed range: 30–3,650 days.</span></label></div>{createFormStarted&&createFormError&&<p role="status" className="mt-3 text-sm text-rose-700">{createFormError}</p>}<button className={`${button} mt-4 w-full sm:w-auto`} disabled={busy||Boolean(createFormError)} onClick={create}>{busy?'Creating company…':'Create customer workplace and invite admin'}</button></section>
    <section className={card}><h2 className="text-lg font-semibold">Review a provider for a real workplace</h2><p className="my-2 text-sm text-slate-600">This step is for a real customer launch, not for trying the demo. Use an existing independent adult account and check the counselor’s current license with their state licensing board. MindGuard records your review; it does not check the board automatically.</p><div className="grid gap-3 sm:grid-cols-2"><input className="rounded-lg border p-3" type="email" placeholder="Provider’s existing account email" value={providerEmail} onChange={e=>setProviderEmail(e.target.value)} /><input className="rounded-lg border p-3" placeholder="Profession (for example, counselor)" value={professionalType} onChange={e=>setProfessionalType(e.target.value)} /><input className="rounded-lg border p-3" placeholder="Professional title / license (for example, LPC)" value={providerTitle} onChange={e=>setProviderTitle(e.target.value)} /><input className="rounded-lg border p-3" placeholder="Degree or qualification" value={qualification} onChange={e=>setQualification(e.target.value)} /><input className="rounded-lg border p-3" placeholder="State license number" value={registration} onChange={e=>setRegistration(e.target.value)} /><input className="rounded-lg border p-3" placeholder="State that issued the license" value={licenseState} onChange={e=>setLicenseState(e.target.value)} /><label className="text-sm font-medium">License effective date, if listed<input type="date" className="mt-1 w-full rounded-lg border p-3" value={credentialValidFrom} onChange={e=>setCredentialValidFrom(e.target.value)}/></label><label className="text-sm font-medium">License expiration date, if listed<input type="date" className="mt-1 w-full rounded-lg border p-3" value={credentialExpiresAt} onChange={e=>setCredentialExpiresAt(e.target.value)}/></label><label className="text-sm font-medium sm:col-span-2">Where and when you checked it<input className="mt-1 w-full rounded-lg border p-3" placeholder="State board lookup · YYYY-MM-DD" value={credentialReference} onChange={e=>setCredentialReference(e.target.value)} /><span className="mt-1 block text-xs font-normal text-slate-500">This is an audit note, not an uploaded document or automated check.</span></label></div><button className={`${button} mt-4`} disabled={busy||!providerEmail||!providerTitle||!qualification||!registration||!licenseState||credentialReference.trim().length<4} onClick={provisionProvider}>Record review and enable provider</button></section>
    <ProviderOperationsPanel />
    <section className={card}><h2 className="text-lg font-semibold">Workplace offboarding</h2><p className="mt-1 text-sm text-slate-600">Scheduled endings preserve access until the effective date. Termination never deletes a company or worker account.</p>{companies.filter(c=>c.offboarding&&c.offboarding.status!=='NOT_STARTED'&&c.offboarding.status!=='COMPLETED').length===0?<p className="mt-3 text-sm text-slate-500">No companies are currently scheduled for offboarding.</p>:<div className="mt-3 divide-y">{companies.filter(c=>c.offboarding&&c.offboarding.status!=='NOT_STARTED'&&c.offboarding.status!=='COMPLETED').map(c=><div key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div><p className="font-semibold">{c.name} · {c.offboarding?.status?.replaceAll('_',' ')}</p><p className="text-sm text-slate-600">Effective {c.offboarding?.effective_date||'date pending'} · continuity through {c.offboarding?.continuity_deadline?new Date(c.offboarding.continuity_deadline).toLocaleDateString():'not started'} · retention through {c.offboarding?.retention_deadline?new Date(c.offboarding.retention_deadline).toLocaleDateString():'not set'}</p><p className="text-xs text-slate-500">Active case obligations: {c.offboarding?.active_support_obligations??0} · provider relationships ending/ended: {c.offboarding?.provider_relationships_ending_or_ended??0}</p></div>{c.offboarding?.completion_ready&&<button className="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-800" disabled={busy} onClick={()=>void completeOffboarding(c)}>Finalize offboarding</button>}</div>)}</div>}</section>
    <section className="space-y-3"><h2 className="text-xl font-semibold">Companies and launch gates</h2>{loading&&<div role="status" className={`${card} animate-pulse text-sm text-slate-500`}>Loading company tenants and launch status…</div>}{companies.map(c=><article key={c.id} className={card}><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-lg font-semibold">{c.name}</h3><p className="text-sm text-slate-600">Approved work domains: {c.approved_work_email_domains.join(', ')}</p><p className="mt-1 text-xs text-slate-500">Employees: {c.employee_population_range||'not recorded'} · retention: {c.retention_days} days · company policy: {c.policy_status}</p><p className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Tenant access status · separate from commercial status</p></div><span className={`rounded-full px-3 py-1 text-xs font-semibold ${c.status==='ACTIVE'?'bg-emerald-100 text-emerald-800':c.status==='SUSPENDED'?'bg-amber-100 text-amber-900':'bg-slate-200 text-slate-700'}`}>{c.status}</span></div>{c.commercial&&<div className="mt-3 rounded-xl border border-teal-100 bg-teal-50/60 p-3"><div className="flex flex-wrap justify-between gap-2"><p className="font-semibold">Commercial account · {c.commercial.plan_name} · {c.commercial.status.replaceAll('_',' ')}</p>{c.commercial.action_required&&<span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-bold text-amber-900">Action required</span>}</div><p className="mt-1 text-sm text-slate-700">Period: {c.commercial.contract_start_date||'not set'} – {c.commercial.contract_end_date||'open-ended'} · band: {c.commercial.population_band} · renewal: {c.commercial.renewal_date||'not scheduled'}{c.commercial.grace_period_end?` · grace ends ${c.commercial.grace_period_end}`:''}</p></div>}<WorkplaceCommercialEditor key={`${c.id}-${c.commercial?.status}-${c.commercial?.plan_key}-${c.commercial?.contract_end_date}`} company={c} onSaved={()=>void load()}/><div className="mt-3 space-y-2 border-t pt-3">{c.administrators.map(a=><div key={a.id} className="flex flex-wrap items-center justify-between gap-2 text-sm"><span><strong>{a.name}</strong> · {a.email} · {a.status}</span>{!['active','approved'].includes(a.status.toLowerCase())&&<button disabled={busy} onClick={()=>void resendInvite(c.id,a.id)} className="font-semibold text-teal-800 underline">Resend invitation</button>}</div>)}</div>{!c.legal_review_complete && <div className="mt-4 rounded-xl bg-amber-50 p-4"><p className="text-sm text-amber-950">Record a completed US privacy/legal review and its internal reference only after review by qualified counsel and privacy professionals. This operational record does not certify legal compliance.</p><div className="mt-3 flex flex-col gap-2 sm:flex-row"><input className="min-w-0 flex-1 rounded-lg border p-3" placeholder="Privacy review record reference" value={reference} onChange={e=>setReference(e.target.value)} /><button className={button} disabled={busy || reference.trim().length<4} onClick={()=>recordReview(c.id)}>Record completed review</button></div></div>}{c.legal_review_reference && <p className="mt-3 text-xs text-slate-500">Review record: {c.legal_review_reference}</p>}<div className="mt-4 flex flex-wrap gap-2 border-t pt-3">{c.status==='SUSPENDED'&&<button disabled={busy} onClick={()=>void lifecycle(c.id,'activate')} className="rounded-lg border px-3 py-2 text-sm font-semibold">Reactivate tenant</button>}{c.status==='ACTIVE'&&<button disabled={busy} onClick={()=>void lifecycle(c.id,'suspend')} className="rounded-lg border border-amber-300 px-3 py-2 text-sm font-semibold text-amber-900">Suspend tenant</button>}{c.status!=='ARCHIVED'&&<button disabled={busy} onClick={()=>void lifecycle(c.id,'archive')} className="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-800">Archive tenant</button>}</div></article>)}{!loading&&companies.length===0&&<div className={card}><h3 className="font-semibold">No workplace company tenants yet</h3><p className="mt-1 text-sm text-slate-600">Create a company tenant above or convert a qualified company demo request.</p></div>}</section>
    {notice && <p role="status" className="rounded-xl bg-slate-100 p-3 text-sm">{notice}</p>}
    {confirmation&&<WorkplaceConfirmDialog message={confirmation.message} onCancel={()=>{confirmation.resolve(false);setConfirmation(null)}} onConfirm={()=>{confirmation.resolve(true);setConfirmation(null)}}/>}
  </main>
}

function ProviderOperationsPanel() {
  const [items,setItems]=useState<ManagedProvider[]>([])
  const [loading,setLoading]=useState(true)
  const [busy,setBusy]=useState(false)
  const [notice,setNotice]=useState('')
  const [error,setError]=useState('')
  const [confirmation,setConfirmation]=useState<{message:string;resolve:(confirmed:boolean)=>void}|null>(null)
  const confirmAction=(message:string)=>new Promise<boolean>(resolve=>setConfirmation({message,resolve}))
  const load=useCallback(async()=>{setLoading(true);setError('');try{setItems((await api.get('/v1/workplace/admin/provider-operations')).data)}catch(e){setError(e instanceof Error?e.message:'Unable to load provider operations.')}finally{setLoading(false)}},[])
  // This effect intentionally starts an API request; state updates happen after it settles.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(()=>{void load()},[load])
  const submitReview=async(provider:ManagedProvider,reviewId:string,decision:'verify'|'reject')=>{
    let verification_reference:string|undefined
    let valid_from:string|undefined
    let expires_at:string|undefined
    let reason:string|undefined
    if(decision==='verify'){
      verification_reference=window.prompt('Enter the reference for your human review of this credential:')||undefined
      if(!verification_reference||verification_reference.trim().length<4)return
      valid_from=window.prompt('Valid from date (YYYY-MM-DD), if applicable:')||undefined
      expires_at=window.prompt('Expiry date (YYYY-MM-DD), if applicable:')||undefined
    }else{
      reason=window.prompt('Reason for rejecting the updated credential:')||undefined
      if(!reason||reason.trim().length<3)return
    }
    setBusy(true);setNotice('')
    try{await api.post(`/v1/workplace/admin/provider-credential-reviews/${reviewId}`,{review_id:reviewId,decision,verification_reference,valid_from,expires_at,reason});setNotice(`${provider.name}’s credential review was ${decision==='verify'?'approved':'rejected'}.`);await load()}
    catch(e){setNotice(e instanceof Error?e.message:'Unable to save the credential review.')}
    finally{setBusy(false)}
  }
  const access=async(provider:ManagedProvider,action:'suspend'|'reactivate'|'revoke'|'deactivate')=>{
    const reason=window.prompt(`Reason to ${action} ${provider.name}’s workplace access:`)
    if(!reason||reason.trim().length<3)return
    if(!await confirmAction(`${action==='reactivate'?'Restore':action==='deactivate'?'Deactivate':action==='revoke'?'Revoke':'Suspend'} workplace access for ${provider.name}? Active cases will require worker-led reassignment; case data will not transfer automatically.`))return
    setBusy(true);setNotice('')
    try{await api.post(`/v1/workplace/admin/providers/${provider.id}/access`,{action,reason});setNotice(`Provider access updated: ${action}.`);await load()}
    catch(e){setNotice(e instanceof Error?e.message:'Unable to update provider access.')}
    finally{setBusy(false)}
  }
  const revokeCredential=async(provider:ManagedProvider)=>{
    const reason=window.prompt(`Reason to revoke ${provider.name}’s professional credential:`)
    if(!reason||reason.trim().length<3)return
    if(!await confirmAction('Revoke this credential? The provider will immediately lose workplace case access.'))return
    setBusy(true);setNotice('')
    try{await api.post(`/v1/workplace/admin/providers/${provider.id}/credential-revoke`,{reason});setNotice('Credential revoked; active cases require worker-led reassignment.');await load()}
    catch(e){setNotice(e instanceof Error?e.message:'Unable to revoke this credential.')}
    finally{setBusy(false)}
  }
  return <section className={card}><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-wider text-teal-700">MindGuard operations</p><h2 className="text-xl font-semibold">Provider credential and access lifecycle</h2><p className="mt-1 text-sm text-slate-600">For real providers, record a human state-license review. This view contains no worker case or wellbeing information.</p></div><button disabled={loading||busy} onClick={()=>void load()} className="rounded-lg border px-3 py-2 text-sm font-semibold">Refresh</button></div>{error&&<p role="alert" className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}{loading?<p role="status" className="mt-4 text-sm text-slate-500">Loading providers…</p>:!items.length?<p className="mt-4 rounded-lg bg-slate-50 p-4 text-sm text-slate-600">No providers have been reviewed yet.</p>:<div className="mt-4 space-y-3">{items.map(provider=><article key={provider.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-semibold">{provider.name}{provider.demo_only&&<span className="ml-2 rounded-full bg-sky-100 px-2 py-1 text-xs font-bold text-sky-800">Demo only</span>}</h3><p className="text-sm text-slate-600">{provider.email}{provider.professional_type?` · ${provider.professional_type}`:''}{provider.title?` · ${provider.title}`:''}{provider.license_state?` · ${provider.license_state}`:''}</p><p className="mt-1 text-xs text-slate-500">{provider.demo_only?'Synthetic sample; not a real licensed provider.':`License review: ${provider.credential_status.replaceAll('_',' ')}${provider.expires_at?` · expires ${provider.expires_at}`:''} · access: ${provider.access_status} · availability: ${provider.availability}`}</p><p className="mt-1 text-xs text-slate-500">Workplace associations: {provider.associations.map(item=>`${item.name} (${item.status})`).join(', ')||'none'}</p></div>{!provider.demo_only&&<div className="flex flex-wrap gap-2">{provider.access_status==='active'?<button disabled={busy} onClick={()=>void access(provider,'suspend')} className="rounded-lg border border-amber-300 px-3 py-2 text-xs font-semibold text-amber-900">Suspend access</button>:<button disabled={busy} onClick={()=>void access(provider,'reactivate')} className="rounded-lg border px-3 py-2 text-xs font-semibold">Reactivate access</button>}<button disabled={busy} onClick={()=>void revokeCredential(provider)} className="rounded-lg border border-rose-300 px-3 py-2 text-xs font-semibold text-rose-800">Revoke credential</button></div>}</div>{provider.pending_reviews.map(pendingReview=><div key={pendingReview.id} className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3"><p className="text-sm font-semibold text-amber-950">Updated license · review pending</p><p className="mt-1 text-sm">{pendingReview.professional_type?`${pendingReview.professional_type} · `:''}{pendingReview.title} · {pendingReview.qualification}</p><p className="mt-1 text-xs text-slate-600">License {pendingReview.registration_number} · {pendingReview.license_state||'state not recorded'} · submitted {new Date(pendingReview.submitted_at).toLocaleDateString()}</p><div className="mt-3 flex flex-wrap gap-2"><button disabled={busy} onClick={()=>void submitReview(provider,pendingReview.id,'verify')} className={button}>Verify license</button><button disabled={busy} onClick={()=>void submitReview(provider,pendingReview.id,'reject')} className="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-800">Reject update</button></div></div>)}</article>)}</div>}{notice&&<p role="status" className="mt-4 rounded-lg bg-slate-100 p-3 text-sm">{notice}</p>}{confirmation&&<WorkplaceConfirmDialog message={confirmation.message} onCancel={()=>{confirmation.resolve(false);setConfirmation(null)}} onConfirm={()=>{confirmation.resolve(true);setConfirmation(null)}}/>}</section>
}

function ProviderCaseList() {
  const [cases, setCases] = useState<Array<{case_id:string;employee_name:string;employee_email:string;status:string;created_at:string;shared_checkin?:Record<string,number>}>>([])
  const [providerStatus,setProviderStatus]=useState<{credential_status:string;credential_valid:boolean;reverification_pending:boolean;valid_from?:string|null;expires_at?:string|null;access_status:string;availability:string;active_case_count:number;action_required_count:number;can_receive_new_cases:boolean}|null>(null)
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
  const [confirmation, setConfirmation] = useState<{message:string;resolve:(confirmed:boolean)=>void}|null>(null)
  const [credentialSubmission,setCredentialSubmission]=useState({professional_type:'',professional_title:'',qualification:'',registration_number:''})
  const [statusBusy,setStatusBusy]=useState(false)
  const confirmAction=(message:string)=>new Promise<boolean>(resolve=>setConfirmation({message,resolve}))
  const loadStatus=async()=>{try{setProviderStatus((await api.get('/v1/workplace/provider/status')).data)}catch(e){setError(e instanceof Error?e.message:'Unable to load provider status.')}}
  const load=async()=>{try{setCases((await api.get('/v1/workplace/provider/cases')).data)}catch(e){setError(e instanceof Error?e.message:'Unable to load shared cases.')}}
  useEffect(()=>{let active=true;Promise.allSettled([api.get('/v1/workplace/provider/status'),api.get('/v1/workplace/provider/cases')]).then(([statusResult,casesResult])=>{if(!active)return;if(statusResult.status==='fulfilled')setProviderStatus(statusResult.value.data);else setError(statusResult.reason instanceof Error?statusResult.reason.message:'Unable to load provider status.');if(casesResult.status==='fulfilled')setCases(casesResult.value.data);else setError(casesResult.reason instanceof Error?casesResult.reason.message:'Unable to load shared cases.')});return()=>{active=false}},[])
  const setAvailability=async(availability:'available'|'unavailable')=>{setStatusBusy(true);try{await api.post('/v1/workplace/provider/availability',{availability});await loadStatus()}catch(e){setError(e instanceof Error?e.message:'Unable to update availability.')}finally{setStatusBusy(false)}}
  const submitReverification=async()=>{setStatusBusy(true);try{await api.post('/v1/workplace/provider/credentials/reverification',credentialSubmission);setCredentialSubmission({professional_type:'',professional_title:'',qualification:'',registration_number:''});await loadStatus()}catch(e){setError(e instanceof Error?e.message:'Unable to submit credential update.')}finally{setStatusBusy(false)}}
  const leaveWorkplace=async()=>{if(!await confirmAction('Deactivate your workplace provider access? Your active cases will be marked for worker-led reassignment; no case content will be sent to another provider without the worker’s confirmation.'))return;setStatusBusy(true);try{await api.post('/v1/workplace/provider/departure');await loadStatus();setCases([])}catch(e){setError(e instanceof Error?e.message:'Unable to start provider departure.')}finally{setStatusBusy(false)}}
  const open=async(id:string)=>{setSelected(id);setNotice('');try{const [d,m]=await Promise.all([api.get(`/v1/workplace/provider/cases/${id}`),api.get(`/v1/workplace/provider/cases/${id}/messages`)]);setDetail(d.data);setMessages(m.data)}catch(e){setError(e instanceof Error?e.message:'Unable to open this case.')}}
  const saveNote=async()=>{if(!selected||!privateNote.trim())return;setBusy(true);setNotice('');try{await api.post(`/v1/workplace/provider/cases/${selected}/notes`,{private_note:privateNote,employee_update:employeeUpdate||null});setPrivateNote('');setEmployeeUpdate('');setNotice('Private case note saved. The employee update was shared only because you entered one.');await open(selected)}catch(e){setNotice(e instanceof Error?e.message:'Unable to save case note.')}finally{setBusy(false)}}
  const sendReply=async()=>{if(!selected||!reply.trim())return;setBusy(true);try{await api.post(`/v1/workplace/provider/cases/${selected}/messages`,{message:reply});setReply('');setMessages((await api.get(`/v1/workplace/provider/cases/${selected}/messages`)).data)}catch(e){setNotice(e instanceof Error?e.message:'Unable to send message.')}finally{setBusy(false)}}
  const schedule=async()=>{if(!selected||!appointment.starts_at||!appointment.location_or_link.trim())return;setBusy(true);try{await api.post(`/v1/workplace/provider/cases/${selected}/appointments`,{...appointment,starts_at:new Date(appointment.starts_at).toISOString()});setAppointment({starts_at:'',mode:'online',location_or_link:''});setNotice('Appointment scheduled and the employee was notified.')}catch(e){setNotice(e instanceof Error?e.message:'Unable to schedule appointment.')}finally{setBusy(false)}}
  const close=async()=>{if(!selected||!await confirmAction('Close this support case? Future provider access ends, and the employee can request support again later.'))return;try{await api.post(`/v1/workplace/provider/cases/${selected}/close`);setNotice('Support case closed.');setSelected('');setDetail(null);await load()}catch(e){setNotice(e instanceof Error?e.message:'Unable to close case.') }}
  return <div className="space-y-5">{confirmation&&<WorkplaceConfirmDialog message={confirmation.message} onCancel={()=>{confirmation.resolve(false);setConfirmation(null)}} onConfirm={()=>{confirmation.resolve(true);setConfirmation(null)}}/>}<section className={card}><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-wider text-teal-700">Provider operations</p><h2 className="text-lg font-semibold">Your workplace access</h2><p className="mt-1 text-sm text-slate-600">Availability affects new assignments only. Existing cases remain accessible while your account and credential are valid.</p></div>{providerStatus&&<span className={`rounded-full px-3 py-1 text-xs font-bold uppercase ${providerStatus.can_receive_new_cases?'bg-emerald-100 text-emerald-800':'bg-amber-100 text-amber-900'}`}>{providerStatus.can_receive_new_cases?'Available for new support':providerStatus.credential_valid?'Not receiving new cases':'Review required'}</span>}</div>{providerStatus&&<div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div className="rounded-xl bg-slate-50 p-3"><p className="text-xs uppercase text-slate-500">Credential</p><p className="mt-1 font-semibold capitalize">{providerStatus.credential_status.replaceAll('_',' ')}</p></div><div className="rounded-xl bg-slate-50 p-3"><p className="text-xs uppercase text-slate-500">Valid until</p><p className="mt-1 font-semibold">{providerStatus.expires_at||'No expiry recorded'}</p></div><div className="rounded-xl bg-slate-50 p-3"><p className="text-xs uppercase text-slate-500">Active cases</p><p className="mt-1 font-semibold">{providerStatus.active_case_count}</p></div><div className="rounded-xl bg-slate-50 p-3"><p className="text-xs uppercase text-slate-500">Needs action</p><p className="mt-1 font-semibold">{providerStatus.action_required_count}</p></div></div>}{providerStatus?.reverification_pending&&<p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Your updated credential details are awaiting MindGuard review.</p>}{providerStatus?.credential_valid&&providerStatus.access_status==='active'&&<div className="mt-4 flex flex-wrap gap-2"><button disabled={statusBusy||providerStatus.availability==='available'} onClick={()=>void setAvailability('available')} className={button}>Available for new cases</button><button disabled={statusBusy||providerStatus.availability==='unavailable'} onClick={()=>void setAvailability('unavailable')} className="rounded-xl border px-4 py-2.5 text-sm font-semibold disabled:opacity-50">Temporarily unavailable</button></div>}<details className="mt-4 rounded-xl border p-4"><summary className="cursor-pointer font-semibold">Submit updated credential details</summary><p className="mt-2 text-sm text-slate-600">MindGuard will review your updated professional information. Registry verification is performed by a human reviewer, not automatically by this form.</p><div className="mt-3 grid gap-3 sm:grid-cols-2">{(['professional_type','professional_title','qualification','registration_number'] as const).map(key=><label key={key} className="text-sm font-medium">{key.replaceAll('_',' ')}<input className="mt-1 w-full rounded-lg border p-3" value={credentialSubmission[key]} onChange={e=>setCredentialSubmission(current=>({...current,[key]:e.target.value}))}/></label>)}</div><button className={`${button} mt-3`} disabled={statusBusy||credentialSubmission.professional_title.trim().length<2||credentialSubmission.qualification.trim().length<2||credentialSubmission.registration_number.trim().length<2} onClick={()=>void submitReverification()}>{statusBusy?'Submitting…':'Submit for review'}</button></details><button className="mt-4 text-sm font-semibold text-rose-800 underline" disabled={statusBusy||providerStatus?.access_status==='deactivated'} onClick={()=>void leaveWorkplace()}>Leave workplace provider network</button></section><section className="grid gap-5 xl:grid-cols-[.8fr_1.2fr]">{error&&<p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800 xl:col-span-2">{error}</p>}<div className="space-y-3">{!cases.length&&!error&&<div className={card}>No active cases are currently assigned to you.</div>}{cases.map(c=><button key={c.case_id} onClick={()=>void open(c.case_id)} className={`w-full rounded-2xl border bg-white p-4 text-left shadow-sm ${selected===c.case_id?'border-teal-700':'border-slate-200'}`}><div className="flex flex-wrap justify-between gap-2"><strong>{c.employee_name}</strong><span className="text-xs font-semibold uppercase text-teal-800">{c.status}</span></div><p className="text-sm text-slate-600">{c.employee_email}</p><p className="mt-2 text-xs text-slate-500">Support shared {new Date(c.created_at).toLocaleDateString()}</p></button>)}</div>
    {detail&&selected?<div className="space-y-4"><article className={card}><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-bold">{detail.case.name}</h2><p className="text-sm text-slate-600">{detail.case.email}</p></div><span className="text-sm font-semibold capitalize text-teal-800">{detail.case.status}</span></div><p className="mt-3 text-xs text-slate-500">This employee explicitly requested support and shared the following check-in with you.</p>{cases.find(c=>c.case_id===selected)?.shared_checkin&&<dl className="mt-3 grid gap-2 sm:grid-cols-3">{Object.entries(cases.find(c=>c.case_id===selected)?.shared_checkin||{}).map(([key,value])=><div key={key} className="rounded-lg bg-slate-50 p-3"><dt className="text-xs capitalize text-slate-500">{key.replace('_',' ')}</dt><dd className="font-semibold">{value}/5</dd></div>)}</dl>}</article>
      <section className={card}><h3 className="font-bold">Case notes</h3><p className="mt-1 text-xs text-slate-500">Private notes stay in the provider workspace. Enter a separate plain-language update only when you want the employee to see it.</p><div className="mt-3 space-y-2"><textarea className="min-h-24 w-full rounded-lg border p-3" placeholder="Private care note" value={privateNote} onChange={e=>setPrivateNote(e.target.value)}/><textarea className="min-h-20 w-full rounded-lg border p-3" placeholder="Optional employee-safe update" value={employeeUpdate} onChange={e=>setEmployeeUpdate(e.target.value)}/><button disabled={busy||!privateNote.trim()} onClick={()=>void saveNote()} className={button}>Save case note</button></div>{detail.notes.map(note=><article key={note.id} className="mt-3 rounded-lg bg-slate-50 p-3 text-sm"><time className="text-xs text-slate-500">{new Date(note.created_at).toLocaleString()}</time><p className="mt-1"><strong>Private:</strong> {note.private_note}</p>{note.employee_update&&<p className="mt-1 text-teal-900"><strong>Shared:</strong> {note.employee_update}</p>}</article>)}</section>
      <section className={card}><h3 className="font-bold">Private communication</h3><div className="mt-3 max-h-52 space-y-2 overflow-y-auto">{messages.map(m=><p key={m.id} className={`max-w-[90%] rounded-xl p-3 text-sm ${m.from_me?'ml-auto bg-teal-50':'bg-slate-50'}`}>{m.message}<time className="mt-1 block text-[10px] text-slate-500">{new Date(m.created_at).toLocaleString()}</time></p>)}</div>{detail.case.status==='open'&&<div className="mt-3 flex flex-col gap-2 sm:flex-row"><input className="min-w-0 flex-1 rounded-lg border p-3" value={reply} onChange={e=>setReply(e.target.value)} placeholder="Message the employee"/><button className={button} disabled={busy||!reply.trim()} onClick={()=>void sendReply()}>Send</button></div>}</section>
      {detail.case.status==='open'&&<section className={card}><h3 className="font-bold">Schedule an appointment</h3><div className="mt-3 grid gap-3 sm:grid-cols-2"><input type="datetime-local" className="rounded-lg border p-3" value={appointment.starts_at} onChange={e=>setAppointment({...appointment,starts_at:e.target.value})}/><select className="rounded-lg border p-3" value={appointment.mode} onChange={e=>setAppointment({...appointment,mode:e.target.value})}><option value="online">Online</option><option value="physical">In person</option></select><input className="rounded-lg border p-3 sm:col-span-2" placeholder={appointment.mode==='online'?'Secure HTTPS meeting link':'Meeting location'} value={appointment.location_or_link} onChange={e=>setAppointment({...appointment,location_or_link:e.target.value})}/></div><button className={`${button} mt-3`} disabled={busy||!appointment.starts_at||!appointment.location_or_link} onClick={()=>void schedule()}>Schedule and notify</button></section>}
      {notice&&<p role="status" className="rounded-xl bg-slate-100 p-3 text-sm">{notice}</p>}{detail.case.status==='open'&&<button onClick={()=>void close()} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800">Close support case</button>}</div>:<div className={`${card} flex items-center justify-center text-center text-sm text-slate-500`}>Select a shared case to review consented information and provide support.</div>}</section></div>
}

function EmployeeMessagesPage(){
  const [cases,setCases]=useState<Array<{id:string;status:string;created_at:string}>>([]);const [caseId,setCaseId]=useState('');const [messages,setMessages]=useState<Array<{id:string;from_me:boolean;message:string;created_at:string}>>([]);const [draft,setDraft]=useState('');const [notice,setNotice]=useState('')
  const load=async()=>{try{const [c,m]=await Promise.all([api.get('/v1/workplace/support-requests'),api.get('/v1/workplace/support/messages')]);const active=c.data.filter((item:{status:string})=>['open','active'].includes(item.status));setCases(active);setCaseId((current:string)=>active.some((item:{id:string})=>item.id===current)?current:active[0]?.id||'');setMessages(m.data)}catch(e){setNotice(e instanceof Error?e.message:'Unable to load private messages.')}}
  useEffect(()=>{let active=true;const refresh=()=>Promise.all([api.get('/v1/workplace/support-requests'),api.get('/v1/workplace/support/messages')]).then(([c,m])=>{if(!active)return;const activeCases=c.data.filter((item:{status:string})=>['open','active'].includes(item.status));setCases(activeCases);setCaseId(current=>activeCases.some((item:{id:string})=>item.id===current)?current:activeCases[0]?.id||'');setMessages(m.data)}).catch(e=>{if(active)setNotice(e instanceof Error?e.message:'Unable to load private messages.')});void refresh();const timer=window.setInterval(()=>void refresh(),15000);return()=>{active=false;window.clearInterval(timer)}},[])
  const send=async()=>{if(!caseId||!draft.trim())return;try{await api.post('/v1/workplace/support/messages',{case_id:caseId,message:draft});setDraft('');await load()}catch(e){setNotice(e instanceof Error?e.message:'Unable to send message.')}}
  return <main className="mx-auto max-w-4xl space-y-5"><header><p className="text-xs font-bold uppercase tracking-widest text-teal-700">Private care communication</p><h1 className="mt-1 text-3xl font-bold">Messages with your provider</h1><p className="mt-2 text-sm text-slate-600">These messages are visible only to you and the independent provider for the support case you opened. Your employer cannot read them.</p></header>{!cases.length?<section className={card}>There is no active shared support case yet. Request support and explicitly share information with a provider to open a private conversation.</section>:<section className={card}><label className="text-sm font-semibold">Support request<select className="mt-1 block w-full rounded-lg border p-3" value={caseId} onChange={e=>setCaseId(e.target.value)}>{cases.map(c=><option key={c.id} value={c.id}>Request from {new Date(c.created_at).toLocaleDateString()} · {c.status}</option>)}</select></label><div className="mt-4 max-h-[55vh] min-h-48 space-y-3 overflow-y-auto rounded-xl bg-slate-50 p-4" aria-live="polite">{messages.filter(m=>m.created_at).map(m=><article key={m.id} className={`max-w-[88%] rounded-xl p-3 text-sm ${m.from_me?'ml-auto bg-teal-100':'bg-white shadow-sm'}`}><p>{m.message}</p><time className="mt-1 block text-[10px] text-slate-500">{new Date(m.created_at).toLocaleString()}</time></article>)}</div><div className="mt-3 flex flex-col gap-2 sm:flex-row"><input className="min-w-0 flex-1 rounded-lg border p-3" value={draft} onChange={e=>setDraft(e.target.value)} placeholder="Write a private message"/><button className={button} disabled={!draft.trim()||!caseId} onClick={()=>void send()}>Send message</button></div></section>}{notice&&<p role="status" className="rounded-xl bg-slate-100 p-3 text-sm">{notice}</p>}</main>
}

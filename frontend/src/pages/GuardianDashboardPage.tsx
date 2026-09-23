import { useEffect, useState } from 'react'
import api from '../api/client'

type GuardianConsent = { id: string; status: string; student_name: string; institution_name?: string; accepted_at?: string; expires_at?: string }
export default function GuardianDashboardPage() {
  const [consents, setConsents] = useState<GuardianConsent[]>([])
  const [error, setError] = useState('')
  const load = () => api.get('/guardian/consents').then(({ data }) => setConsents(data.consents || [])).catch(() => setError('Unable to load your consent records.'))
  useEffect(() => { load() }, [])
  const revoke = async (id: string) => { if (!window.confirm('Withdraw consent? This immediately stops institution wellbeing access.')) return; try { await api.post(`/guardian/consents/${id}/revoke`); load() } catch { setError('Unable to withdraw consent.') } }
  return <div className="mx-auto max-w-4xl p-6 md:p-9"><p className="text-xs font-bold uppercase tracking-widest text-[#0f766e]">Guardian portal</p><h1 className="mt-2 text-2xl font-bold text-slate-800">Consent management</h1><p className="mt-2 text-sm text-slate-500">This portal manages consent only. It does not display counselling records, analyses, messages, or alerts.</p>{error && <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}<div className="mt-6 grid gap-4">{consents.map((consent) => <article key={consent.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-bold text-slate-800">{consent.student_name}</h2><p className="mt-1 text-sm text-slate-500">{consent.institution_name || 'Institution'} · {consent.status}</p></div>{consent.status === 'ACCEPTED' && <button onClick={() => revoke(consent.id)} className="rounded-lg border border-red-200 px-3 py-2 text-xs font-semibold text-red-700">Withdraw consent</button>}</div></article>)}{!consents.length && <div className="rounded-2xl border border-dashed border-slate-300 p-8 text-sm text-slate-500">No consent records are linked to this guardian account.</div>}</div></div>
}

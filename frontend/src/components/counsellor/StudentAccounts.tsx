/* eslint-disable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps */
import { useEffect, useState } from 'react'
import { getStudentSocialAccounts, requestAccountReverification, type StudentSocialAccount } from '../../api/counsellor'

export default function StudentAccounts({ studentId }: { studentId: string }) {
  const [accounts, setAccounts] = useState<StudentSocialAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const load = async () => { setLoading(true); try { setAccounts(await getStudentSocialAccounts(studentId)) } catch { setError('Account status could not be loaded.') } finally { setLoading(false) } }
  useEffect(() => { void load() }, [studentId])
  const request = async (account: StudentSocialAccount) => { setBusy(account.platform); setMessage(''); setError(''); try { await requestAccountReverification(studentId, account.platform); setMessage(`The student was asked to verify ${account.platform} again.`); await load() } catch { setError('The reverification request could not be sent.') } finally { setBusy(null) } }
  return <div className="rounded-xl border border-[rgba(229,231,235,0.7)] bg-white">
    <div className="border-b border-[#f1f5f9] px-5 py-3"><h3 className="flex items-center gap-2 text-[0.9rem] font-bold text-[#1f2937]"><i className="ti ti-link text-[#0f766e]" /> Student account verification</h3><p className="mt-1 text-[0.72rem] text-[#6b7280]">You can view status and request reverification. Only the student can change the account.</p></div>
    <div className="p-5">{loading ? <p className="text-sm text-slate-500">Loading account status…</p> : accounts.length === 0 ? <p className="text-sm text-slate-500">No social accounts have been connected.</p> : <div className="space-y-3">{accounts.map(account => { const verified = account.verification_status === 'verified' && !account.reverification_required && account.availability_status !== 'unavailable'; const unavailable = account.availability_status === 'unavailable'; return <div key={account.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="flex items-start justify-between gap-3"><div><p className="font-semibold capitalize text-slate-800">{account.platform}</p><p className="text-xs text-slate-500">{account.handle || account.profile_url || 'Profile not supplied'}</p><p className="mt-1 text-[11px] text-slate-500">Method: {account.verification_method === 'oauth' ? 'Official connection' : 'Public profile code'}{account.last_verified_at ? ` · Verified ${new Date(account.last_verified_at).toLocaleDateString()}` : ''}</p></div><span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase ${verified ? 'bg-emerald-100 text-emerald-700' : unavailable ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>{verified ? 'verified' : unavailable ? 'unavailable' : 'verification needed'}</span></div><button disabled={busy === account.platform} onClick={() => void request(account)} className="mt-3 rounded-md border border-[#0f766e] px-3 py-1.5 text-xs font-semibold text-[#0f766e] disabled:opacity-50">{busy === account.platform ? 'Sending…' : verified ? 'Request reverification' : 'Request verification'}</button></div> })}</div>}{message && <p className="mt-3 text-xs text-emerald-700">{message}</p>}{error && <p className="mt-3 text-xs text-red-700">{error}</p>}</div>
  </div>
}

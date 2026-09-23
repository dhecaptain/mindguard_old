import { useState } from 'react'
import { setToken } from '../lib/tokenStorage'
import { useAuthStore } from '../store/authStore'

const apiBase = import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://127.0.0.1:8000/api' : '/api')

export default function GuardianSetupPage() {
  const token = new URLSearchParams(window.location.search).get('token') || ''
  const setAuth = useAuthStore((state) => state.setAuth)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const submit = async () => {
    if (!token || password.length < 8 || password !== confirm) { setError('Use matching passwords with at least 8 characters.'); return }
    setSaving(true); setError('')
    try {
      const response = await fetch(`${apiBase}/v1/portal/consents/${token}/guardian-account`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, password }) })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || 'Unable to create guardian account.')
      setToken(data.access_token); setAuth({ ...data.user, role: data.user.role_type, referral_code: '', terms_accepted: true })
      window.location.href = '/'
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to create guardian account.') } finally { setSaving(false) }
  }
  return <div className="flex min-h-screen items-center justify-center bg-slate-50 p-5"><div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-7 shadow-sm"><p className="text-xs font-bold uppercase tracking-widest text-[#0f766e]">MindGuard guardian portal</p><h1 className="mt-2 text-2xl font-bold text-slate-800">Manage consent securely</h1><p className="mt-2 text-sm leading-6 text-slate-500">Creating an account is optional. It lets you review and revoke consent for the child linked to this verified email. It does not show counselling records.</p><div className="mt-5 space-y-3"><input value={name} onChange={(event) => setName(event.target.value)} placeholder="Your full name" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" /><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Choose password" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" /><input type="password" value={confirm} onChange={(event) => setConfirm(event.target.value)} placeholder="Confirm password" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" />{error && <p className="text-sm text-red-700">{error}</p>}<button disabled={saving} onClick={submit} className="w-full rounded-lg bg-[#0f766e] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{saving ? 'Creating account…' : 'Create guardian account'}</button></div></div></div>
}

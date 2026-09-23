import { useState, useEffect } from 'react'
import api from '../api/client'
import { setToken } from '../lib/tokenStorage'
import { useAuthStore } from '../store/authStore'
import { useUiStore } from '../store/uiStore'

export default function InvitePage() {
  const params = new URLSearchParams(window.location.search)
  const token = params.get('token') || ''

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [status, setStatus] = useState<'loading' | 'ready' | 'done' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const setAuth = useAuthStore((state) => state.setAuth)
  const setPage = useUiStore((state) => state.setPage)

  useEffect(() => {
    if (!token) {
      setError('Missing invitation token')
      setStatus('error')
      return
    }
    api.post('/auth/invite/verify', { token })
      .then(({ data }) => {
        setEmail(data.email || '')
        setStatus('ready')
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : 'Invalid or expired invitation'
        setError(msg)
        setStatus('error')
      })
  }, [token])

  const handleSubmit = async () => {
    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const { data } = await api.post('/auth/invite/accept', { token, password })
      if (data.access_token && data.user) {
        setToken(data.access_token)
        setAuth({ ...data.user, role: data.user.role_type, referral_code: '', terms_accepted: false, user_category: data.user.user_category })
        setPage(data.user.role_type === 'school_admin' || data.user.role_type === 'counsellor' ? 'institution' : 'dashboard')
        window.location.href = '/'
      } else setStatus('done')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to accept invitation'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (status === 'loading') {
    return (
      <div className="min-h-screen bg-[#f7f9fb] flex items-center justify-center">
        <div className="flex items-center gap-[10px] text-[#6b7280] text-[0.9rem]">
          <div className="w-[20px] h-[20px] border-2 border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin" />
          Loading invitation...
        </div>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="min-h-screen bg-[#f7f9fb] flex items-center justify-center p-[20px]">
        <div className="bg-white rounded-xl border border-[#e5e7eb] p-[32px] max-w-[420px] w-full text-center">
          <i className="ti ti-alert-circle text-[32px] text-[#dc2626] mb-[12px]" />
          <h2 className="text-[1.1rem] font-bold text-[#1f2937] mb-[8px]">Invitation invalid</h2>
          <p className="text-[0.85rem] text-[#6b7280] mb-[16px]">{error}</p>
          <a href="/" className="inline-block px-[18px] py-[9px] bg-[#0F766E] text-white rounded-[8px] text-[0.85rem] font-semibold">Go to home</a>
        </div>
      </div>
    )
  }

  if (status === 'done') {
    return (
      <div className="min-h-screen bg-[#f7f9fb] flex items-center justify-center p-[20px]">
        <div className="bg-white rounded-xl border border-[#e5e7eb] p-[32px] max-w-[420px] w-full text-center">
          <i className="ti ti-circle-check text-[32px] text-[#0F766E] mb-[12px]" />
          <h2 className="text-[1.1rem] font-bold text-[#1f2937] mb-[8px]">Account activated</h2>
          <p className="text-[0.85rem] text-[#6b7280] mb-[16px]">Your password has been set. You can now sign in.</p>
          <a href="/" className="inline-block px-[18px] py-[9px] bg-[#0F766E] text-white rounded-[8px] text-[0.85rem] font-semibold">Sign in</a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#f7f9fb] flex items-center justify-center p-[20px]">
      <div className="bg-white rounded-xl border border-[#e5e7eb] p-[32px] max-w-[420px] w-full">
        <h2 className="text-[1.2rem] font-bold text-[#1f2937] mb-[4px]">Accept invitation</h2>
        <p className="text-[0.82rem] text-[#6b7280] mb-[20px]">{email ? `For ${email}` : 'Set your password to activate your MindGuard account.'}</p>

        <div className="flex flex-col gap-[12px]">
          <div>
            <label className="text-[0.72rem] font-bold text-[#374151] uppercase tracking-[0.06em] mb-[6px] block">New password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters" className="w-full bg-[#fafbfc] border border-[#e5e7eb] rounded-[8px] px-[12px] py-[9px] text-[0.85rem] outline-none focus:border-[#0F766E]" />
          </div>
          <div>
            <label className="text-[0.72rem] font-bold text-[#374151] uppercase tracking-[0.06em] mb-[6px] block">Confirm password</label>
            <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Repeat password" className="w-full bg-[#fafbfc] border border-[#e5e7eb] rounded-[8px] px-[12px] py-[9px] text-[0.85rem] outline-none focus:border-[#0F766E]" />
          </div>

          {error && (
            <div className="px-[12px] py-[8px] bg-[#fee2e2] border border-[#fca5a5] rounded-[8px] text-[0.78rem] text-[#991b1b]">{error}</div>
          )}

          <button onClick={handleSubmit} disabled={submitting || !password} className="w-full mt-[8px] px-[16px] py-[10px] bg-[#0F766E] text-white rounded-[8px] text-[0.85rem] font-semibold disabled:opacity-50 hover:bg-[#115E59]">
            {submitting ? 'Activating…' : 'Activate account'}
          </button>
        </div>
      </div>
    </div>
  )
}

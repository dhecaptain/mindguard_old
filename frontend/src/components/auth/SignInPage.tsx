/* eslint-disable @typescript-eslint/no-explicit-any, react-hooks/set-state-in-effect */
import { useState, useEffect } from 'react'
import { useAuthStore } from '../../store'
import { useUiStore } from '../../store'
import { login, register } from '../../api/auth'
import { getSupabase, isSupabaseAvailable } from '../../lib/supabase'

interface SignInPageProps {
  onSuccess: () => void
}

export default function SignInPage({ onSuccess }: SignInPageProps) {
  const { setAuth } = useAuthStore()
  const setPage = useUiStore((s) => s.setPage)
  const [tab, setTab] = useState<'signin' | 'register'>('signin')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const [regName, setRegName] = useState('')
  const [regEmail, setRegEmail] = useState('')
  const [regPassword, setRegPassword] = useState('')
  const [regDob, setRegDob] = useState('')
  const [regParentEmail, setRegParentEmail] = useState('')
  const [regReferredBy, setRegReferredBy] = useState('')
  const [isMinor, setIsMinor] = useState(false)

  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const ref = params.get('ref')
    if (ref) {
      setRegReferredBy(ref.toUpperCase())
      setTab('register')
    }
  }, [])

  const handleLogin = async () => {
    setError('')
    setLoading(true)
    try {
      const user = await login(email, password)
      setAuth(user)
      const rt = user.role_type?.toLowerCase()
      if (rt === 'counsellor') setPage('counsellor-dashboard')
      else if (rt === 'school_admin') setPage('institution')
      else if (rt === 'admin') setPage('admin')
      onSuccess()
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  const handleRegister = async () => {
    setError('')
    if (isMinor && !regParentEmail) {
      setError('A parent or guardian email is required for students under 18')
      return
    }
    setLoading(true)
    try {
      await register({
        name: regName, email: regEmail, password: regPassword,
        role: 'student', dob: regDob || undefined,
        parent_email: isMinor ? regParentEmail : undefined,
        referred_by: regReferredBy || undefined,
      })
      setTab('signin')
      setEmail(regEmail)
      setPassword('')
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  const handleGoogleSignIn = async () => {
    setError('')
    try {
      const { error: oauthError } = await getSupabase().auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: `${window.location.origin}/auth/callback` },
      })
      if (oauthError) {
        if (oauthError.message?.toLowerCase().includes('provider')) {
          setError('Google sign-in is not configured yet. Please use email and password.')
        } else {
          setError(oauthError.message || 'Google sign-in failed')
        }
      }
    } catch {
      setError('Google sign-in is unavailable. Please use email and password.')
    }
  }

  const inputClass =
    'w-full bg-[#fafbfc] border-[1.5px] border-[#e5e7eb] rounded-[8px] px-[14px] py-[10px] text-[0.9rem] text-[#4b5563] outline-none focus:border-[#0F766E] transition-colors'
  const labelClass =
    'text-[0.7rem] font-bold text-[#374151] uppercase tracking-[0.06em] mb-[6px] block'

  return (
    <div className="min-h-screen bg-[#f7f9fb] flex items-center justify-center p-4 sm:p-6">
      <div className="flex flex-col sm:flex-row w-full max-w-[1060px] bg-white rounded-2xl overflow-hidden shadow-sm border border-[rgba(229,231,235,0.5)]">

        {/* Left panel — collapses to a compact banner on mobile */}
        <div className="sm:w-[300px] lg:w-[380px] sm:flex-shrink-0 bg-gradient-to-br from-[#0a1f1d] to-[#0d322e] p-6 sm:p-8 lg:p-9 flex flex-col justify-between">
          <div>
            <div className="flex items-center gap-3 mb-4 sm:mb-7">
              <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-lg bg-gradient-to-br from-[#0F766E] to-[#1D9E75] flex items-center justify-center text-white font-extrabold text-[0.85rem]">
                MG
              </div>
              <span className="text-white text-[1.05rem] sm:text-[1.1rem] font-bold">MindGuard</span>
            </div>
            <h1 className="text-white text-[1.2rem] sm:text-[1.5rem] font-bold leading-snug mb-3 hidden sm:block">
              Consent-first clinical decision support
            </h1>
            <p className="text-[#94a3b8] text-[0.82rem] leading-relaxed hidden sm:block">
              Powered by Mental-RoBERTa. Human-in-the-loop. Research use only.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 mt-4 sm:mt-0">
            {['HIPAA-aligned', '92.5% accuracy', '12.6K trained', 'Ethics approved'].map((pill) => (
              <span
                key={pill}
                className="px-[10px] py-[3px] rounded-full text-[0.62rem] sm:text-[0.65rem] font-semibold bg-[rgba(15,118,110,0.2)] text-[#34d399] border border-[rgba(52,211,153,0.15)]"
              >
                {pill}
              </span>
            ))}
          </div>
        </div>

        {/* Right panel */}
        <div className="flex-1 p-6 sm:p-8 lg:p-11">
          {/* Tabs */}
          <div className="flex mb-6 border-b border-[#f1f5f9]">
            {(['signin', 'register'] as const).map((t) => (
              <button
                key={t}
                onClick={() => { setTab(t); setError('') }}
                className={`pb-2.5 px-4 sm:px-5 text-[0.88rem] font-semibold border-b-2 transition-colors cursor-pointer ${
                  tab === t
                    ? 'text-[#0F766E] border-[#0F766E]'
                    : 'text-[#94a3b8] border-transparent hover:text-[#6b7280]'
                }`}
              >
                {t === 'signin' ? 'Sign In' : 'Create Account'}
              </button>
            ))}
          </div>

          {error && (
            <div className="bg-[#fef2f2] border border-[#fecaca] rounded-lg p-[10px_14px] text-[0.82rem] text-[#991b1b] mb-4">
              {error}
            </div>
          )}

          {tab === 'signin' ? (
            <div className="space-y-4">
              <div>
                <label className={labelClass}>Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                  className={inputClass}
                  placeholder="you@example.com"
                />
              </div>
              <div>
                <label className={labelClass}>Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                  className={inputClass}
                  placeholder="••••••••"
                />
              </div>
              <button
                onClick={handleLogin}
                disabled={!email || !password || loading}
                className="w-full bg-gradient-to-r from-[#0F766E] to-[#1D9E75] text-white rounded-lg py-[11px] text-[0.9rem] font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed mt-1 transition-opacity"
              >
                {loading ? 'Signing in…' : 'Sign In'}
              </button>

              {isSupabaseAvailable() && (
                <>
                  <div className="relative my-2">
                    <div className="absolute inset-0 flex items-center">
                      <div className="w-full border-t border-[#e5e7eb]" />
                    </div>
                    <div className="relative flex justify-center text-[0.72rem]">
                      <span className="bg-white px-3 text-[#9ca3af]">or continue with</span>
                    </div>
                  </div>
                  <button
                    onClick={handleGoogleSignIn}
                    className="w-full flex items-center justify-center gap-2.5 py-[10px] rounded-lg border border-[#d1d5db] bg-white text-[#374151] text-[0.85rem] font-medium cursor-pointer hover:bg-[#f9fafb] transition-colors"
                  >
                    <svg className="w-[18px] h-[18px] flex-shrink-0" viewBox="0 0 24 24">
                      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                    </svg>
                    Sign in with Google
                  </button>
                </>
              )}
            </div>
          ) : (
            <div className="space-y-3 max-h-[calc(100vh-280px)] sm:max-h-[500px] overflow-y-auto pr-1">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="sm:col-span-2">
                  <label className={labelClass}>Full Name</label>
                  <input
                    type="text"
                    value={regName}
                    onChange={(e) => setRegName(e.target.value)}
                    className={inputClass}
                    placeholder="Jane Doe"
                  />
                </div>
                <div>
                  <label className={labelClass}>Email</label>
                  <input
                    type="email"
                    value={regEmail}
                    onChange={(e) => setRegEmail(e.target.value)}
                    className={inputClass}
                    placeholder="you@example.com"
                  />
                </div>
                <div>
                  <label className={labelClass}>Password</label>
                  <input
                    type="password"
                    value={regPassword}
                    onChange={(e) => setRegPassword(e.target.value)}
                    className={inputClass}
                    placeholder="Min 8 characters"
                  />
                </div>
                <div>
                  <label className={labelClass}>
                    Referral Code <span className="text-[#9ca3af] normal-case font-normal">(optional)</span>
                  </label>
                  <input
                    type="text"
                    value={regReferredBy}
                    onChange={(e) => setRegReferredBy(e.target.value.toUpperCase())}
                    className={`${inputClass} tracking-wider`}
                    placeholder="e.g. AB3X7R2K"
                    maxLength={8}
                  />
                </div>
                <div className="flex items-center gap-2 bg-[#eff6ff] border border-[#bfdbfe] rounded-lg px-3 py-2 text-[0.78rem] text-[#1e40af]">
                  <i className="ti ti-school text-[14px] flex-shrink-0" />
                  Counsellor and school-admin accounts are provisioned by your institution. Public registration is for students only.
                </div>
              </div>

              <div>
                <label className={labelClass}>Date of Birth</label>
                <input
                  type="date"
                  value={regDob}
                  onChange={(e) => {
                    setRegDob(e.target.value)
                    const birth = new Date(e.target.value)
                    const age = new Date().getFullYear() - birth.getFullYear()
                    setIsMinor(age < 18)
                  }}
                  className={inputClass}
                />
              </div>
              {isMinor && (
                <>
                  <div className="flex items-start gap-2 bg-[#fef3c7] border border-[#fde68a] rounded-lg px-3 py-2 text-[0.78rem] text-[#92400e]">
                    <i className="ti ti-info-circle text-[14px] mt-px flex-shrink-0" />
                    A parent or guardian must provide consent for users under 18. A notification will be sent to their email.
                  </div>
                  <div>
                    <label className={labelClass}>
                      Parent/Guardian Email <span className="text-[#ef4444]">*</span>
                    </label>
                    <input
                      type="email"
                      value={regParentEmail}
                      onChange={(e) => setRegParentEmail(e.target.value)}
                      className={inputClass}
                      placeholder="parent@example.com"
                      required
                    />
                  </div>
                </>
              )}
              <button
                onClick={handleRegister}
                disabled={!regName || !regEmail || !regPassword || loading}
                className="w-full bg-gradient-to-r from-[#0F766E] to-[#1D9E75] text-white rounded-lg py-[11px] text-[0.9rem] font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed mt-1 transition-opacity"
              >
                {loading ? 'Creating account…' : 'Create Account'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

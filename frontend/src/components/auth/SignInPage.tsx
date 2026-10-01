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
  const { setAuth, setTermsAccepted } = useAuthStore()
  const setPage = useUiStore((s) => s.setPage)
  const [tab, setTab] = useState<'signin' | 'register'>('signin')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showLoginPassword, setShowLoginPassword] = useState(false)

  const [regName, setRegName] = useState('')
  const [regEmail, setRegEmail] = useState('')
  const [regPassword, setRegPassword] = useState('')
  const [regDob, setRegDob] = useState('')
  const [regParentEmail, setRegParentEmail] = useState('')
  const [regReferredBy, setRegReferredBy] = useState('')
  const [isMinor, setIsMinor] = useState(false)
  const [showRegPassword, setShowRegPassword] = useState(false)

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
      setTermsAccepted(Boolean(user.terms_accepted))
      const rt = user.role_type?.toLowerCase()
      if (rt === 'counsellor') setPage('counsellor-dashboard')
      else if (rt === 'school_admin') setPage('institution')
      else if (rt === 'admin') setPage('admin')
      else if (['company_admin', 'workplace_employee', 'workplace_provider'].includes(rt || '')) setPage('workplace')
      onSuccess()
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  const handleRegister = async () => {
    setError('')
    if (!regName.trim() || !regEmail.trim() || !regDob || regPassword.length < 8) {
      setError('Enter your name, email, date of birth, and a password of at least 8 characters.')
      return
    }
    if (isMinor && !regParentEmail.trim()) {
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
  const registrationPasswordScore = [
    regPassword.length >= 8,
    /[A-Z]/.test(regPassword),
    /[0-9]/.test(regPassword),
    /[^A-Za-z0-9]/.test(regPassword),
  ].filter(Boolean).length
  const calculateAge = (value: string) => {
    if (!value) return null
    const birth = new Date(`${value}T00:00:00`)
    const today = new Date()
    let age = today.getFullYear() - birth.getFullYear()
    const birthdayPassed = today.getMonth() > birth.getMonth() || (today.getMonth() === birth.getMonth() && today.getDate() >= birth.getDate())
    if (!birthdayPassed) age -= 1
    return age
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#eef5f4] flex items-center justify-center p-3 sm:p-5 lg:p-8">
      <div className="pointer-events-none absolute -left-24 -top-24 h-80 w-80 rounded-full bg-[#b8e6dc]/50 blur-3xl motion-safe:animate-pulse" />
      <div className="pointer-events-none absolute -bottom-32 -right-20 h-96 w-96 rounded-full bg-[#c8d9f3]/50 blur-3xl motion-safe:animate-pulse [animation-delay:1.5s]" />
      <div className="relative flex min-h-[640px] w-full max-w-[1240px] flex-col overflow-hidden rounded-[24px] border border-white/80 bg-white shadow-[0_24px_80px_rgba(15,118,110,0.14)] sm:flex-row lg:min-h-[700px]">

        {/* Left panel — collapses to a compact banner on mobile */}
        <div className="relative flex shrink-0 flex-col justify-between overflow-hidden bg-gradient-to-br from-[#061d1b] via-[#0a302c] to-[#0f554c] p-6 sm:w-[45%] sm:p-9 lg:w-[47%] lg:p-12">
          <div className="pointer-events-none absolute -right-20 top-20 h-64 w-64 rounded-full border border-[#5eead4]/20 motion-safe:animate-[spin_18s_linear_infinite]" />
          <div className="pointer-events-none absolute -right-8 top-32 h-40 w-40 rounded-full border border-[#5eead4]/20 motion-safe:animate-[spin_12s_linear_infinite_reverse]" />
          <div className="pointer-events-none absolute bottom-20 right-16 h-3 w-3 rounded-full bg-[#6ee7b7] shadow-[0_0_28px_8px_rgba(110,231,183,0.35)] motion-safe:animate-ping" />
          <div>
            <div className="relative z-10 mb-6 flex items-center gap-3 sm:mb-12">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#2dd4bf] to-[#1D9E75] text-[0.85rem] font-extrabold text-white shadow-lg shadow-[#2dd4bf]/20 sm:h-12 sm:w-12">
                MG
              </div>
              <span className="text-[1.1rem] font-bold tracking-tight text-white sm:text-[1.2rem]">MindGuard</span>
            </div>
            <div className="relative z-10 hidden sm:block">
            <p className="mb-3 text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[#5eead4]">A calmer place to begin</p>
            <h1 className="mb-4 max-w-[420px] text-[1.8rem] font-bold leading-[1.15] text-white lg:text-[2.35rem]">
              Consent-first clinical decision support
            </h1>
            <p className="max-w-[390px] text-[0.9rem] leading-relaxed text-[#a7c5c1]">
              A private, human-supported wellbeing space designed around consent, clarity, and the next useful step.
            </p>
            <div className="mt-10 flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.06] p-4 backdrop-blur-sm">
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-[#5eead4]/15 text-[#5eead4]"><i className="ti ti-heart-handshake text-[22px]" /></div>
              <div><p className="text-[0.78rem] font-semibold text-white">Human-in-the-loop support</p><p className="mt-1 text-[0.68rem] text-[#a7c5c1]">Your information is handled with care.</p></div>
            </div>
            </div>
          </div>
          <div className="relative z-10 mt-7 flex flex-wrap gap-2 sm:mt-0">
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
        <div className="flex flex-1 flex-col justify-center p-6 sm:w-[55%] sm:p-10 lg:w-[53%] lg:px-16 lg:py-12">
          {/* Tabs */}
          <div className="mb-8 flex border-b border-[#e8eef0]">
            {(['signin', 'register'] as const).map((t) => (
              <button
                key={t}
                onClick={() => { setTab(t); setError('') }}
                className={`px-4 pb-3 text-[0.88rem] font-semibold border-b-2 transition-colors cursor-pointer sm:px-5 ${
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
                <label className={labelClass} htmlFor="login-password">Password</label>
                <div className="relative">
                  <input
                    id="login-password"
                    type={showLoginPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                    className={`${inputClass} pr-[42px]`}
                    placeholder="••••••••"
                    autoComplete="current-password"
                  />
                  <button type="button" aria-label={showLoginPassword ? 'Hide password' : 'Show password'} onClick={() => setShowLoginPassword((value) => !value)} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-[#64748b] hover:bg-[#f1f5f9]"><i className={`ti ${showLoginPassword ? 'ti-eye-off' : 'ti-eye'} text-[16px]`} /></button>
                </div>
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
            <div className="space-y-5 max-h-[calc(100vh-250px)] sm:max-h-[620px] overflow-y-auto pr-1">
              <div>
                <p className="text-[0.68rem] font-bold uppercase tracking-[0.16em] text-[#0F766E]">Create your wellbeing space</p>
                <h2 className="mt-1 text-[1.35rem] font-bold leading-tight text-[#17212b]">A thoughtful start matters.</h2>
                <p className="mt-2 text-[0.8rem] leading-relaxed text-[#64748b]">Your details help us provide the right consent and support experience. You can update your profile later.</p>
              </div>

              <div className="rounded-xl border border-[#ccfbf1] bg-[#f0fdfa] p-3">
                <div className="flex items-center gap-2 text-[0.78rem] font-semibold text-[#115e59]"><i className="ti ti-shield-check text-[17px]" /> Your information stays under your control</div>
                <p className="mt-1 pl-[25px] text-[0.72rem] leading-relaxed text-[#0f766e]">We use your date of birth only to apply the correct adult or minor consent journey.</p>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <label className={labelClass} htmlFor="register-name">Full name</label>
                  <input
                    id="register-name"
                    type="text"
                    value={regName}
                    onChange={(e) => setRegName(e.target.value)}
                    className={inputClass}
                    placeholder="e.g. Jane Doe"
                    autoComplete="name"
                  />
                </div>
                <div>
                  <label className={labelClass} htmlFor="register-email">Email address</label>
                  <input
                    id="register-email"
                    type="email"
                    value={regEmail}
                    onChange={(e) => setRegEmail(e.target.value)}
                    className={inputClass}
                    placeholder="you@example.com"
                    autoComplete="email"
                  />
                </div>
                <div>
                  <label className={labelClass} htmlFor="register-password">Password</label>
                  <div className="relative">
                    <input id="register-password" type={showRegPassword ? 'text' : 'password'} value={regPassword} onChange={(e) => setRegPassword(e.target.value)} className={`${inputClass} pr-[42px]`} placeholder="At least 8 characters" autoComplete="new-password" />
                    <button type="button" aria-label={showRegPassword ? 'Hide password' : 'Show password'} onClick={() => setShowRegPassword((value) => !value)} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-[#64748b] hover:bg-[#f1f5f9]"><i className={`ti ${showRegPassword ? 'ti-eye-off' : 'ti-eye'} text-[16px]`} /></button>
                  </div>
                  {regPassword && <div className="mt-2"><div className="flex gap-1">{[0, 1, 2, 3].map((item) => <span key={item} className={`h-1 flex-1 rounded-full ${item < registrationPasswordScore ? registrationPasswordScore >= 3 ? 'bg-[#0f766e]' : 'bg-[#f59e0b]' : 'bg-[#e5e7eb]'}`} />)}</div><p className="mt-1 text-[0.68rem] text-[#64748b]">Use 8+ characters with a capital letter, number, and symbol.</p></div>}
                </div>
                <div>
                  <label className={labelClass} htmlFor="register-referral">Referral code <span className="text-[#9ca3af] normal-case font-normal">(optional)</span></label>
                  <input
                    id="register-referral"
                    type="text"
                    value={regReferredBy}
                    onChange={(e) => setRegReferredBy(e.target.value.toUpperCase())}
                    className={`${inputClass} tracking-wider`}
                    placeholder="e.g. AB3X7R2K"
                    maxLength={8}
                  />
                </div>
              </div>

              <div>
                <label className={labelClass} htmlFor="register-dob">Date of birth</label>
                <input
                  id="register-dob"
                  type="date"
                  value={regDob}
                  onChange={(e) => {
                    setRegDob(e.target.value)
                    const age = calculateAge(e.target.value)
                    setIsMinor(age !== null && age < 18)
                  }}
                  className={inputClass}
                  max={new Date().toISOString().slice(0, 10)}
                  autoComplete="bday"
                />
                <p className="mt-1 text-[0.7rem] text-[#64748b]">This determines whether parent or guardian consent is required.</p>
              </div>
              {isMinor && (
                <>
                  <div className="flex items-start gap-2 rounded-xl border border-[#fde68a] bg-[#fffbeb] px-3 py-3 text-[0.78rem] text-[#92400e]">
                    <i className="ti ti-info-circle text-[14px] mt-px flex-shrink-0" />
                    <span><b>Parent or guardian consent required.</b><br />We will email them a secure consent request. You can continue setting up your account, but protected wellbeing support stays locked until they respond.</span>
                  </div>
                  <div>
                    <label className={labelClass} htmlFor="register-parent-email">
                      Parent/Guardian Email <span className="text-[#ef4444]">*</span>
                    </label>
                    <input
                      id="register-parent-email"
                      type="email"
                      value={regParentEmail}
                      onChange={(e) => setRegParentEmail(e.target.value)}
                      className={inputClass}
                      placeholder="parent@example.com"
                      required
                      autoComplete="email"
                    />
                  </div>
                </>
              )}
              {!isMinor && regDob && <div className="flex items-start gap-2 rounded-xl border border-[#bfdbfe] bg-[#eff6ff] px-3 py-3 text-[0.76rem] text-[#1e40af]"><i className="ti ti-user-check text-[15px] mt-px" /><span>Your account will follow the adult self-service wellbeing experience. You remain in control of any connected accounts.</span></div>}
              <div className="flex items-start gap-2 rounded-lg bg-[#f8fafc] px-3 py-2 text-[0.72rem] text-[#64748b]"><i className="ti ti-school text-[14px] flex-shrink-0" />Counsellor and school-admin accounts are provisioned by an institution. Public registration is for personal student accounts.</div>
              <button
                onClick={handleRegister}
                disabled={!regName || !regEmail || !regPassword || !regDob || loading}
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

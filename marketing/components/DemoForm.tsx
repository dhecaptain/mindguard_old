'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

const ORG_TYPES = [
  { value: 'k12', label: 'K-12 school / district' },
  { value: 'university', label: 'University / college' },
  { value: 'company', label: 'Company / employer' },
  { value: 'clinic', label: 'Clinic / counselling practice' },
  { value: 'research', label: 'Research organisation' },
  { value: 'other', label: 'Other' },
]

const COUNT_RANGES = ['Under 500', '500–1,000', '1,001–5,000', '5,001–10,000', '10,000+']
const EMPLOYEE_RANGES = ['Under 50', '50–199', '200–499', '500–999', '1,000+']

const FREE_EMAIL_DOMAINS = new Set(['gmail.com', 'yahoo.com', 'ymail.com', 'hotmail.com', 'outlook.com', 'live.com', 'aol.com'])

const inputCls =
  'w-full bg-white border border-[rgba(23,33,29,0.12)] rounded-lg px-3 py-2.5 text-sm text-ink outline-none focus:border-forest focus:ring-2 focus:ring-forest/15 placeholder:text-ink-soft/50'

const labelCls = 'block text-xs font-bold text-ink uppercase tracking-wider mb-1.5'

type Status = 'idle' | 'submitting' | 'done' | 'error'

declare global {
  interface Window {
    grecaptcha?: {
      ready: (cb: () => void) => void
      execute: (siteKey: string, opts: { action: string }) => Promise<string>
    }
  }
}

const SITE_KEY = process.env.NEXT_PUBLIC_RECAPTCHA_SITE_KEY

export default function DemoForm() {
  const router = useRouter()
  const redirectedRef = useRef(false)
  const [form, setForm] = useState({
    full_name: '',
    work_email: '',
    organisation: '',
    organisation_type: 'k12',
    role_title: '',
    country: '',
    population_range: '',
    message: '',
    heard_about_us: '',
    website: '', // honeypot — humans never see or fill this
  })
  const [consentToContact, setConsentToContact] = useState(false)
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const [recaptchaToken, setRecaptchaToken] = useState('')

  useEffect(() => {
    if (!SITE_KEY || window.grecaptcha) return
    const s = document.createElement('script')
    s.src = `https://www.google.com/recaptcha/api.js?render=${SITE_KEY}`
    s.async = true
    s.defer = true
    s.onload = () => {
      window.grecaptcha?.ready(() => {
        window.grecaptcha?.execute(SITE_KEY, { action: 'demo_request' }).then(setRecaptchaToken).catch(() => {})
      })
    }
    document.head.appendChild(s)
  }, [])

  const set =
    (k: string) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [k]: e.target.value }))

  const valid =
    form.full_name.trim() &&
    form.work_email.trim() &&
    form.organisation.trim() &&
    form.role_title.trim() &&
    form.country.trim() &&
    form.population_range &&
    consentToContact

  const freeEmailDomain = (() => {
    const domain = form.work_email.split('@')[1]?.toLowerCase() ?? ''
    if (!domain) return false
    return FREE_EMAIL_DOMAINS.has(domain)
  })()
  const showFreeEmailWarning =
    (form.organisation_type === 'k12' || form.organisation_type === 'university' || form.organisation_type === 'company') && freeEmailDomain

  const handleSubmit = async () => {
    if (!valid || status === 'submitting') return

    // Honeypot filled ⇒ bot. Silently show success without submitting.
    if (form.website) {
      setStatus('done')
      return
    }

    let token = recaptchaToken
    if (SITE_KEY && !token) {
      try {
        token = await window.grecaptcha?.execute(SITE_KEY, { action: 'demo_request' }) ?? ''
      } catch {
        token = ''
      }
    }

    setStatus('submitting')
    setError(null)
    setWarning(null)
    try {
      const res = await fetch('/api/v1/demo-requests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          full_name: form.full_name.trim(),
          work_email: form.work_email.trim(),
          organisation: form.organisation.trim(),
          consent_to_contact: consentToContact,
          population_range: form.population_range,
          recaptcha_token: token,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail || 'Something went wrong. Please try again.')
        setStatus('error')
        return
      }
      setWarning(data.warning || null)
      setStatus('done')
      window.setTimeout(() => {
        if (!redirectedRef.current) {
          redirectedRef.current = true
          router.push('/thank-you')
        }
      }, 1400)
    } catch {
      setError('Network error — please try again.')
      setStatus('error')
    }
  }

  if (status === 'done') {
    return (
      <div className="mg-card p-8 text-center">
        <div className="w-14 h-14 rounded-full bg-forest-50 flex items-center justify-center mx-auto mb-4 text-2xl text-forest">
          ✓
        </div>
        <h2 className="text-xl font-bold text-ink mb-2">Request received</h2>
        <p className="text-sm text-ink-soft max-w-md mx-auto">
          Thanks, {form.full_name.trim()}! Our team will reach out within 2 business days.
        </p>
        {warning && (
          <p className="mt-4 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 max-w-md mx-auto">
            {warning}
          </p>
        )}
        <button
          onClick={() => router.push('/thank-you')}
          className="mt-6 px-6 py-3 mg-btn-primary text-sm"
        >
          Next steps
        </button>
      </div>
    )
  }

  return (
    <div className="mg-card p-6 sm:p-8 flex flex-col gap-4">
      {/* Honeypot (invisible to humans, irresistible to bots) */}
      <div className="absolute left-[-9999px] top-[-9999px]" aria-hidden="true">
        <label htmlFor="website">Leave this field blank</label>
        <input
          id="website"
          name="website"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={form.website}
          onChange={set('website')}
        />
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <label className={labelCls}>Full name *</label>
          <input className={inputCls} value={form.full_name} onChange={set('full_name')} placeholder="Jordan Blake" />
        </div>
        <div>
          <label className={labelCls}>Work email *</label>
          <input className={inputCls} type="email" value={form.work_email} onChange={set('work_email')} placeholder="you@organisation.org" />
          {showFreeEmailWarning && (
            <p className="mt-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              For organisation sign-ups we recommend a work email address so our team can
              verify your organisation. A personal address is fine if you do not have one.
            </p>
          )}
        </div>
      </div>

      <div>
        <label className={labelCls}>Organisation *</label>
        <input className={inputCls} value={form.organisation} onChange={set('organisation')} placeholder={form.organisation_type === 'company' ? 'Acme Ltd' : 'Organisation name'} />
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <label className={labelCls}>Role / title *</label>
          <input className={inputCls} value={form.role_title} onChange={set('role_title')} placeholder="Head of Pastoral Care" />
        </div>
        <div>
          <label className={labelCls} htmlFor="org-type">Organisation type</label>
          <select id="org-type" className={inputCls} value={form.organisation_type} onChange={set('organisation_type')}>
            {ORG_TYPES.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <label className={labelCls}>Country *</label>
          <input className={inputCls} value={form.country} onChange={set('country')} placeholder="UK" />
        </div>
        <div>
          <label className={labelCls} htmlFor="student-pop">{form.organisation_type === 'company' ? 'Employee population *' : ['k12', 'university'].includes(form.organisation_type) ? 'Student population *' : 'Population served *'}</label>
          <select id="student-pop" className={inputCls} value={form.population_range} onChange={set('population_range')}>
            <option value="">Select a range...</option>
            {(form.organisation_type === 'company' ? EMPLOYEE_RANGES : COUNT_RANGES).map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className={labelCls}>Message</label>
        <textarea
          className={`${inputCls} resize-none`}
          rows={4}
          value={form.message}
          onChange={set('message')}
          placeholder="Tell us a little about what you're looking for..."
        />
      </div>

      <div>
        <label className={labelCls} htmlFor="heard-about">How did you hear about us?</label>
        <select id="heard-about" className={inputCls} value={form.heard_about_us} onChange={set('heard_about_us')}>
          <option value="">Select an option...</option>
          {['Conference', 'Word of mouth', 'Online search', 'Social media', 'Newsletter', 'Other'].map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      </div>

      <label className="flex items-start gap-2 text-sm text-ink-soft cursor-pointer">
        <input
          type="checkbox"
          checked={consentToContact}
          onChange={(e) => setConsentToContact(e.target.checked)}
          className="mt-0.5 accent-forest"
        />
        <span>I agree to be contacted by MindGuard about my request. *</span>
      </label>

      {warning && (
        <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
          {warning}
        </p>
      )}
      {error && (
        <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          {error}
        </p>
      )}

      <button
        onClick={handleSubmit}
        disabled={!valid || status === 'submitting'}
        className="self-start px-6 py-3 mg-btn-primary text-sm disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {status === 'submitting' ? 'Submitting...' : 'Request demo'}
      </button>
    </div>
  )
}

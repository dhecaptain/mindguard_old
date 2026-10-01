import { useState } from 'react'
import { submitDemoRequest } from '../api/demo'

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

const inputCls =
  'w-full bg-[#fafbfc] border border-[#e5e7eb] rounded-[8px] px-[12px] py-[9px] text-[0.85rem] text-[#1f2937] outline-none focus:border-[#0F766E] focus:ring-2 focus:ring-[#0F766E]/20'

const labelCls = 'block text-[0.72rem] font-bold text-[#374151] uppercase tracking-[0.06em] mb-[6px]'
const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Unable to submit the demo request.'

export default function DemoRequestPage() {
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
  })
  const [consentToContact, setConsentToContact] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  const valid = form.full_name.trim() && form.work_email.trim() && form.organisation.trim() && (form.organisation_type !== 'company' || form.population_range) && consentToContact

  const handleSubmit = async () => {
    if (!valid || submitting) return
    setSubmitting(true)
    setError(null)
    setWarning(null)
    try {
      const res = await submitDemoRequest({
        ...form,
        full_name: form.full_name.trim(),
        work_email: form.work_email.trim(),
        organisation: form.organisation.trim(),
        consent_to_contact: consentToContact,
      })
      setWarning(res.warning || null)
      setDone(`Thanks, ${form.full_name.trim()}! We've received your request and will be in touch within 2 business days.`)
    } catch (e: unknown) {
      setError(errorMessage(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#f7f9fb] flex flex-col">
      {/* Header */}
      <header className="w-full bg-white border-b border-[#eef2f6]">
        <div className="max-w-[520px] mx-auto px-[20px] py-[18px] flex items-center justify-between">
          <div className="flex items-center gap-[8px]">
            <span className="w-[30px] h-[30px] rounded-lg bg-[#0F766E] flex items-center justify-center text-white font-bold text-[0.85rem]">M</span>
            <span className="text-[1.05rem] font-bold text-[#1f2937]">MindGuard</span>
          </div>
          <a href="/" className="text-[0.8rem] text-[#0F766E] font-semibold hover:text-[#115E59]">Back</a>
        </div>
      </header>

      <main className="flex-1 w-full max-w-[520px] mx-auto px-[20px] py-[32px]">
        <div className="mb-[24px]">
          <h1 className="text-[1.4rem] font-bold text-[#1f2937]">Request a demo</h1>
          <p className="text-[0.85rem] text-[#6b7280] mt-[6px]">
            Explore how MindGuard can support wellbeing in your organisation, with privacy and consent built in from day one.
          </p>
        </div>

        {done ? (
          <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[24px] text-center">
            <div className="w-[52px] h-[52px] rounded-full bg-[#d1fae5] flex items-center justify-center mx-auto mb-[14px]">
              <i className="ti ti-circle-check text-[26px] text-[#065f46]" />
            </div>
            <h2 className="text-[1rem] font-bold text-[#1f2937] mb-[6px]">Request received</h2>
            <p className="text-[0.85rem] text-[#6b7280]">{done}</p>
            {warning && (
              <div className="mt-[14px] rounded-[8px] bg-[#fef3c7] border border-[#fde68a] px-[12px] py-[8px] text-[0.78rem] text-[#92400e] text-left">
                <i className="ti ti-alert-triangle text-[14px] mr-[6px]" />
                {warning}
              </div>
            )}
            <a
              href="/"
              className="inline-block mt-[18px] px-[18px] py-[9px] bg-[#0F766E] text-white rounded-[8px] text-[0.82rem] font-semibold hover:bg-[#115E59]"
            >
              Back to home
            </a>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[24px] flex flex-col gap-[14px]">
            <div className="grid sm:grid-cols-2 gap-[14px]">
              <div>
                <label className={labelCls}>Full name *</label>
                <input className={inputCls} value={form.full_name} onChange={set('full_name')} placeholder="Jordan Blake" />
              </div>
              <div>
                <label className={labelCls}>Work email *</label>
                <input className={inputCls} type="email" value={form.work_email} onChange={set('work_email')} placeholder="you@organisation.org" />
              </div>
            </div>

            <div className="grid sm:grid-cols-2 gap-[14px]">
              <div>
                <label className={labelCls}>Organisation *</label>
                <input className={inputCls} value={form.organisation} onChange={set('organisation')} placeholder={form.organisation_type === 'company' ? 'Acme Ltd' : 'Organisation name'} />
              </div>
              <div>
                <label className={labelCls}>Organisation type</label>
                <select className={inputCls} value={form.organisation_type} onChange={set('organisation_type')}>
                  {ORG_TYPES.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="grid sm:grid-cols-2 gap-[14px]">
              <div>
                <label className={labelCls}>Role / title</label>
                <input className={inputCls} value={form.role_title} onChange={set('role_title')} placeholder="Head of Pastoral Care" />
              </div>
              <div>
                <label className={labelCls}>Country</label>
                <input className={inputCls} value={form.country} onChange={set('country')} placeholder="UK" />
              </div>
            </div>

            <div>
              <label className={labelCls}>{form.organisation_type === 'company' ? 'Employee population *' : ['k12', 'university'].includes(form.organisation_type) ? 'Student population' : 'Population served'}</label>
              <select className={inputCls} value={form.population_range} onChange={set('population_range')}>
                <option value="">Select a range...</option>
                {(form.organisation_type === 'company' ? EMPLOYEE_RANGES : COUNT_RANGES).map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>

            <div>
              <label className={labelCls}>How did you hear about us?</label>
              <select className={inputCls} value={form.heard_about_us} onChange={set('heard_about_us')}>
                <option value="">Select an option...</option>
                {['Conference', 'Word of mouth', 'Online search', 'Social media', 'Newsletter', 'Other'].map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
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

            <label className="flex items-start gap-[10px] text-[0.8rem] text-[#4b5563] cursor-pointer">
              <input
                type="checkbox"
                checked={consentToContact}
                onChange={(e) => setConsentToContact(e.target.checked)}
                className="mt-[2px] accent-[#0F766E]"
              />
              <span>
                I consent to MindGuard contacting me at this email address about the demo. * (Required)
              </span>
            </label>

            {warning && (
              <div className="rounded-[8px] bg-[#fef3c7] border border-[#fde68a] px-[12px] py-[8px] text-[0.78rem] text-[#92400e]">
                <i className="ti ti-alert-triangle text-[14px] mr-[6px]" />
                {warning}
              </div>
            )}
            {error && (
              <div className="rounded-[8px] bg-[#fee2e2] border border-[#fca5a5] px-[12px] py-[8px] text-[0.78rem] text-[#991b1b]">
                <i className="ti ti-alert-circle text-[14px] mr-[6px]" />
                {error}
              </div>
            )}

            <button
              onClick={handleSubmit}
              disabled={!valid || submitting}
              className="self-start px-[20px] py-[10px] bg-[#0F766E] text-white rounded-[8px] text-[0.85rem] font-semibold cursor-pointer hover:bg-[#115E59] transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-[6px]"
            >
              {submitting ? (
                <div className="w-[14px] h-[14px] border-2 border-white/40 border-t-white rounded-full animate-spin" />
              ) : (
                <i className="ti ti-send text-[15px]" />
              )}
              {submitting ? 'Submitting...' : 'Request demo'}
            </button>
          </div>
        )}
      </main>

      <footer className="text-center py-[18px] text-[0.72rem] text-[#9ca3af]">
        MindGuard · Wellbeing, with consent.
      </footer>
    </div>
  )
}

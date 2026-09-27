import { useEffect, useState } from 'react'
import { getInstitutionPolicy, updateInstitutionPolicy, type InstitutionPolicy } from '../api/admin'

const fieldClass = 'mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:border-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-100'

export default function InstitutionPolicyPage() {
  const [policy, setPolicy] = useState<InstitutionPolicy | null>(null)
  const [reminderDaysInput, setReminderDaysInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const load = async () => {
    try {
      const loaded = await getInstitutionPolicy()
      setPolicy(loaded)
      setReminderDaysInput(Array.isArray(loaded.consent_reminder_days) ? loaded.consent_reminder_days.join(', ') : '')
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load institution policy.')
    }
  }

  useEffect(() => { void load() }, [])

  const setNumber = (key: keyof InstitutionPolicy, value: string) => {
    setPolicy((current) => current ? { ...current, [key]: value === '' ? undefined : Number(value) } : current)
  }

  const save = async () => {
    if (!policy) return
    const reminderTokens = reminderDaysInput.trim() ? reminderDaysInput.split(',').map((part) => part.trim()) : []
    const reminders = reminderTokens.map(Number)
    if (reminderTokens.some((token) => !/^\d+$/.test(token) || Number(token) < 1 || Number(token) > 365)) {
      setError('Enter reminder days as comma-separated whole numbers from 1 to 365, or leave the field empty.')
      setMessage('')
      return
    }
    if (new Set(reminders).size !== reminders.length) {
      setError('Each consent reminder day can only be listed once.')
      setMessage('')
      return
    }
    setBusy(true); setError(''); setMessage('')
    try {
      const updated = await updateInstitutionPolicy({
        retention_days: policy.retention_days,
        minor_age_threshold: policy.minor_age_threshold,
        consent_expiry_days: policy.consent_expiry_days,
        consent_reminder_days: reminders,
        alert_threshold: policy.alert_threshold,
        confidence_floor: policy.confidence_floor,
      })
      setPolicy(updated)
      setReminderDaysInput(Array.isArray(updated.consent_reminder_days) ? updated.consent_reminder_days.join(', ') : '')
      setMessage('Institution policy saved. The change has been recorded in the audit log.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save institution policy.')
    } finally { setBusy(false) }
  }

  if (!policy && !error) return <div className="p-8 text-slate-500">Loading institution policy…</div>
  if (!policy) return <div className="mx-auto max-w-3xl p-6 md:p-9"><div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div><button onClick={() => void load()} className="mt-3 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold">Try again</button></div>

  return <main className="mx-auto max-w-4xl p-6 md:p-9">
    <header className="mb-6">
      <p className="text-xs font-bold uppercase tracking-widest text-teal-700">Institution operations</p>
      <h1 className="mt-1 text-2xl font-bold text-slate-800">Institution policy</h1>
      <p className="mt-1 text-sm text-slate-600">Review and update consent, retention, and decision-support settings for <strong>{policy.name}</strong>. Changes are institution-scoped and audited.</p>
    </header>
    {(error || message) && <div role={error ? 'alert' : 'status'} className={`mb-5 rounded-lg border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}>{error || message}</div>}
    <div className="space-y-5">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="font-bold text-slate-800">Consent and safeguarding</h2>
        <p className="mt-1 text-sm text-slate-500">Consent remains required before protected counsellor access or analysis. These settings do not override consent.</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="text-sm font-medium text-slate-700">Age of majority threshold
            <input className={fieldClass} type="number" min="13" max="21" value={policy.minor_age_threshold ?? 18} onChange={(e) => setNumber('minor_age_threshold', e.target.value)} />
            <span className="mt-1 block text-xs font-normal text-slate-500">Users below this age require guardian consent. Confirm this matches your local safeguarding requirements.</span>
          </label>
          <label className="text-sm font-medium text-slate-700">Consent link expiry (days)
            <input className={fieldClass} type="number" min="1" max="365" value={policy.consent_expiry_days ?? 30} onChange={(e) => setNumber('consent_expiry_days', e.target.value)} />
          </label>
          <label className="text-sm font-medium text-slate-700 sm:col-span-2">Reminder days after request
            <input className={fieldClass} value={reminderDaysInput} onChange={(e) => setReminderDaysInput(e.target.value)} placeholder="7, 14" />
            <span className="mt-1 block text-xs font-normal text-slate-500">Comma-separated positive days (for example 7, 14). Reminders stop when the request reaches a terminal state.</span>
          </label>
        </div>
      </section>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="font-bold text-slate-800">Data and decision-support controls</h2>
        <p className="mt-1 text-sm text-slate-500">These controls configure retention and system alerting; they are not clinical diagnoses or substitutes for counsellor judgement.</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="text-sm font-medium text-slate-700">Retention period (days)
            <input className={fieldClass} type="number" min="1" max="3650" value={policy.retention_days ?? 30} onChange={(e) => setNumber('retention_days', e.target.value)} />
          </label>
          <label className="text-sm font-medium text-slate-700">Alert threshold (0–1)
            <input className={fieldClass} type="number" min="0" max="1" step="0.01" value={policy.alert_threshold ?? 0.65} onChange={(e) => setNumber('alert_threshold', e.target.value)} />
          </label>
          <label className="text-sm font-medium text-slate-700">Confidence floor (0–1)
            <input className={fieldClass} type="number" min="0" max="1" step="0.01" value={policy.confidence_floor ?? 0.7} onChange={(e) => setNumber('confidence_floor', e.target.value)} />
          </label>
        </div>
      </section>
      <div className="flex justify-end"><button onClick={() => void save()} disabled={busy} className="rounded-lg bg-teal-800 px-5 py-2.5 text-sm font-semibold text-white hover:bg-teal-900 disabled:cursor-not-allowed disabled:opacity-50">{busy ? 'Saving…' : 'Save policy'}</button></div>
    </div>
  </main>
}

import { useState } from 'react'
import api from '../api/client'
import { useAuthStore } from '../store/authStore'

export default function StaffProfilePage() {
  const user = useAuthStore((s) => s.user)
  const setAuth = useAuthStore((s) => s.setAuth)
  const [form, setForm] = useState({ phone: '', country: '', address: '', professional_title: '', qualification: '', emergency_contact: '' })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }))
  const submit = async () => {
    setSaving(true); setError('')
    try {
      const { data } = await api.patch('/institution/staff/profile', form)
      setAuth({ ...(user as NonNullable<typeof user>), profile_completed: data.profile.profile_completed })
      window.location.reload()
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to save profile') }
    finally { setSaving(false) }
  }
  return <div className="min-h-screen bg-[#f7f9fb] flex items-center justify-center p-5"><div className="w-full max-w-[620px] rounded-2xl border border-slate-200 bg-white p-7 shadow-sm"><p className="text-xs font-bold uppercase tracking-widest text-[#0f766e]">Staff setup</p><h1 className="mt-2 text-2xl font-bold text-slate-800">Complete your professional profile</h1><p className="mt-2 text-sm text-slate-500">This information helps your institution manage access and contact you safely.</p><div className="mt-5 grid gap-3 sm:grid-cols-2">{(['phone', 'country', 'address', 'professional_title', 'qualification', 'emergency_contact'] as const).map((key) => <div key={key} className={key === 'address' ? 'sm:col-span-2' : ''}><label className="mb-1 block text-xs font-bold uppercase text-slate-600">{key.replaceAll('_', ' ')}{key !== 'emergency_contact' && ' *'}</label><input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" value={form[key]} onChange={(e) => update(key, e.target.value)} /></div>)}</div>{error && <div className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}<button onClick={submit} disabled={saving || !form.phone || !form.country || !form.address || !form.professional_title || !form.qualification} className="mt-5 w-full rounded-lg bg-[#0f766e] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40">{saving ? 'Saving…' : 'Continue to institution workspace'}</button></div></div>
}

import { useEffect, useState } from 'react'
import api from '../api/client'
import { useAuthStore } from '../store/authStore'

const emptyProfile = { phone: '', country: '', address: '', professional_title: '', qualification: '', emergency_contact: '' }

export default function StaffProfilePage() {
  const user = useAuthStore((s) => s.user)
  const setAuth = useAuthStore((s) => s.setAuth)
  const [form, setForm] = useState(emptyProfile)
  const [passwords, setPasswords] = useState({ current_password: '', new_password: '', confirm: '' })
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const profileComplete = Boolean(user?.profile_completed)
  const isCounsellor = user?.role_type === 'counsellor'
  const profileFields = (isCounsellor
    ? ['phone', 'country', 'address', 'professional_title', 'qualification', 'emergency_contact']
    : ['phone', 'country', 'address', 'emergency_contact']) as Array<keyof typeof emptyProfile>

  useEffect(() => {
    api.get('/institution/staff/profile')
      .then(({ data }) => setForm({ ...emptyProfile, ...Object.fromEntries(Object.keys(emptyProfile).map((key) => [key, data[key] || ''])) }))
      .catch(() => setError('Unable to load your profile. Please refresh and try again.'))
      .finally(() => setLoading(false))
  }, [])

  const update = (key: keyof typeof emptyProfile, value: string) => setForm((current) => ({ ...current, [key]: value }))
  const saveProfile = async () => {
    setSaving(true); setError(''); setMessage('')
    try {
      const { data } = await api.patch('/institution/staff/profile', form)
      if (user) setAuth({ ...user, profile_completed: data.profile.profile_completed })
      setMessage(profileComplete ? 'Profile updated.' : 'Profile complete. Opening your workspace…')
      if (!profileComplete) window.setTimeout(() => window.location.reload(), 600)
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to save profile.') }
    finally { setSaving(false) }
  }
  const changePassword = async () => {
    if (passwords.new_password.length < 8 || passwords.new_password !== passwords.confirm) {
      setError('New passwords must match and be at least 8 characters.'); return
    }
    setSaving(true); setError(''); setMessage('')
    try {
      await api.post('/auth/change-password', { current_password: passwords.current_password, new_password: passwords.new_password })
      setPasswords({ current_password: '', new_password: '', confirm: '' })
      setMessage('Password updated successfully.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to change password.') }
    finally { setSaving(false) }
  }

  if (loading) return <div className="p-8 text-slate-500">Loading your profile…</div>
  return <div className="mx-auto w-full max-w-[760px] p-6 md:p-9"><div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
    <p className="text-xs font-bold uppercase tracking-widest text-[#0f766e]">Account profile</p>
    <h1 className="mt-2 text-2xl font-bold text-slate-800">{profileComplete ? 'Your professional profile' : 'Complete your professional profile'}</h1>
    <p className="mt-2 text-sm text-slate-500">{profileComplete ? 'Keep your approved contact and professional details current.' : 'Before entering the workspace, provide the required contact and professional details for your institution.'}</p>
    <div className="mt-5 grid gap-3 sm:grid-cols-2">{profileFields.map((key) => <div key={key} className={key === 'address' ? 'sm:col-span-2' : ''}><label className="mb-1 block text-xs font-bold uppercase text-slate-600">{key.replaceAll('_', ' ')}{key !== 'emergency_contact' && ' *'}</label><input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" value={form[key]} onChange={(e) => update(key, e.target.value)} /></div>)}</div>
    {(error || message) && <div className={`mt-4 rounded-lg px-3 py-2 text-sm ${error ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700'}`}>{error || message}</div>}
    <button onClick={saveProfile} disabled={saving || !form.phone || !form.country || !form.address || (isCounsellor && (!form.professional_title || !form.qualification))} className="mt-5 w-full rounded-lg bg-[#0f766e] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40">{saving ? 'Saving…' : profileComplete ? 'Save profile' : 'Save and continue'}</button>
    {profileComplete && <section className="mt-8 border-t border-slate-100 pt-6"><h2 className="font-bold text-slate-800">Change password</h2><p className="mt-1 text-sm text-slate-500">Use this only after your account is active.</p><div className="mt-3 grid gap-3 sm:grid-cols-3">{(['current_password', 'new_password', 'confirm'] as const).map((key) => <input key={key} type="password" placeholder={key.replaceAll('_', ' ')} value={passwords[key]} onChange={(e) => setPasswords((current) => ({ ...current, [key]: e.target.value }))} className="rounded-lg border border-slate-200 px-3 py-2 text-sm" />)}</div><button disabled={saving} onClick={changePassword} className="mt-3 rounded-lg border border-[#0f766e] px-4 py-2 text-sm font-semibold text-[#0f766e] disabled:opacity-40">Update password</button></section>}
  </div></div>
}

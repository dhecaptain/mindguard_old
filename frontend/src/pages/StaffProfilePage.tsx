import { useEffect, useState } from 'react'
import api from '../api/client'
import { useAuthStore } from '../store/authStore'

export default function StaffProfilePage() {
  const user = useAuthStore((s) => s.user)
  const setAuth = useAuthStore((s) => s.setAuth)
  const [form, setForm] = useState({ phone: '', country: '', address: '', professional_title: '', qualification: '', emergency_contact: '' })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [passwords, setPasswords] = useState({ current_password: '', new_password: '', confirm: '' })
  const [passwordMessage, setPasswordMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }))
  useEffect(() => {
    api.get('/institution/staff/profile').then(({ data }) => {
      setForm({ phone: data.phone || '', country: data.country || '', address: data.address || '', professional_title: data.professional_title || '', qualification: data.qualification || '', emergency_contact: data.emergency_contact || '' })
    }).catch(() => {}).finally(() => setLoading(false))
  }, [])
  const submit = async () => {
    setSaving(true); setError('')
    try {
      const { data } = await api.patch('/institution/staff/profile', form)
      setAuth({ ...(user as NonNullable<typeof user>), profile_completed: data.profile.profile_completed })
      window.location.reload()
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to save profile') }
    finally { setSaving(false) }
  }
  if (loading) return <div className="p-8 text-slate-500">Loading your profile…</div>
  return <div className="mx-auto w-full max-w-[760px] p-6 md:p-9"><div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm"><p className="text-xs font-bold uppercase tracking-widest text-[#0f766e]">Account profile</p><h1 className="mt-2 text-2xl font-bold text-slate-800">{user?.profile_completed ? 'Your professional profile' : 'Complete your professional profile'}</h1><p className="mt-2 text-sm text-slate-500">Your details are securely stored and visible to authorised institution administrators.</p><div className="mt-5 grid gap-3 sm:grid-cols-2">{(['phone', 'country', 'address', 'professional_title', 'qualification', 'emergency_contact'] as const).map((key) => <div key={key} className={key === 'address' ? 'sm:col-span-2' : ''}><label className="mb-1 block text-xs font-bold uppercase text-slate-600">{key.replaceAll('_', ' ')}{key !== 'emergency_contact' && ' *'}</label><input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" value={form[key]} onChange={(e) => update(key, e.target.value)} /></div>)}</div>{error && <div className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}<button onClick={submit} disabled={saving || !form.phone || !form.country || !form.address || !form.professional_title || !form.qualification} className="mt-5 w-full rounded-lg bg-[#0f766e] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40">{saving ? 'Saving…' : 'Save profile'}</button><div className="mt-8 border-t border-slate-100 pt-6"><h2 className="font-bold text-slate-800">Change password</h2><div className="mt-3 grid gap-3 sm:grid-cols-3">{(['current_password', 'new_password', 'confirm'] as const).map((key) => <input key={key} type="password" placeholder={key.replaceAll('_', ' ')} value={passwords[key]} onChange={(e) => setPasswords((p) => ({ ...p, [key]: e.target.value }))} className="rounded-lg border border-slate-200 px-3 py-2 text-sm" />)}</div>{passwordMessage && <p className="mt-3 text-sm text-emerald-700">{passwordMessage}</p>}<button onClick={async () => { setPasswordMessage(''); if (passwords.new_password.length < 8 || passwords.new_password !== passwords.confirm) { setError('New passwords must match and be at least 8 characters.'); return } try { await api.post('/auth/change-password', { current_password: passwords.current_password, new_password: passwords.new_password }); setPasswords({ current_password: '', new_password: '', confirm: '' }); setPasswordMessage('Password updated successfully.'); setError('') } catch (err) { setError(err instanceof Error ? err.message : 'Unable to change password') } }} className="mt-3 rounded-lg border border-[#0f766e] px-4 py-2 text-sm font-semibold text-[#0f766e]">Update password</button></div></div></div>
}

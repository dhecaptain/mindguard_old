import { useCallback, useEffect, useMemo, useState } from 'react'
import api from '../../api/client'
import { useAuthStore } from '../../store'
import { WorkplaceStatus } from './WorkplaceStatus'

type Appointment = {
  id: string
  case_id: string
  starts_at: string
  mode: string
  location_or_link?: string | null
  status: string
  employee_name?: string
  provider_name?: string
}

export default function WorkplaceAppointmentsPage() {
  const role = useAuthStore(state => state.user?.role_type)
  const isProvider = role === 'workplace_provider'
  const [items, setItems] = useState<Appointment[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [now] = useState(() => Date.now())
  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const path = isProvider ? '/v1/workplace/provider/appointments' : '/v1/workplace/appointments'
      setItems((await api.get(path)).data)
    } catch {
      setError('Appointments could not be loaded. Check your connection and retry.')
    } finally {
      setLoading(false)
    }
  }, [isProvider])
  useEffect(() => { void load() }, [load]) // eslint-disable-line react-hooks/set-state-in-effect
  const upcoming = useMemo(() => items.filter(item => item.status === 'scheduled' && new Date(item.starts_at).getTime() >= now), [items, now])
  const history = useMemo(() => items.filter(item => !upcoming.includes(item)), [items, upcoming])
  const update = async (id: string, status: 'completed' | 'cancelled') => {
    setBusyId(id)
    setNotice('')
    try {
      await api.post(`/v1/workplace/provider/appointments/${id}/status`, { status })
      setNotice(status === 'completed' ? 'Appointment marked complete.' : 'Appointment cancelled.')
      await load()
    } catch {
      setNotice('Appointment status could not be updated. Please retry.')
    } finally {
      setBusyId('')
    }
  }
  return <main className="mx-auto w-full max-w-5xl space-y-6 text-slate-900">
    <header><p className="text-xs font-bold uppercase tracking-widest text-emerald-700">{isProvider ? 'Provider workspace' : 'Your private wellbeing space'}</p><h1 className="mt-1 text-3xl font-bold">Appointments</h1><p className="mt-2 text-sm text-slate-600">{isProvider ? 'Appointments are connected only to support cases employees explicitly shared with you.' : 'Your appointment details are private to you and your independent provider.'}</p></header>
    {error&&<div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"><span>{error}</span><button className="font-semibold underline focus-visible:outline focus-visible:outline-2" onClick={()=>void load()}>Retry</button></div>}
    {loading?<div role="status" className="animate-pulse rounded-2xl border bg-white p-6 text-sm text-slate-500">Loading appointments…</div>:<>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-center justify-between gap-3"><h2 className="text-lg font-semibold">Upcoming</h2><span className="text-sm text-slate-500">{upcoming.length}</span></div>{upcoming.length===0?<p className="mt-3 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">No upcoming appointments. {isProvider?'An appointment will appear here after you schedule one in a shared case.':'Your provider will share appointment details here when one is scheduled.'}</p>:<ul className="mt-3 divide-y">{upcoming.map(item=><li key={item.id} className="flex flex-col justify-between gap-3 py-4 sm:flex-row sm:items-center"><div><p className="font-semibold">{isProvider?item.employee_name:'Support appointment'}{!isProvider&&item.provider_name?` · ${item.provider_name}`:''}</p><p className="mt-1 text-sm text-slate-600">{new Date(item.starts_at).toLocaleString()} · {item.mode==='online'?'Online':'In person'}</p>{item.location_or_link&&<p className="mt-1 break-all text-sm text-emerald-800">{item.location_or_link}</p>}</div><div className="flex items-center gap-2"><WorkplaceStatus value={item.status}/>{isProvider&&<><button disabled={busyId===item.id} className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50" onClick={()=>void update(item.id,'completed')}>Mark complete</button><button disabled={busyId===item.id} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold hover:bg-slate-50 disabled:opacity-50" onClick={()=>void update(item.id,'cancelled')}>Cancel</button></>}</div></li>)}</ul>}</section>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="text-lg font-semibold">Past appointments</h2>{history.length===0?<p className="mt-3 text-sm text-slate-600">Past or cancelled appointments will appear here.</p>:<ul className="mt-3 divide-y">{history.map(item=><li key={item.id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div><p className="font-medium">{isProvider?item.employee_name:'Support appointment'}{!isProvider&&item.provider_name?` · ${item.provider_name}`:''}</p><p className="text-sm text-slate-600">{new Date(item.starts_at).toLocaleString()}</p></div><WorkplaceStatus value={item.status}/></li>)}</ul>}</section>
    </>}
    {notice&&<p role="status" className="rounded-xl bg-slate-100 p-3 text-sm">{notice}</p>}
  </main>
}

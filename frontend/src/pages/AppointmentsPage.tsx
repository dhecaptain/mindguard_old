import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { useAuthStore } from '../store'
import { createAppointment, getAppointments, updateAppointmentStatus, type Appointment, type AppointmentStatus } from '../api/appointments'
import { getStudents, type StudentDTO } from '../api/counsellor'

const statusStyles: Record<AppointmentStatus, string> = {
  REQUESTED: 'bg-[#fef3c7] text-[#92400e]',
  CONFIRMED: 'bg-[#d1fae5] text-[#065f46]',
  DECLINED: 'bg-[#fee2e2] text-[#991b1b]',
  CANCELLED: 'bg-[#f1f5f9] text-[#475569]',
  COMPLETED: 'bg-[#dbeafe] text-[#1e40af]',
  NO_SHOW: 'bg-[#fce7f3] text-[#9d174d]',
}

function dateLabel(value: string) {
  return new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export default function AppointmentsPage() {
  const user = useAuthStore((s) => s.user)
  const isStaff = user?.role_type === 'counsellor' || user?.role_type === 'school_admin' || user?.role_type === 'admin'
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [students, setStudents] = useState<StudentDTO[]>([])
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ student_id: '', title: 'Wellbeing check-in', date: '', start: '', end: '', mode: 'video', location: '', notes: '' })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [items, roster] = await Promise.all([getAppointments(), isStaff ? getStudents() : Promise.resolve([])])
      setAppointments(items)
      setStudents(roster)
      setError('')
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to load appointments') }
    finally { setLoading(false) }
  }, [isStaff])

  useEffect(() => {
    const refresh = async () => { await load() }
    void refresh()
  }, [load])

  const upcoming = useMemo(() => appointments.filter((a) => ['REQUESTED', 'CONFIRMED'].includes(a.status)), [appointments])
  const past = useMemo(() => appointments.filter((a) => !['REQUESTED', 'CONFIRMED'].includes(a.status)), [appointments])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!form.student_id || !form.date || !form.start || !form.end) return
    setSaving(true); setError('')
    try {
      const start = new Date(`${form.date}T${form.start}`)
      const end = new Date(`${form.date}T${form.end}`)
      await createAppointment({
        student_id: form.student_id, title: form.title.trim(), start_at: start.toISOString(), end_at: end.toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, mode: form.mode, location: form.location.trim(), notes: form.notes.trim(),
      })
      setForm({ student_id: '', title: 'Wellbeing check-in', date: '', start: '', end: '', mode: 'video', location: '', notes: '' })
      setShowForm(false); await load()
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to schedule appointment') }
    finally { setSaving(false) }
  }

  const transition = async (appointment: Appointment, status: AppointmentStatus) => {
    try { await updateAppointmentStatus(appointment.id, status); await load() }
    catch (e) { setError(e instanceof Error ? e.message : 'Unable to update appointment') }
  }

  return (
    <div className="max-w-[1100px] mx-auto px-[24px] py-[28px]">
      <div className="flex flex-wrap items-start justify-between gap-[16px] mb-[24px]">
        <div>
          <div className="text-[0.72rem] uppercase tracking-[0.12em] text-[#0f766e] font-bold">Care coordination</div>
          <h1 className="text-[1.6rem] font-bold text-[#17212b] mt-[4px]">Appointments</h1>
          <p className="text-[0.86rem] text-[#64748b] mt-[5px]">Keep wellbeing check-ins clear, agreed, and easy to follow up.</p>
        </div>
        {isStaff && <button onClick={() => setShowForm((v) => !v)} className="px-[14px] py-[10px] rounded-[9px] bg-[#0f766e] text-white text-[0.82rem] font-semibold hover:bg-[#115e59]">{showForm ? 'Close' : 'Schedule appointment'}</button>}
      </div>

      {error && <div role="alert" className="mb-[18px] rounded-[9px] bg-[#fef2f2] border border-[#fecaca] text-[#991b1b] px-[14px] py-[11px] text-[0.82rem]">{error}</div>}

      {showForm && <form onSubmit={submit} className="mb-[24px] rounded-[14px] border border-[#dbe5e7] bg-white p-[18px] shadow-sm">
        <h2 className="font-bold text-[#1f2937] mb-[14px]">Propose a wellbeing appointment</h2>
        <div className="grid md:grid-cols-2 gap-[12px]">
          <label className="text-[0.78rem] font-semibold text-[#475569]">Student<select required value={form.student_id} onChange={(e) => setForm({ ...form, student_id: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal"><option value="">Choose an assigned student</option>{students.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.email}</option>)}</select></label>
          <label className="text-[0.78rem] font-semibold text-[#475569]">Title<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal" maxLength={160} /></label>
          <label className="text-[0.78rem] font-semibold text-[#475569]">Date<input required type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal" /></label>
          <div className="grid grid-cols-2 gap-[8px]"><label className="text-[0.78rem] font-semibold text-[#475569]">Starts<input required type="time" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal" /></label><label className="text-[0.78rem] font-semibold text-[#475569]">Ends<input required type="time" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal" /></label></div>
          <label className="text-[0.78rem] font-semibold text-[#475569]">Format<select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal"><option value="video">Video call</option><option value="in_person">In person</option><option value="phone">Phone</option></select></label>
          <label className="text-[0.78rem] font-semibold text-[#475569]">Location or link<input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal" placeholder="Optional" /></label>
          <label className="md:col-span-2 text-[0.78rem] font-semibold text-[#475569]">Private preparation note<textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal min-h-[70px]" maxLength={2000} /></label>
        </div>
        <div className="flex justify-end mt-[14px]"><button disabled={saving} className="px-[14px] py-[9px] rounded-[8px] bg-[#0f766e] text-white text-[0.82rem] font-semibold disabled:opacity-50">{saving ? 'Scheduling…' : 'Send appointment request'}</button></div>
      </form>}

      {loading ? <div className="text-[#64748b] text-[0.86rem]">Loading appointments…</div> : <>
        <section><h2 className="text-[0.9rem] font-bold text-[#334155] mb-[10px]">Upcoming <span className="text-[#94a3b8]">({upcoming.length})</span></h2><div className="space-y-[10px]">{upcoming.length ? upcoming.map((a) => <AppointmentCard key={a.id} appointment={a} isStaff={isStaff} onTransition={transition} />) : <Empty message={isStaff ? 'No upcoming appointments. Schedule a check-in when a student is ready.' : 'No upcoming appointments. Your counsellor will send a request when a check-in is arranged.'} />}</div></section>
        <section className="mt-[28px]"><h2 className="text-[0.9rem] font-bold text-[#334155] mb-[10px]">History <span className="text-[#94a3b8]">({past.length})</span></h2><div className="space-y-[10px]">{past.length ? past.map((a) => <AppointmentCard key={a.id} appointment={a} isStaff={isStaff} onTransition={transition} />) : <Empty message="Completed and cancelled appointments will appear here." />}</div></section>
      </>}
    </div>
  )
}

function AppointmentCard({ appointment: a, isStaff, onTransition }: { appointment: Appointment; isStaff: boolean; onTransition: (a: Appointment, status: AppointmentStatus) => void }) {
  const canRespond = !isStaff && a.status === 'REQUESTED'
  return <article className="rounded-[13px] border border-[#e2e8f0] bg-white p-[15px] shadow-sm flex flex-wrap items-center justify-between gap-[12px]">
    <div><div className="flex items-center gap-[8px] flex-wrap"><h3 className="font-semibold text-[#1f2937] text-[0.9rem]">{a.title}</h3><span className={`rounded-full px-[8px] py-[3px] text-[0.66rem] font-bold ${statusStyles[a.status]}`}>{a.status.replace('_', ' ')}</span></div><div className="text-[0.8rem] text-[#475569] mt-[6px]">{dateLabel(a.start_at)} – {new Date(a.end_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</div><div className="text-[0.74rem] text-[#94a3b8] mt-[3px]">{isStaff ? a.student_name : `Counsellor: ${a.counsellor_name}`} · {a.mode.replace('_', ' ')}</div>{a.location && <div className="text-[0.74rem] text-[#64748b] mt-[3px]">{a.location}</div>}</div>
    <div className="flex gap-[7px]">{canRespond && <><button onClick={() => onTransition(a, 'CONFIRMED')} className="px-[10px] py-[7px] rounded-[7px] bg-[#0f766e] text-white text-[0.74rem] font-semibold">Accept</button><button onClick={() => onTransition(a, 'DECLINED')} className="px-[10px] py-[7px] rounded-[7px] border border-[#cbd5e1] text-[#475569] text-[0.74rem] font-semibold">Decline</button></>}{a.status === 'CONFIRMED' && <button onClick={() => onTransition(a, 'CANCELLED')} className="px-[10px] py-[7px] rounded-[7px] border border-[#fecaca] text-[#b91c1c] text-[0.74rem] font-semibold">Cancel</button>}</div>
  </article>
}

function Empty({ message }: { message: string }) { return <div className="rounded-[12px] border border-dashed border-[#cbd5e1] bg-[#f8fafc] p-[22px] text-[0.82rem] text-[#64748b]">{message}</div> }

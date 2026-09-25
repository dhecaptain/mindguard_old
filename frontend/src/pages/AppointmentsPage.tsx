import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { useAuthStore } from '../store'
import { completeAppointmentRecord, createAppointment, getAppointments, updateAppointmentStatus, type Appointment, type AppointmentStatus } from '../api/appointments'
import { getStudents, type StudentDTO } from '../api/counsellor'

const statusStyles: Record<AppointmentStatus, string> = {
  REQUESTED: 'bg-[#fef3c7] text-[#92400e]',
  CONFIRMED: 'bg-[#d1fae5] text-[#065f46]',
  DECLINED: 'bg-[#fee2e2] text-[#991b1b]',
  CANCELLED: 'bg-[#f1f5f9] text-[#475569]',
  COMPLETED: 'bg-[#dbeafe] text-[#1e40af]',
  NO_SHOW: 'bg-[#fce7f3] text-[#9d174d]',
}

function isWebLink(value?: string | null) {
  return Boolean(value && /^https?:\/\//i.test(value.trim()))
}

function icsDate(value: string) {
  return new Date(value).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z')
}

function icsText(value: string) {
  return value.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n')
}

function downloadCalendarFile(appointment: Appointment) {
  const details = [
    appointment.notes,
    appointment.location ? `Location: ${appointment.location}` : '',
    `Format: ${appointment.mode.replace('_', ' ')}`,
  ].filter(Boolean).join('\n')
  const ics = [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//MindGuard//Appointments//EN',
    'BEGIN:VEVENT', `UID:${appointment.id}@mindguard`, `DTSTAMP:${icsDate(new Date().toISOString())}`,
    `DTSTART:${icsDate(appointment.start_at)}`, `DTEND:${icsDate(appointment.end_at)}`,
    `SUMMARY:${icsText(appointment.title)}`, `DESCRIPTION:${icsText(details)}`,
    appointment.location ? `LOCATION:${icsText(appointment.location)}` : '',
    'END:VEVENT', 'END:VCALENDAR',
  ].filter(Boolean).join('\r\n')
  const blob = new Blob([ics], { type: 'text/calendar;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${appointment.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'mindguard-appointment'}.ics`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function googleCalendarUrl(appointment: Appointment) {
  const params = new URLSearchParams({
    action: 'TEMPLATE',
    text: appointment.title,
    dates: `${icsDate(appointment.start_at)}/${icsDate(appointment.end_at)}`,
    details: appointment.notes || 'MindGuard appointment',
    location: appointment.location || '',
  })
  return `https://calendar.google.com/calendar/render?${params.toString()}`
}

export default function AppointmentsPage() {
  const user = useAuthStore((s) => s.user)
  const isStaff = user?.role_type === 'counsellor' || user?.role_type === 'school_admin' || user?.role_type === 'admin'
  const canSchedule = user?.role_type === 'counsellor' || user?.role_type === 'admin'
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [students, setStudents] = useState<StudentDTO[]>([])
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ student_id: '', title: 'Wellbeing check-in', date: '', start: '', end: '', mode: 'google_meet' as 'google_meet' | 'in_person', location: '', notes: '' })

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
      setForm({ student_id: '', title: 'Wellbeing check-in', date: '', start: '', end: '', mode: 'google_meet', location: '', notes: '' })
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
        {canSchedule && <button onClick={() => setShowForm((v) => !v)} className="px-[14px] py-[10px] rounded-[9px] bg-[#0f766e] text-white text-[0.82rem] font-semibold hover:bg-[#115e59]">{showForm ? 'Close' : 'Schedule appointment'}</button>}
      </div>

      {error && <div role="alert" className="mb-[18px] rounded-[9px] bg-[#fef2f2] border border-[#fecaca] text-[#991b1b] px-[14px] py-[11px] text-[0.82rem]">{error}</div>}

      {showForm && <form onSubmit={submit} className="mb-[24px] rounded-[14px] border border-[#dbe5e7] bg-white p-[18px] shadow-sm">
        <h2 className="font-bold text-[#1f2937] mb-[14px]">Propose a wellbeing appointment</h2>
        <div className="grid md:grid-cols-2 gap-[12px]">
          <label className="text-[0.78rem] font-semibold text-[#475569]">Student<select required value={form.student_id} onChange={(e) => setForm({ ...form, student_id: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal"><option value="">Choose an assigned student</option>{students.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.email}</option>)}</select></label>
          <label className="text-[0.78rem] font-semibold text-[#475569]">Title<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal" maxLength={160} /></label>
          <label className="text-[0.78rem] font-semibold text-[#475569]">Date<input required type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal" /></label>
          <div className="grid grid-cols-2 gap-[8px]"><label className="text-[0.78rem] font-semibold text-[#475569]">Starts<input required type="time" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal" /></label><label className="text-[0.78rem] font-semibold text-[#475569]">Ends<input required type="time" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal" /></label></div>
          <label className="text-[0.78rem] font-semibold text-[#475569]">Format<select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value as 'google_meet' | 'in_person', location: '' })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal"><option value="google_meet">Google Meet</option><option value="in_person">Physical meeting</option></select></label>
          <label className="text-[0.78rem] font-semibold text-[#475569]">{form.mode === 'google_meet' ? 'Google Meet link' : 'Physical location'}<input required value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal" placeholder={form.mode === 'google_meet' ? 'https://meet.google.com/...' : 'Counselling office or approved venue'} /></label>
          <label className="md:col-span-2 text-[0.78rem] font-semibold text-[#475569]">Private preparation note<textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="mt-[5px] w-full rounded-[8px] border border-[#cbd5e1] px-[10px] py-[9px] font-normal min-h-[70px]" maxLength={2000} /></label>
        </div>
        <div className="flex justify-end mt-[14px]"><button disabled={saving} className="px-[14px] py-[9px] rounded-[8px] bg-[#0f766e] text-white text-[0.82rem] font-semibold disabled:opacity-50">{saving ? 'Scheduling…' : 'Send appointment request'}</button></div>
      </form>}

      {loading ? <div className="text-[#64748b] text-[0.86rem]">Loading appointments…</div> : <>
      <section><h2 className="text-[0.9rem] font-bold text-[#334155] mb-[10px]">Upcoming <span className="text-[#94a3b8]">({upcoming.length})</span></h2><div className="space-y-[10px]">{upcoming.length ? upcoming.map((a) => <AppointmentCard key={a.id} appointment={a} isStaff={isStaff} canComplete={canSchedule} onTransition={transition} onCompleted={load} />) : <Empty message={isStaff ? 'No upcoming appointments. Schedule a check-in when a student is ready.' : 'No upcoming appointments. Your counsellor will send a request when a check-in is arranged.'} />}</div></section>
        <section className="mt-[28px]"><h2 className="text-[0.9rem] font-bold text-[#334155] mb-[10px]">History <span className="text-[#94a3b8]">({past.length})</span></h2><div className="space-y-[10px]">{past.length ? past.map((a) => <AppointmentCard key={a.id} appointment={a} isStaff={isStaff} canComplete={canSchedule} onTransition={transition} onCompleted={load} />) : <Empty message="Completed and cancelled appointments will appear here." />}</div></section>
      </>}
    </div>
  )
}

function AppointmentCard({ appointment: a, isStaff, canComplete, onTransition, onCompleted }: { appointment: Appointment; isStaff: boolean; canComplete: boolean; onTransition: (a: Appointment, status: AppointmentStatus) => void; onCompleted: () => Promise<void> }) {
  const canRespond = !isStaff && a.status === 'REQUESTED'
  const [showRecord, setShowRecord] = useState(false)
  const start = new Date(a.start_at)
  return <>
  <article className="rounded-[16px] border border-[#e2e8f0] bg-white p-[14px] shadow-sm flex flex-wrap items-center gap-[15px] hover:border-[#99d5ce] transition-colors">
    <div className="w-[66px] h-[70px] rounded-[12px] bg-[#f0fdfa] border border-[#ccfbf1] flex flex-col items-center justify-center flex-shrink-0">
      <span className="text-[0.64rem] uppercase tracking-[0.12em] font-bold text-[#0f766e]">{start.toLocaleDateString(undefined, { month: 'short' })}</span>
      <span className="text-[1.55rem] leading-none font-bold text-[#134e4a] mt-[2px]">{start.getDate()}</span>
      <span className="text-[0.62rem] text-[#5f7775] mt-[3px]">{start.toLocaleDateString(undefined, { weekday: 'short' })}</span>
    </div>
    <div className="min-w-[220px] flex-1">
      <div className="flex items-center gap-[8px] flex-wrap"><h3 className="font-semibold text-[#1f2937] text-[0.92rem]">{a.title}</h3><span className={`rounded-full px-[8px] py-[3px] text-[0.66rem] font-bold ${statusStyles[a.status]}`}>{a.status.replace('_', ' ')}</span></div>
      <div className="flex items-center gap-[6px] text-[0.8rem] text-[#475569] mt-[7px]"><i className="ti ti-clock text-[#0f766e]" />{start.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })} – {new Date(a.end_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}<span className="text-[#cbd5e1]">·</span>{a.timezone}</div>
      <div className="text-[0.74rem] text-[#94a3b8] mt-[4px]">{isStaff ? a.student_name : `Counsellor: ${a.counsellor_name}`} · {a.mode.replace('_', ' ')}</div>
      {a.location && (isWebLink(a.location) ? <a href={a.location} target="_blank" rel="noreferrer" className="inline-flex items-center gap-[5px] text-[0.76rem] text-[#0f766e] hover:text-[#115e59] hover:underline mt-[6px]"><i className="ti ti-video" />Join meeting <i className="ti ti-external-link text-[11px]" /></a> : <div className="inline-flex items-center gap-[5px] text-[0.76rem] text-[#64748b] mt-[6px]"><i className="ti ti-map-pin" />{a.location}</div>)}
    </div>
    <div className="flex flex-wrap items-center gap-[7px] ml-auto">{a.status !== 'DECLINED' && <CalendarActions appointment={a} />}{canRespond && <><button onClick={() => onTransition(a, 'CONFIRMED')} className="px-[10px] py-[7px] rounded-[7px] bg-[#0f766e] text-white text-[0.74rem] font-semibold">Accept</button><button onClick={() => onTransition(a, 'DECLINED')} className="px-[10px] py-[7px] rounded-[7px] border border-[#cbd5e1] text-[#475569] text-[0.74rem] font-semibold">Decline</button></>}{a.status === 'CONFIRMED' && <button onClick={() => onTransition(a, 'CANCELLED')} className="px-[10px] py-[7px] rounded-[7px] border border-[#fecaca] text-[#b91c1c] text-[0.74rem] font-semibold">Cancel</button>}{canComplete && a.status === 'CONFIRMED' && <button onClick={() => setShowRecord((value) => !value)} className="px-[10px] py-[7px] rounded-[7px] bg-[#1e40af] text-white text-[0.74rem] font-semibold">{showRecord ? 'Close record' : 'Complete session'}</button>}</div>
  </article>
  {showRecord && <CompleteSessionForm appointment={a} onCompleted={async () => { setShowRecord(false); await onCompleted() }} />}
  </>
}

function CompleteSessionForm({ appointment, onCompleted }: { appointment: Appointment; onCompleted: () => Promise<void> }) {
  const [privateSummary, setPrivateSummary] = useState('')
  const [studentMessage, setStudentMessage] = useState('')
  const [guardianMessage, setGuardianMessage] = useState('')
  const [referralSummary, setReferralSummary] = useState('')
  const [followUpAt, setFollowUpAt] = useState('')
  const [safeguardingFlag, setSafeguardingFlag] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setError('')
    try {
      await completeAppointmentRecord(appointment.id, { private_summary: privateSummary.trim(), student_message: studentMessage.trim() || undefined, guardian_message: guardianMessage.trim() || undefined, referral_summary: referralSummary.trim() || undefined, follow_up_at: followUpAt ? new Date(followUpAt).toISOString() : undefined, safeguarding_flag: safeguardingFlag })
      await onCompleted()
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to save the session record') }
    finally { setSaving(false) }
  }
  return <form onSubmit={submit} className="rounded-[14px] border border-blue-100 bg-blue-50/40 p-[16px]">
    <div className="mb-[12px]"><h3 className="font-bold text-[#1e3a8a]">Post-appointment record</h3><p className="mt-[3px] text-[0.75rem] text-[#475569]">Keep the private clinical/case summary separate from anything shared with the student or guardian.</p></div>
    <div className="grid gap-[10px] md:grid-cols-2">
      <label className="md:col-span-2 text-[0.76rem] font-semibold text-[#475569]">Private session summary<textarea required value={privateSummary} onChange={(e) => setPrivateSummary(e.target.value)} maxLength={8000} rows={4} className="mt-[4px] w-full rounded-[8px] border border-[#cbd5e1] bg-white px-[10px] py-[8px] font-normal" placeholder="Findings, observations, interventions and professional notes." /></label>
      <label className="text-[0.76rem] font-semibold text-[#475569]">Student-safe update<textarea value={studentMessage} onChange={(e) => setStudentMessage(e.target.value)} maxLength={2000} rows={3} className="mt-[4px] w-full rounded-[8px] border border-teal-200 bg-white px-[10px] py-[8px] font-normal" placeholder="Plain-language encouragement or next step." /></label>
      <label className="text-[0.76rem] font-semibold text-[#475569]">Guardian-safe update<textarea value={guardianMessage} onChange={(e) => setGuardianMessage(e.target.value)} maxLength={2000} rows={3} className="mt-[4px] w-full rounded-[8px] border border-amber-200 bg-white px-[10px] py-[8px] font-normal" placeholder="Only for a linked guardian with active consent." /></label>
      <label className="text-[0.76rem] font-semibold text-[#475569]">Referral-ready summary<textarea value={referralSummary} onChange={(e) => setReferralSummary(e.target.value)} maxLength={4000} rows={3} className="mt-[4px] w-full rounded-[8px] border border-[#cbd5e1] bg-white px-[10px] py-[8px] font-normal" placeholder="Minimum necessary context for a future referral." /></label>
      <label className="text-[0.76rem] font-semibold text-[#475569]">Follow-up date<input type="datetime-local" value={followUpAt} onChange={(e) => setFollowUpAt(e.target.value)} className="mt-[4px] w-full rounded-[8px] border border-[#cbd5e1] bg-white px-[10px] py-[8px] font-normal" /></label>
    </div>
    <label className="mt-[10px] flex items-start gap-[7px] text-[0.76rem] text-[#475569]"><input type="checkbox" checked={safeguardingFlag} onChange={(e) => setSafeguardingFlag(e.target.checked)} className="mt-[2px]" />Safeguarding concern requires appropriate follow-up</label>
    {error && <div role="alert" className="mt-[10px] rounded-[7px] bg-red-50 px-[10px] py-[8px] text-[0.76rem] text-red-700">{error}</div>}
    <div className="mt-[12px] flex justify-end"><button disabled={saving || !privateSummary.trim()} className="rounded-[8px] bg-[#1e40af] px-[13px] py-[8px] text-[0.78rem] font-semibold text-white disabled:opacity-50">{saving ? 'Saving record…' : 'Complete and save record'}</button></div>
  </form>
}

function CalendarActions({ appointment }: { appointment: Appointment }) {
  const [open, setOpen] = useState(false)
  return <div className="relative"><button onClick={() => setOpen((value) => !value)} className="inline-flex items-center gap-[5px] px-[10px] py-[7px] rounded-[7px] border border-[#cbd5e1] text-[#475569] text-[0.74rem] font-semibold hover:bg-[#f8fafc]"><i className="ti ti-calendar-plus" />Calendar</button>{open && <div className="absolute right-0 top-[38px] z-10 w-[170px] rounded-[9px] border border-[#e2e8f0] bg-white p-[5px] shadow-lg"><button onClick={() => { downloadCalendarFile(appointment); setOpen(false) }} className="flex items-center gap-[7px] w-full rounded-[6px] px-[9px] py-[8px] text-left text-[0.74rem] text-[#334155] hover:bg-[#f0fdfa]"><i className="ti ti-download" />Download .ics</button><a href={googleCalendarUrl(appointment)} target="_blank" rel="noreferrer" onClick={() => setOpen(false)} className="flex items-center gap-[7px] rounded-[6px] px-[9px] py-[8px] text-[0.74rem] text-[#334155] hover:bg-[#f0fdfa]"><i className="ti ti-brand-google" />Google Calendar</a></div>}</div>
}

function Empty({ message }: { message: string }) { return <div className="rounded-[12px] border border-dashed border-[#cbd5e1] bg-[#f8fafc] p-[22px] text-[0.82rem] text-[#64748b]">{message}</div> }

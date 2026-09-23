import { useEffect, useState } from 'react'
import api from '../api/client'
import { useUiStore } from '../store/uiStore'

type StudentHome = {
  institution_name: string
  is_minor: boolean
  consent_status: string | null
  guardian_details_present: boolean
  access_status: 'ready' | 'guardian_consent_pending' | 'student_consent_pending'
  assigned_counsellor_name: string | null
  support_active: boolean
}

export default function InstitutionStudentHomePage() {
  const setPage = useUiStore((state) => state.setPage)
  const [home, setHome] = useState<StudentHome | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/institution/student-home')
      .then(({ data }) => setHome(data))
      .catch(() => setError('We could not load your support status. Please refresh or contact your school administrator.'))
  }, [])

  if (error) return <div className="mx-auto max-w-[820px] p-6 md:p-9"><div className="rounded-2xl border border-red-100 bg-red-50 p-5 text-sm text-red-700">{error}</div></div>
  if (!home) return <div className="p-8 text-sm text-slate-500">Loading your wellbeing space…</div>

  const waitingForGuardian = home.access_status === 'guardian_consent_pending'
  const waitingForStudent = home.access_status === 'student_consent_pending'
  const title = home.support_active
    ? 'Your wellbeing support is active'
    : waitingForGuardian
      ? 'We are waiting for parent or guardian permission'
      : waitingForStudent
        ? 'Review your wellbeing permission'
        : 'Your wellbeing space is being prepared'
  const message = home.support_active
    ? `Your support with ${home.institution_name} is ready. You can use the safe options below whenever you need them.`
    : waitingForGuardian
      ? home.guardian_details_present
        ? 'We have emailed your parent or guardian. When they decide, we will let you know. You can still add optional social accounts below.'
        : 'Your school needs a parent or guardian email address before wellbeing support can begin. Please ask your school administrator for help.'
      : waitingForStudent
        ? 'We emailed you a secure permission link. Please open that email and choose whether to give permission before your school counsellor can access protected wellbeing features.'
        : 'Your school is preparing your wellbeing support. You can add optional social accounts while you wait.'

  return <div className="mx-auto max-w-[920px] p-6 md:p-9">
    <section className={`rounded-3xl border p-6 md:p-8 ${home.support_active ? 'border-emerald-200 bg-emerald-50' : waitingForGuardian ? 'border-amber-200 bg-amber-50' : 'border-teal-200 bg-teal-50'}`}>
      <p className="text-xs font-bold uppercase tracking-widest text-[#0f766e]">{home.institution_name}</p>
      <div className="mt-3 flex items-start gap-3"><div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full ${home.support_active ? 'bg-emerald-200 text-emerald-800' : 'bg-white text-[#0f766e]'}`}><i className={`ti ${home.support_active ? 'ti-circle-check' : waitingForGuardian ? 'ti-shield-clock' : 'ti-mail'} text-2xl`} /></div><div><h1 className="text-2xl font-bold text-slate-800">{title}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">{message}</p></div></div>
    </section>

    <section className="mt-6 grid gap-4 md:grid-cols-3">
      <StatusCard icon="ti-user-check" title="Your account" detail="Your MindGuard account is active." complete />
      <StatusCard icon="ti-shield-lock" title={home.is_minor ? 'Parent or guardian permission' : 'Your permission'} detail={home.access_status === 'ready' ? 'Permission accepted.' : waitingForGuardian ? 'Waiting for their decision.' : 'Check your email to decide.'} complete={home.access_status === 'ready'} />
      <StatusCard icon="ti-heart-handshake" title="Counsellor support" detail={home.assigned_counsellor_name ? home.access_status === 'ready' ? `Your counsellor is ${home.assigned_counsellor_name}.` : 'A counsellor is assigned, but support starts after permission.' : 'Your school will match you with a counsellor.'} complete={home.support_active} />
    </section>

    <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="font-bold text-slate-800">What you can do now</h2><p className="mt-1 text-sm text-slate-500">Connecting accounts is optional. Leave anything blank if you do not use it.</p><div className="mt-4 flex flex-wrap gap-3"><button onClick={() => setPage('my-accounts')} className="rounded-lg bg-[#0f766e] px-4 py-2.5 text-sm font-semibold text-white">Manage optional accounts</button><button onClick={() => setPage('resources')} className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700">Get immediate support</button></div>{waitingForGuardian && <p className="mt-4 text-xs leading-5 text-slate-500">Your parent or guardian controls this decision. MindGuard will not ask you to approve it for yourself.</p>}</section>
  </div>
}

function StatusCard({ icon, title, detail, complete }: { icon: string; title: string; detail: string; complete: boolean }) {
  return <div className="rounded-2xl border border-slate-200 bg-white p-5"><i className={`ti ${icon} text-xl ${complete ? 'text-emerald-600' : 'text-amber-600'}`} /><h2 className="mt-3 font-bold text-slate-800">{title}</h2><p className="mt-1 text-sm leading-5 text-slate-500">{detail}</p></div>
}

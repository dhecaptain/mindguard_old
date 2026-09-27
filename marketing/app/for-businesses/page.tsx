import type { Metadata } from 'next'
import Link from 'next/link'
import { PageHero, SectionHeading, Card } from '@/components/ui'

export const metadata: Metadata = {
  title: 'For businesses — MindGuard workplace wellbeing',
  description: 'Voluntary, private workplace wellbeing check-ins with independent care-provider support and protected aggregate-only employer reporting.',
}

const principles = [
  ['Voluntary by design', 'Employees choose whether to join through a shared enrollment link. Employers cannot see who enrolled or opted out.'],
  ['Private employee experience', 'Check-ins are for the employee. No employee social-media monitoring, social account connection, or individual wellbeing dashboard for managers.'],
  ['Independent support', 'An employee can choose to request help from an available independent care provider. The provider receives information only after the employee explicitly requests support and agrees to share it.'],
  ['Protected group reporting', 'Employers see only broad, organization-wide aggregates. Reports are suppressed unless at least 10 distinct employees have completed check-ins; there are no department filters or individual exports.'],
]

export default function ForBusinessesPage() {
  return <div>
    <PageHero eyebrow="For businesses · Kenya-first pilot" title="A workplace wellbeing programme employees can trust" subtitle="Private, voluntary check-ins and access to independent support—without turning wellbeing into employee surveillance." />
    <section className="py-16 sm:py-20"><div className="mg-section">
      <SectionHeading title="Support people, without exposing them" subtitle="MindGuard workplace is separate from our school programme. Employers do not receive employee participation lists, individual responses, referrals, appointments, or care notes." />
      <div className="mt-10 grid gap-5 sm:grid-cols-2">{principles.map(([title, body]) => <Card key={title} title={title}>{body}</Card>)}</div>
      <div className="mt-10 rounded-2xl border border-amber-300 bg-amber-50 p-6 text-sm leading-relaxed text-amber-950">
        <h2 className="text-lg font-semibold">Pilot readiness and privacy review</h2>
        <p className="mt-2">Workplace wellbeing information requires careful handling. Before a live pilot, MindGuard and the participating organisation must complete Kenyan legal and privacy review, including controller/processor roles, employee notice and consent, a DPIA, provider confidentiality, retention, and cross-border processing. The pilot is not presented as legally certified or as a substitute for emergency or clinical care.</p>
      </div>
      <div className="mt-8 flex flex-wrap gap-3"><Link href="/request-demo" className="mg-btn-primary">Discuss a workplace pilot</Link><Link href="/security" className="mg-btn-secondary">Review our security approach</Link></div>
    </div></section>
  </div>
}

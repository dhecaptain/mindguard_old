import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Privacy policy — MindGuard',
  description: 'MindGuard privacy policy.',
}

export default function PrivacyPage() {
  return (
    <div className="py-20">
      <div className="max-w-3xl mx-auto px-6">
        <span className="mg-eyebrow mb-4 inline-block">Legal</span>
        <h1 className="display text-4xl text-ink mb-8">Privacy policy</h1>
        <div className="mg-card p-8 sm:p-10 text-sm leading-relaxed text-ink-soft flex flex-col gap-5">
          <p>
            MindGuard supports separate services for school wellbeing and a limited,
            voluntary workplace wellbeing pilot. This policy describes the broad
            safeguards that apply; the notice shown for each service explains the
            specific processing and choices for that context.
          </p>
          <h2 className="text-lg font-bold text-ink mt-2">Consent before analysis</h2>
          <p>
            No student content is analysed until consent has been given — by the student
            if they are an adult, or by a parent or guardian if they are a minor. Consent
            is recorded, time-stamped and can be revoked at any time. Revoking consent
            stops analysis immediately.
          </p>
          <h2 className="text-lg font-bold text-ink mt-2">Data we hold</h2>
          <p>
            We hold roster information (name, email, date of birth), consent records, and
            analysis events. Student PII is encrypted at rest, and access is limited to
            the counsellors and admins your institution authorises.
          </p>
          <h2 className="text-lg font-bold text-ink mt-2">Your rights</h2>
          <p>
            You may request access to, correction of, or deletion of your data at any
            time by contacting us at the address below.
          </p>
          <h2 className="text-lg font-bold text-ink mt-2">Workplace wellbeing pilot</h2>
          <p>
            Workplace participation is voluntary and uses an employee-shared enrollment
            link with work-email verification. Employers are not given employee
            participation lists or access to individual check-ins, support requests,
            appointments, or care notes. Employer insights are restricted to a fixed,
            organization-wide aggregate and are suppressed below ten distinct employees
            with check-ins. A provider receives an employee&apos;s information only when
            that employee requests support and explicitly chooses what to share. Workplace
            v1 does not connect or analyze personal social accounts and does not send
            wellbeing alerts to an employer.
          </p>
          <p>
            Workplace wellbeing information can be sensitive. A Kenya-first pilot will
            remain gated until the participating parties complete legal and privacy review,
            including roles, employee notice and consent, a DPIA, provider confidentiality,
            retention, and cross-border processing. This product is not represented as
            legally certified or as a substitute for emergency or clinical care.
          </p>
          <h2 className="text-lg font-bold text-ink mt-2">Contact</h2>
          <p>Email: privacy@mindguard.ai</p>
          <p className="text-xs text-ink-soft/70">Last updated: September 2026</p>
        </div>
      </div>
    </div>
  )
}

import type { Metadata } from 'next'
import DemoForm from '@/components/DemoForm'

export const metadata: Metadata = {
  title: 'Request a demo — MindGuard',
  description: 'See MindGuard in action. Fill in the form and our team will reach out within 2 business days.',
}

export default function RequestDemoPage() {
  return (
    <div className="py-20">
      <div className="max-w-2xl mx-auto px-6">
        <span className="mg-eyebrow mb-3 inline-block">Demo request</span>
        <h1 className="display text-4xl text-ink mb-3">Request a demo</h1>
        <p className="text-ink-soft mb-10 max-w-lg">
          Explore how MindGuard supports wellbeing across schools, care organisations, and workplaces — with consent and privacy built in from day one.
        </p>
        <DemoForm />
      </div>
    </div>
  )
}

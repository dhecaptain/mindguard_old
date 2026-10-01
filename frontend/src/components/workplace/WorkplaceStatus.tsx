import { workplaceStatusLabel } from './workplaceStatusUtils'

function toneFor(value: string): 'success' | 'attention' | 'pending' | 'neutral' {
  const state = value.toUpperCase()
  if (['ACTIVE', 'PILOT', 'TRIAL', 'READY', 'COMPLETED', 'APPROVED', 'AVAILABLE'].includes(state)) return 'success'
  if (['GRACE_PERIOD', 'SUSPENDED', 'CANCELLED', 'INSUFFICIENT_DATA', 'ACTION_REQUIRED', 'REASSIGNMENT_REQUIRED', 'PROVIDER_REASSIGNMENT_REQUIRED'].includes(state)) return 'attention'
  if (['PENDING', 'PENDING_REVIEW', 'INVITED'].includes(state)) return 'pending'
  return 'neutral'
}

const TONES = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  attention: 'border-amber-200 bg-amber-50 text-amber-900',
  pending: 'border-sky-200 bg-sky-50 text-sky-900',
  neutral: 'border-slate-200 bg-slate-50 text-slate-700',
}

export function WorkplaceStatus({ value, label }: { value: string; label?: string }) {
  const tone = toneFor(value)
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${TONES[tone]}`}>
    <span className="sr-only">Status: </span>{label || workplaceStatusLabel(value)}
  </span>
}

const LABELS: Record<string, string> = {
  ACTIVE: 'Active', PILOT: 'Pilot', TRIAL: 'Trial', GRACE_PERIOD: 'Payment or contract attention',
  SUSPENDED: 'Temporarily suspended', CANCELLED: 'Cancellation scheduled', TERMINATED: 'Service ended',
  ARCHIVED: 'Archived', READY: 'Ready for enrollment', INSUFFICIENT_DATA: 'More participation needed for privacy',
  NO_DATA: 'No completed-period data', NOT_ENTITLED: 'Not included in this plan', WORKPLACE_INACTIVE: 'Workplace inactive',
  PROVIDER_REASSIGNMENT_REQUIRED: 'Choose another provider', REASSIGNMENT_REQUIRED: 'Choose another provider',
  PENDING: 'Invitation pending', PENDING_REVIEW: 'MindGuard review pending', COMPLETED: 'Complete', ACTION_REQUIRED: 'Action required',
}

export function workplaceStatusLabel(value: string | null | undefined): string {
  if (!value) return 'Status unavailable'
  return LABELS[value.toUpperCase()] || value.replaceAll('_', ' ').toLowerCase().replace(/\b\w/g, letter => letter.toUpperCase())
}

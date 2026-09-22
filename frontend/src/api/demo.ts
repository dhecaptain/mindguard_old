import api from './client'

// ─── Demo request pipeline — public submission (Delivery Brief §6) ───────────

export interface DemoSubmission {
  full_name: string
  work_email: string
  organisation: string
  organisation_type: string
  role_title?: string
  country?: string
  student_count_range?: string
  message?: string
  heard_about_us?: string
  consent_to_contact: boolean
}

export async function submitDemoRequest(payload: DemoSubmission): Promise<{
  id: string
  status: string
  warning?: string | null
}> {
  const { data } = await api.post('/v1/demo-requests', payload)
  return data
}

export interface DemoResponseDetails {
  full_name: string | null
  organisation: string | null
  meeting_at: string | null
  meeting_url: string | null
  meeting_response: string | null
}

export async function getDemoResponseDetails(token: string): Promise<DemoResponseDetails> {
  const { data } = await api.get('/v1/demo-requests/respond', { params: { token } })
  return data
}

export async function respondToDemoMeeting(
  token: string,
  action: 'accept' | 'reschedule',
  note?: string,
): Promise<{ ok: boolean; meeting_response: string }> {
  const { data } = await api.post('/v1/demo-requests/respond', {
    action,
    ...(note?.trim() ? { note: note.trim() } : {}),
  }, { params: { token } })
  return data
}

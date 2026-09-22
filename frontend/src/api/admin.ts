import api from './client'
import type {
  AuditEvent,
  DemoRequest,
  DemoRequestStatus,
  Institution,
  RosterCommitResult,
  RosterStudent,
  RosterUploadSummary,
  InstitutionSetup,
  InstitutionStaff,
} from '../types'

// ─── Roster & School Admin (Delivery Brief §5) ────────────────────────────────

export async function getInstitutions(): Promise<Institution[]> {
  const { data } = await api.get('/v1/admin/institutions')
  return data.institutions ?? data
}

export async function createInstitution(
  name: string,
  type = 'university',
): Promise<Institution> {
  const { data } = await api.post('/v1/admin/institutions', { name, type })
  return data
}

export async function updateInstitution(id: string, patch: { status?: string; name?: string; type?: string }): Promise<Institution> {
  const { data } = await api.patch(`/v1/admin/institutions/${id}`, patch)
  return data
}

export interface RosterConflict {
  id: string
  student_id: string
  name: string
  email: string
  institution: { id: string | null; name: string }
  has_linked_account: boolean
}

export async function findRosterConflict(studentId: string): Promise<RosterConflict> {
  const { data } = await api.get('/v1/admin/roster-conflicts', { params: { student_id: studentId } })
  return data
}

export async function purgeRosterConflict(studentId: string): Promise<{ ok: boolean; linked_account_preserved: boolean }> {
  const { data } = await api.post('/v1/admin/roster-conflicts/purge', {
    student_id: studentId,
    confirmation: studentId,
  })
  return data
}

export async function getInstitutionSetup(): Promise<InstitutionSetup> {
  const { data } = await api.get('/institution/setup')
  return data
}

export async function getInstitutionStaff(): Promise<InstitutionStaff[]> {
  const { data } = await api.get('/institution/staff')
  return data
}

export async function inviteInstitutionStaff(payload: { name: string; email: string; role_type: 'school_admin' | 'counsellor'; institution_id?: string }) {
  const { data } = await api.post('/institution/staff', payload)
  return data
}

export async function markInstitutionReady() {
  const { data } = await api.post('/institution/ready')
  return data
}

export interface InstitutionStudentStatus {
  id: string
  account_id?: string | null
  name: string
  email: string
  is_minor: boolean
  grade_level?: string | null
  account_status?: string | null
  consent_status?: string | null
  counsellor_id?: string | null
  counsellor_name?: string | null
  invitation_pending: boolean
  onboarding_state: string
}

export interface InstitutionAssignment {
  id: string
  student_id: string
  student_name: string
  student_email: string
  counsellor_id: string
  counsellor_name: string
  counsellor_email: string
  assigned_at: string
}

export async function getInstitutionStudentStatus(): Promise<InstitutionStudentStatus[]> {
  const { data } = await api.get('/institution/students/status')
  return data
}

export async function resendStudentInvite(studentId: string) {
  const { data } = await api.post(`/institution/students/${studentId}/resend-invite`)
  return data
}

export async function getInstitutionAssignments(): Promise<InstitutionAssignment[]> {
  const { data } = await api.get('/institution/assignments')
  return data
}

export async function getAssignableInstitutionUsers(): Promise<{
  counsellors: Array<{ id: string; name: string; email: string; status: string; profile_completed_at?: string }>
  students: Array<{ id: string; name: string; email: string; status: string; assignment_id?: string; counsellor_id?: string; counsellor_name?: string }>
}> {
  const { data } = await api.get('/institution/assignable')
  return data
}

export async function assignInstitutionStudent(counsellorId: string, studentId: string) {
  const { data } = await api.post('/institution/assignments', { counsellor_id: counsellorId, student_id: studentId })
  return data
}

export async function removeInstitutionAssignment(id: string) {
  const { data } = await api.delete(`/institution/assignments/${id}`)
  return data
}

export async function getRosterStudents(
  institutionId?: string,
  limit = 500,
): Promise<RosterStudent[]> {
  const { data } = await api.get('/v1/admin/students', {
    params: institutionId ? { institution_id: institutionId, limit } : { limit },
  })
  return data.students ?? data
}

export async function uploadRoster(
  file: File,
  institutionId: string,
): Promise<RosterUploadSummary> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post(`/v1/admin/roster/upload?institution_id=${institutionId}`, form)
  return data
}

export async function commitRoster(
  file: File,
  institutionId: string,
): Promise<RosterCommitResult> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post(`/v1/admin/roster/commit?institution_id=${institutionId}`, form)
  return data
}

export async function runConsentMaintenance(): Promise<{
  expired: number
  reminders: { sent: number; failed: number }
}> {
  const { data } = await api.post('/v1/admin/consents/run-maintenance')
  return data
}

// ─── Demo request pipeline (Delivery Brief §6) ────────────────────────────────

export async function getDemoRequests(
  status?: string,
  limit = 100,
): Promise<DemoRequest[]> {
  const { data } = await api.get('/v1/admin/demo-requests', {
    params: { limit, ...(status ? { status } : {}) },
  })
  return data.demo_requests ?? data
}

export async function updateDemoRequest(
  id: string,
  patch: Partial<Pick<DemoRequest, 'status' | 'notes' | 'assigned_to' | 'meeting_at' | 'meeting_url'>>,
): Promise<DemoRequest> {
  const { data } = await api.patch(`/v1/admin/demo-requests/${id}`, patch)
  return data
}

export async function convertDemoRequest(id: string): Promise<{
  demo_request: DemoRequest
  institution: Institution
  staff: { id: string; email: string; name: string; role_type: string }
  email_sent: boolean
  email_error?: string | null
}> {
  const { data } = await api.post(`/v1/admin/demo-requests/${id}/convert`)
  return data
}

export async function scheduleDemoRequest(id: string, meeting_at: string, meeting_url: string): Promise<{
  demo_request: DemoRequest
  calendar_url: string
  email_sent: boolean
  email_error?: string | null
}> {
  const { data } = await api.post(`/v1/admin/demo-requests/${id}/schedule`, { meeting_at, meeting_url })
  return data
}

export const DEMO_STATUSES: DemoRequestStatus[] = [
  'new',
  'contacted',
  'qualified',
  'demo_scheduled',
  'institution_provisioning',
  'onboarding',
  'closed_won',
  'closed_lost',
]

// ─── Audit / compliance trail (Delivery Brief §12) ───────────────────────────

export async function getAdminAuditLog(limit = 50): Promise<AuditEvent[]> {
  const { data } = await api.get('/v1/admin/audit', { params: { limit } })
  return data.entries ?? data
}

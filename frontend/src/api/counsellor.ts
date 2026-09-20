import api from './client'
import type {
  Consent, ConsentListResponse, ConsentDetail, LinkedAccount, Alert, AlertDisposition,
  AuditEvent, Note, TimelineEntry,
  Group, GroupDetail, GroupMessage,
  ConversationsResponse, NotificationPreference,
} from '../types'

export interface StudentDTO {
  id: string
  name: string
  email: string
  role_type: string
  status: string
  created_at: string
}

export interface StudentDetail {
  id: string
  email: string
  name: string
  status: string
  created_at: string
  risk_summary: {
    latest_prob: number
    latest_label: string
    latest_color: string
    total_analyses: number
    high_risk_count: number
  }
  rolling_risk: {
    id: string
    student_id: string
    computed_at: string
    score: number
    window_days: number
    top_platform: string
    n_posts: number
  } | null
  analyses: Array<{
    id: string
    platform: string
    text: string | null
    prob: number
    label: string
    created_at: string
  }>
  consent_status?: {
    enforced: boolean
    active: boolean
    consent_id?: string | null
    expires_at?: string | null
    expiry_days?: number
  }
}

export interface StudentAnalysisResult {
  student_id: string
  platform: string
  rolling_score: number
  n_posts: number
  risk_record: {
    score: number
    top_platform: string
    n_posts: number
    updated_at: string
  }
  alert_created: boolean
  alert: {
    id: string
    level: string
    reason_code: string
  } | null
}

export interface Referral {
  id: string
  counsellor_id: string
  student_id: string
  urgency: string
  status: string
  notes: string
  destination?: string | null
  follow_up_at?: string | null
  outcome?: string | null
  created_at: string
  updated_at: string
  student_name?: string
  student_email?: string
}

export interface Conversation {
  other_id: string
  other_name: string
  other_email: string
  last_message: string
  last_time: string
  unread: number
}

export interface Message {
  id: string
  sender_id: string
  receiver_id: string
  message: string
  read: number
  created_at: string
}

export interface DashboardData {
  total_students: number
  pending_approvals: number
  open_referrals: number
  crisis_flags_7d: number
  recent_referrals: Referral[]
}

export async function getStudents(): Promise<StudentDTO[]> {
  const { data } = await api.get('/counsellor/students')
  return data
}

export async function getStudentDetail(id: string): Promise<StudentDetail> {
  const { data } = await api.get(`/counsellor/students/${id}`)
  return data
}

// ─── Consent-gated student analysis ───────────────────────────────────────────

export async function analyzeStudent(
  studentId: string,
  payload: { platform: string; posts: Array<{ risk_score: number; date?: string; text?: string }> }
): Promise<StudentAnalysisResult> {
  const { data } = await api.post(`/v1/students/${studentId}/analyze`, payload)
  return data
}

export async function approveStudent(id: string): Promise<{ ok: boolean; email_sent: boolean; email_error?: string | null }> {
  const { data } = await api.post('/counsellor/students/approve', { id })
  return data
}

export async function revokeStudent(id: string): Promise<{ ok: boolean; email_sent: boolean; email_error?: string | null }> {
  const { data } = await api.post('/counsellor/students/revoke', { id })
  return data
}

export async function getReferrals(): Promise<Referral[]> {
  const { data } = await api.get('/counsellor/referrals')
  return data
}

export async function createReferral(student_id: string, urgency: string, notes: string, destination?: string, follow_up_at?: string): Promise<Referral> {
  const { data } = await api.post('/counsellor/referrals', { student_id, urgency, notes, destination, follow_up_at })
  return data
}

export async function updateReferral(id: string, updates: { status?: string; notes?: string; outcome?: string; follow_up_at?: string; reason?: string }): Promise<Referral> {
  const { data } = await api.patch(`/counsellor/referrals/${id}`, updates)
  return data
}

export async function getConversations(): Promise<Conversation[]> {
  const { data } = await api.get('/counsellor/conversations')
  return data
}

export async function getConversation(otherId: string): Promise<Message[]> {
  const { data } = await api.get(`/counsellor/conversations/${otherId}`)
  return data
}

export async function sendMessage(receiver_id: string, message: string): Promise<Message> {
  const { data } = await api.post('/counsellor/messages', { receiver_id, message })
  return data
}

export async function getDashboard(): Promise<DashboardData> {
  const { data } = await api.get('/counsellor/dashboard')
  return data
}

// ─── Consents ─────────────────────────────────────────────────────────────────

export async function getConsents(params?: {
  status?: string
  search?: string
  dateFrom?: string
  dateTo?: string
  limit?: number
  offset?: number
}): Promise<ConsentListResponse> {
  // Backend expects snake_case query params (date_from / date_to).
  const { dateFrom, dateTo, ...rest } = params ?? {}
  const { data } = await api.get('/v1/consents', {
    params: {
      ...rest,
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo ? { date_to: dateTo } : {}),
    },
  })
  return { consents: data.consents ?? data, total: data.total ?? data.length ?? 0 }
}

export async function exportConsents(params?: {
  status?: string
  search?: string
  dateFrom?: string
  dateTo?: string
}): Promise<Blob> {
  const { dateFrom, dateTo, ...rest } = params ?? {}
  const { data } = await api.get('/v1/consents/export', {
    params: {
      ...rest,
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo ? { date_to: dateTo } : {}),
    },
    responseType: 'blob',
  })
  return data
}

export async function getConsentDetail(id: string): Promise<ConsentDetail> {
  const { data } = await api.get(`/v1/consents/${id}`)
  return data
}

export async function createConsent(
  studentId: string,
  payload: {
    recipient_email: string
    recipient_role: 'student' | 'parent'
    platforms: string[]
    mode: 'ON_DEMAND' | 'CONTINUOUS'
  }
): Promise<Consent> {
  const { data } = await api.post(`/v1/students/${studentId}/consent`, payload)
  return data
}

export async function dispatchConsent(consentId: string): Promise<Consent> {
  const { data } = await api.post(`/v1/consents/${consentId}/dispatch`)
  return data
}

export async function cancelConsent(consentId: string): Promise<void> {
  await api.post(`/v1/consents/${consentId}/cancel`)
}

export async function remindConsent(consentId: string): Promise<Partial<Consent>> {
  const { data } = await api.post(`/v1/consents/${consentId}/remind`)
  return data
}

/** Record the recipient's decision from the tracker (paper/verbal consent). */
export async function recordConsentDecision(
  consentId: string,
  decision: 'ACCEPTED' | 'DECLINED',
  signatureName?: string,
): Promise<{ ok: boolean; status: string; email_sent: boolean }> {
  const { data } = await api.post(`/v1/consents/${consentId}/decision`, {
    decision,
    signature_name: signatureName || undefined,
  })
  return data
}

// ─── Account Linking ──────────────────────────────────────────────────────────

export async function getLinkedAccounts(studentId: string): Promise<LinkedAccount[]> {
  const { data } = await api.get(`/v1/students/${studentId}/accounts`)
  return data
}

export async function linkAccount(
  studentId: string,
  payload: { platform: string; mode: 'handle'; handle: string }
): Promise<LinkedAccount> {
  const { data } = await api.post(`/v1/students/${studentId}/accounts`, payload)
  return data
}

export async function unlinkAccount(studentId: string, accountId: string): Promise<void> {
  await api.delete(`/v1/students/${studentId}/accounts/${accountId}`)
}

// ─── Alerts ───────────────────────────────────────────────────────────────────

export async function getAlerts(status?: 'OPEN' | 'CLOSED'): Promise<Alert[]> {
  const { data } = await api.get('/v1/alerts', { params: status ? { status } : undefined })
  return data.alerts ?? data
}

export async function disposeAlert(
  alertId: string,
  payload: { action: AlertDisposition; reason_code: string; reason_note?: string }
): Promise<Alert> {
  const { data } = await api.post(`/v1/alerts/${alertId}/disposition`, payload)
  return data
}

// ─── Timeline ─────────────────────────────────────────────────────────────────

export async function getStudentTimeline(studentId: string): Promise<TimelineEntry[]> {
  const { data } = await api.get(`/v1/students/${studentId}/timeline`)
  return data
}

// ─── Notes ────────────────────────────────────────────────────────────────────

export async function getNotes(studentId: string): Promise<Note[]> {
  const { data } = await api.get(`/v1/students/${studentId}/notes`)
  return data
}

export async function createNote(studentId: string, body: string): Promise<Note> {
  const { data } = await api.post(`/v1/students/${studentId}/notes`, { body })
  return data
}

// ─── Audit Log ────────────────────────────────────────────────────────────────

export async function getAuditLog(): Promise<AuditEvent[]> {
  const { data } = await api.get('/v1/audit')
  return data.entries ?? data
}


// ─── Group Messaging ──────────────────────────────────────────────────────────

export async function getGroups(): Promise<{ groups: Group[]; total: number }> {
  const { data } = await api.get('/v1/groups')
  return data
}

export async function getGroup(id: string): Promise<GroupDetail> {
  const { data } = await api.get(`/v1/groups/${id}`)
  return data
}

export async function createGroup(payload: {
  name: string
  description?: string
  member_ids?: string[]
}): Promise<GroupDetail> {
  const { data } = await api.post('/v1/groups', payload)
  return data
}

export async function updateGroup(id: string, payload: { name?: string; description?: string }): Promise<Group> {
  const { data } = await api.patch(`/v1/groups/${id}`, payload)
  return data
}

export async function deleteGroup(id: string): Promise<void> {
  await api.delete(`/v1/groups/${id}`)
}

export async function addGroupMembers(groupId: string, userIds: string[]): Promise<{ added: number }> {
  const { data } = await api.post(`/v1/groups/${groupId}/members`, { user_ids: userIds })
  return data
}

export async function removeGroupMember(groupId: string, userId: string): Promise<void> {
  await api.delete(`/v1/groups/${groupId}/members/${userId}`)
}

export async function getGroupMessages(groupId: string, limit = 50, beforeId?: string): Promise<{ messages: GroupMessage[]; total: number }> {
  const params: any = { limit }
  if (beforeId) params.before_id = beforeId
  const { data } = await api.get(`/v1/groups/${groupId}/messages`, { params })
  return data
}

export async function sendGroupMessage(groupId: string, message: string): Promise<GroupMessage> {
  const { data } = await api.post(`/v1/groups/${groupId}/messages`, { message })
  return data
}

export async function markGroupRead(groupId: string): Promise<void> {
  await api.post(`/v1/groups/${groupId}/read`)
}


// ─── General Messaging ────────────────────────────────────────────────────────

export async function getMyConversations(): Promise<ConversationsResponse> {
  const { data } = await api.get('/messages/conversations')
  return data
}

export async function sendDirectMessage(receiverId: string, message: string): Promise<any> {
  const { data } = await api.post('/messages/send', { receiver_id: receiverId, message })
  return data
}

export async function getDirectConversation(otherId: string): Promise<any[]> {
  const { data } = await api.get(`/messages/conversations/${otherId}`)
  return data
}

export async function markAllReadWith(otherId: string): Promise<void> {
  await api.post(`/messages/read-all/${otherId}`)
}


// ─── Notification Preferences ─────────────────────────────────────────────────

export async function getNotificationPreferences(): Promise<{ preferences: NotificationPreference[] }> {
  const { data } = await api.get('/notifications/preferences')
  return data
}

export async function updateNotificationPreference(
  type: string,
  payload: { enabled?: boolean; muted_groups?: string[] }
): Promise<NotificationPreference> {
  const { data } = await api.put(`/notifications/preferences/${type}`, payload)
  return data
}

export async function toggleGroupMute(groupId: string, muted: boolean): Promise<{ muted_groups: string[] }> {
  const { data } = await api.put('/notifications/preferences/mute-group', { group_id: groupId, muted })
  return data
}

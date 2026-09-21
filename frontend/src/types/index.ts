export type RiskLevel = 'low' | 'moderate' | 'high' | 'critical'
export type Classification = 'Suicidal' | 'Non-Suicidal'
export type InputMode = 'text' | 'image'
export type RoleType = 'student' | 'counsellor' | 'school_admin' | 'admin'

export interface AnalysisResult {
  prob: number
  latency_ms: number
  label: string
  risk_level: RiskLevel
  risk_color: string
  alert_eligible: boolean
  crisis_escalation_eligible: boolean
}

export interface HistoryEntry {
  ts: string
  cls: Classification
  prob: number
  txt: string
}

export interface Analytics {
  total_analyses: number
  positive_count: number
  negative_count: number
  history: HistoryEntry[]
}

export interface SocioeconomicSignal {
  keyword: string
  snippet: string
}

export interface PlatformResult {
  df: PostData[]
  overall: number
  n_posts: number
  n_high: number
  signals: Record<string, SocioeconomicSignal[]>
  min_risk: number
  n_show: number
  platform_key?: string
  handle?: string
}

export interface PostData {
  text: string
  date: string
  url?: string
  risk_score: number
  raw_risk_score?: number
  low_context?: boolean
  adjustment_reason?: string
  word_count?: number
  char_count?: number
  subreddit?: string
  type?: string
}

export interface VideoResult {
  ok: boolean
  risk: number
  transcription?: string
  label?: string
  latency_ms?: number
  video_url?: string
  signals?: Record<string, SocioeconomicSignal[]>
}

export interface UserInfo {
  id: string
  email: string
  name: string
  role: string
  role_type: RoleType
  referral_code: string
  terms_accepted?: boolean
  dob?: string
  parent_email?: string
  user_category?: 'staff' | 'adult' | 'minor' | 'parent' | 'institution_managed' | 'pending'
  onboarding_completed?: boolean
}

export interface CrisisResource {
  name: string
  contact: string
  type: string
}

export interface TeamMember {
  name: string
  role: string
  bio: string
  image: string
  linkedin: string
}

export interface Notification {
  id: string
  sender: string
  target: string
  subject: string
  body: string
  timestamp: string
  read_by: string[]
}

export const RISK_THRESHOLDS = {
  low: 0.35,
  moderate: 0.55,
  high: 0.75,
  alert: 0.55,
  critical: 0.75,
} as const

export function getRiskLabel(score: number): { label: string; color: string; level: RiskLevel } {
  if (score < 0.35) return { label: 'Low Risk', color: '#22c55e', level: 'low' }
  if (score < 0.55) return { label: 'Moderate Risk', color: '#f59e0b', level: 'moderate' }
  if (score < 0.75) return { label: 'High Risk', color: '#f97316', level: 'high' }
  return { label: 'Critical Risk', color: '#ef4444', level: 'critical' }
}

export function getClassification(prob: number): Classification {
  return prob >= 0.5 ? 'Suicidal' : 'Non-Suicidal'
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

// ─── Consent & Account Linking ───────────────────────────────────────────────

export type ConsentStatus =
  | 'DRAFT' | 'PENDING' | 'VIEWED' | 'ACCEPTED'
  | 'DECLINED' | 'EXPIRED' | 'REVOKED' | 'RENEWAL_DUE' | 'INVALID'

export type AlertStatus = 'OPEN' | 'CLOSED'
export type AlertDisposition =
  | 'REACH_OUT' | 'SCHEDULE_CHECKIN' | 'ESCALATE' | 'DISMISS'

export interface Consent {
  id: string
  student_id: string
  counsellor_id: string
  recipient_email: string
  recipient_role: 'student' | 'parent'
  status: ConsentStatus
  platforms_json: string  // JSON array
  mode: 'ON_DEMAND' | 'CONTINUOUS'
  dispatched_at?: string
  viewed_at?: string
  accepted_at?: string
  declined_at?: string
  revoked_at?: string
  expires_at?: string
  created_at: string
  student_name?: string  // joined from users
  student_email?: string  // joined from users
  email_sent?: boolean
  email_error?: string
  consent_url?: string
  response_user_agent?: string
  template_version?: string
  delivery_status?: 'delivered' | 'bounced' | 'complained'
  last_delivery_event_at?: string
}

export interface ConsentListResponse {
  consents: Consent[]
  total: number
}

export interface ConsentEvent {
  id: string
  consent_id: string
  event_type: string
  actor_type: string
  actor_id?: string
  metadata_json?: string
  created_at: string
}

export interface ConsentAuditEntry {
  id: string
  actor_id?: string
  actor_role?: string
  action: string
  target_type?: string
  target_id?: string
  payload_json?: string
  ip?: string
  occurred_at: string
}

export interface ConsentDetail {
  consent: Consent
  events: ConsentEvent[]
  audit_log: ConsentAuditEntry[]
}

// ─── Roster & School Admin (Delivery Brief §5) ────────────────────────────────

export interface RosterStudent {
  id: string
  student_id_hash: string
  name: string
  email: string
  is_minor: boolean
  grade_level?: string
  consent_status?: string | null
}

export interface Institution {
  id: string
  name: string
  type?: string
  minor_age_threshold?: number
  consent_reminder_days?: string
  consent_expiry_days?: number
}

export interface RosterUploadSummary {
  total: number
  created: number
  updated: number
  minors: number
  adults: number
  errors: Array<{ row_number?: number; row: Record<string, string>; error: string }>
  parse_error?: string | null
  student_ids?: string[]
}

export interface RosterDispatchSummary {
  checked: number
  created: number
  dispatched: number
  email_queued: number
  courtesy_queued: number
  skipped_live: number
  skipped_no_parent: number
  users_created?: number
  routing_errors: Array<{ student_id: string; reason: string }>
}

export interface RosterCommitResult {
  roster: RosterUploadSummary
  dispatch: RosterDispatchSummary
}

// ─── Demo request pipeline (Delivery Brief §6) ────────────────────────────────

export type DemoRequestStatus =
  | 'new'
  | 'contacted'
  | 'qualified'
  | 'demo_scheduled'
  | 'institution_provisioning'
  | 'onboarding'
  | 'closed_won'
  | 'closed_lost'

export interface DemoRequest {
  id: string
  full_name: string
  work_email: string
  organisation: string
  organisation_type: string
  role_title?: string | null
  country?: string | null
  student_count_range?: string | null
  message?: string | null
  heard_about_us?: string | null
  status: DemoRequestStatus
  assigned_to?: string | null
  notes?: string | null
  consent_to_contact?: number
  created_at: string
  updated_at: string
  meeting_at?: string | null
  meeting_url?: string | null
  meeting_response?: 'PENDING' | 'ACCEPTED' | 'RESCHEDULE_REQUESTED' | null
  meeting_response_note?: string | null
  institution_id?: string | null
  converted_at?: string | null
}

export interface LinkedAccount {
  id: string
  student_id: string
  platform: string
  mode: 'oauth' | 'handle'
  handle?: string
  status: 'active' | 'stale' | 'revoked'
  last_synced_at?: string
  created_at: string
}

export interface Alert {
  id: string
  student_id: string
  counsellor_id: string
  fired_at: string
  risk_score: number
  threshold_at_fire: number
  platform?: string
  status: AlertStatus
  disposition?: AlertDisposition
  disposition_reason?: string
  disposition_note?: string
  dispositioned_at?: string
  student_name?: string  // joined
  student_email?: string  // joined
}

export interface AuditEvent {
  id: string
  actor_id?: string
  actor_role?: string
  action: string
  target_type?: string
  target_id?: string
  payload_json?: string
  ip?: string
  occurred_at: string
}

export interface Note {
  id: string
  student_id: string
  author_id: string
  body: string
  created_at: string
  updated_at: string
  author_name?: string
}

export interface RollingRisk {
  id: string
  student_id: string
  computed_at: string
  score: number
  window_days: number
  top_platform?: string
  n_posts: number
}

export interface TimelineEntry {
  date: string
  score: number
  top_platform?: string
  n_posts: number
  alert?: Alert
}


// ─── Group Messaging ──────────────────────────────────────────────────────────

export interface Group {
  id: string
  name: string
  description: string
  avatar_url: string
  created_by: string
  is_active: boolean
  member_count: number
  unread_count: number
  created_at: string
  updated_at: string
}

export interface GroupMember {
  id: string
  user_id: string
  name: string
  email: string
  role: 'admin' | 'member'
  joined_at: string
}

export interface GroupDetail extends Group {
  members: GroupMember[]
}

export interface GroupMessage {
  id: string
  group_id: string
  sender_id: string
  sender_name: string
  message: string
  created_at: string
}

export interface DirectMessage {
  id: string
  sender_id: string
  receiver_id: string
  message: string
  created_at: string
}

export interface GroupConversationPreview {
  type: 'group'
  group_id: string
  name: string
  avatar_url: string
  member_count: number
  last_message: string
  last_time: string
  last_sender: string
  unread: number
}

export interface Conversation {
  other_id: string
  other_name: string
  other_email: string
  last_message: string
  last_time: string
  last_sender: string
  unread: number
}

export interface ConversationsResponse {
  direct: Conversation[]
  groups: GroupConversationPreview[]
}

// ─── Notification Preferences ─────────────────────────────────────────────────

export interface NotificationPreference {
  type: string
  enabled: boolean
  muted_groups: string[]
}

export const NOTIFICATION_TYPE_LABELS: Record<string, string> = {
  message: 'Direct Messages',
  group_message: 'Group Messages',
  alert: 'Risk Alerts',
  referral: 'Referrals',
  broadcast: 'Broadcasts',
  consent: 'Consent Updates',
  approval: 'Account Approval',
  system: 'System Notifications',
}

export const NOTIFICATION_TYPE_ICONS: Record<string, string> = {
  message: 'ti ti-mail',
  group_message: 'ti ti-messages',
  alert: 'ti ti-alert-triangle',
  referral: 'ti ti-link',
  broadcast: 'ti ti-bullhorn',
  consent: 'ti ti-file-check',
  approval: 'ti ti-user-check',
  system: 'ti ti-info-circle',
}

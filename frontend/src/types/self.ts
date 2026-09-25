import type { RiskLevel } from './index'

export type PlatformKey =
  | 'reddit'
  | 'bluesky'
  | 'mastodon'
  | 'youtube'
  | 'instagram'
  | 'twitter'
  | 'facebook'
  | 'linkedin'
  | 'tiktok'

export type VerificationStatus = 'pending' | 'verified' | 'failed' | 'not_connected'

export type AnalysisStatus = 'not_run' | 'completed' | 'error' | 'running'

export interface PlatformCredentialsSpec {
  required: boolean
  type?: 'app_password' | 'server_key'
  label?: string
  why?: string
  where?: string
  hint?: string
  secret_fields?: string[]
  steps?: string[]
}

export interface PlatformSpec {
  key: PlatformKey | string
  display_name: string
  icon: string
  blurb: string
  required_input: string
  handle_label: string
  handle_format: string
  handle_example: string
  accepts_url: boolean
  credentials: PlatformCredentialsSpec
  requires_public: string
  privacy_note: string
  capabilities: string
  limitations: string
  analyzable: boolean
  data_source: string
  server_config_required: boolean
  server_config_note: string
  analyze_step_label: string
  // connection state (injected by GET /api/self/platforms)
  connected: boolean
  verification_status: VerificationStatus | string
  verified_handle?: string | null
  verified_profile_url?: string | null
  analysis_status: AnalysisStatus | string
  handle?: string | null
  profile_url?: string | null
  consented?: boolean
  consent_pending?: boolean
  consent_id?: string | null
}

export interface SelfSocialAccount {
  id: string
  student_id: string
  platform: string
  handle?: string | null
  profile_url?: string | null
  active: number
  created_at: string
  updated_at: string
  has_credentials: boolean
  verification_status: VerificationStatus | string
  verified_handle?: string | null
  verified_profile_url?: string | null
  last_verified_at?: string | null
  reverification_required?: number | boolean
  availability_status?: string | null
  analysis_status: AnalysisStatus | string
}

export interface AddAccountPayload {
  platform: string
  handle?: string
  profile_url?: string
  channel?: string
  credentials?: Record<string, string>
}

export interface TrendInfo {
  direction: 'rising' | 'falling' | 'stable' | 'insufficient_data' | string
  description: string
  delta?: number
}

export interface TopPost {
  platform: string
  text: string
  risk_score: number
  level: RiskLevel | string
  date?: string | null
  url?: string | null
}

export interface PlatformBreakdown {
  platform: string
  posts_analyzed: number
  earliest?: string | null
  latest?: string | null
  average_risk?: number | null
  distribution: Record<RiskLevel, number>
}

export interface SocioeconomicSignal {
  keyword: string
  snippet: string
}

export interface Findings {
  platforms_analyzed: string[]
  posts_analyzed: number
  overall_risk?: number | null
  overall_level?: RiskLevel | null
  trend: TrendInfo
  top_posts: TopPost[]
  platforms: PlatformBreakdown[]
  socioeconomic?: SocioeconomicSignal[] | Record<string, SocioeconomicSignal[]> | null
}

export type SessionStatus = 'running' | 'completed' | 'no_data' | 'partial' | 'failed' | string

export interface PlatformProgress {
  status?: string
  message?: string
}

export interface SessionProgress {
  requested?: string[]
  platforms?: Record<string, PlatformProgress>
}

export interface AnalysisSession {
  id: string
  student_id: string
  counsellor_id?: string | null
  institution_id?: string | null
  consent_id?: string | null
  started_at: string
  completed_at?: string | null
  analysis_type: string
  platforms: string[]
  findings: Findings | null
  risk_score?: number | null
  insights: string[] | null
  recommendations: string[] | null
  status: SessionStatus
  progress: SessionProgress | null
  error?: Record<string, unknown> | null
  counsellor_notes?: string | null
  follow_up_status: string
  created_at: string
  updated_at: string
}

export interface VerifyResult {
  platform: string
  verified: boolean
  verification_status: VerificationStatus | string
  verified_handle?: string | null
  verified_profile_url?: string | null
  message: string
}

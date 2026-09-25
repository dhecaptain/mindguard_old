import api from './client'
import type {
  AddAccountPayload,
  AnalysisSession,
  PlatformSpec,
  SelfSocialAccount,
  VerifyResult,
} from '../types/self'

export async function getSelfPlatforms(): Promise<PlatformSpec[]> {
  const { data } = await api.get<{ platforms: PlatformSpec[] }>('/self/platforms')
  return data.platforms
}

export async function getSocialAccounts(): Promise<SelfSocialAccount[]> {
  const { data } = await api.get<{ accounts: SelfSocialAccount[] }>('/self/social-accounts')
  return data.accounts
}

export async function addSocialAccount(
  payload: AddAccountPayload,
): Promise<{ ok: boolean; platform: string; verification_code?: string; verification_instructions?: string }> {
  const { data } = await api.post<{ ok: boolean; platform: string; verification_code?: string; verification_instructions?: string }>('/self/social-accounts', payload)
  return data
}

export async function deleteSocialAccount(platform: string): Promise<void> {
  await api.delete(`/self/social-accounts/${platform}`)
}

export async function verifySocialAccount(platform: string, verificationCode: string): Promise<VerifyResult> {
  const { data } = await api.post<VerifyResult>(`/self/social-accounts/${platform}/verify`, { verification_code: verificationCode })
  return data
}

export async function rotateSocialAccountCode(platform: string): Promise<{ verification_code: string; verification_instructions?: string }> {
  const { data } = await api.post<{ verification_code: string; verification_instructions?: string }>(`/self/social-accounts/${platform}/verification-code`)
  return data
}

export async function analyzeSelfAll(): Promise<{ session: AnalysisSession }> {
  const { data } = await api.post<{ session: AnalysisSession }>('/self/analyze', {})
  return data
}

export async function analyzeSelfPlatform(platform: string): Promise<{ session: AnalysisSession }> {
  const { data } = await api.post<{ session: AnalysisSession }>('/self/analyze', { platform })
  return data
}

export async function getAnalysisSessions(): Promise<{ sessions: AnalysisSession[]; total: number }> {
  const { data } = await api.get<{ sessions: AnalysisSession[]; total: number }>(
    '/self/analysis-sessions',
  )
  return data
}

export async function getAnalysisSession(id: string): Promise<{ session: AnalysisSession }> {
  const { data } = await api.get<{ session: AnalysisSession }>(`/self/analysis-sessions/${id}`)
  return data
}

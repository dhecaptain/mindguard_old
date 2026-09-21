import api from './client'
import type { PlatformResult, VideoResult } from '../types'

export interface TextAnalysisPayload {
  text: string
}

export interface TextAnalysisResponse {
  prob: number
  latency_ms: number
  risk_tier: 'low' | 'moderate' | 'high' | 'critical'
  alert_eligible: boolean
  crisis_escalation_eligible: boolean
  analytics: {
    total_analyses: number
    positive_count: number
    negative_count: number
    history: { ts: string; cls: string; prob: number; txt: string }[]
  }
}

export async function analyzeText(payload: TextAnalysisPayload): Promise<TextAnalysisResponse> {
  const { data } = await api.post('/analysis/text', payload)
  return data
}

export async function analyzeImage(file: File): Promise<TextAnalysisResponse> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post('/analysis/image', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function analyzeReddit(
  username: string,
  clientId: string,
  clientSecret: string,
  minRisk = 0,
  nShow = 20,
): Promise<PlatformResult> {
  const { data } = await api.post('/platforms/reddit', {
    username,
    client_id: clientId,
    client_secret: clientSecret,
    min_risk: minRisk,
    n_show: nShow,
  })
  return data
}

export async function analyzeBluesky(
  handle: string,
  identifier: string,
  password: string,
  minRisk = 0,
  nShow = 20,
): Promise<PlatformResult> {
  const { data } = await api.post('/platforms/bluesky', {
    handle,
    identifier,
    password,
    min_risk: minRisk,
    n_show: nShow,
  })
  return data
}

export async function analyzeMastodon(handle: string, minRisk = 0, nShow = 20): Promise<PlatformResult> {
  const { data } = await api.post('/platforms/mastodon', { handle, min_risk: minRisk, n_show: nShow })
  return data
}

export async function analyzeYouTube(
  channelUrl: string,
  apiKey: string,
  minRisk = 0,
  nShow = 20,
  transcribeVideos = true,
  transcriptLimit = 3,
): Promise<PlatformResult> {
  const { data } = await api.post('/platforms/youtube', {
    channel_url: channelUrl,
    api_key: apiKey,
    min_risk: minRisk,
    n_show: nShow,
    transcribe_videos: transcribeVideos,
    transcript_limit: transcriptLimit,
  })
  return data
}

export async function analyzeVideo(videoUrl: string): Promise<VideoResult> {
  const { data } = await api.post('/platforms/video', { video_url: videoUrl })
  return data
}

export async function analyzeFacebook(profileUrl: string, months = 3, minRisk = 0, nShow = 20): Promise<PlatformResult> {
  const { data } = await api.post('/platforms/facebook', {
    profile_url: profileUrl,
    months,
    min_risk: minRisk,
    n_show: nShow,
  })
  return data
}

export async function analyzeTwitter(profileUrl: string, minRisk = 0, nShow = 20): Promise<PlatformResult> {
  const { data } = await api.post('/platforms/twitter', {
    profile_url: profileUrl,
    min_risk: minRisk,
    n_show: nShow,
  })
  return data
}

export async function analyzeFile(file: File, minRisk = 0, nShow = 20): Promise<PlatformResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('min_risk', String(minRisk))
  form.append('n_show', String(nShow))
  const { data } = await api.post('/platforms/file', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function getUnifiedAnalysis(): Promise<{
  platforms: Record<string, { overall: number; n_posts: number; n_high: number }>
  unified_score: number
}> {
  const { data } = await api.get('/platforms/unified')
  return data
}

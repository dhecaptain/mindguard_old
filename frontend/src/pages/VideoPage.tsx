import { useState } from 'react'
import { usePlatformStore } from '../store'
import { analyzeVideo } from '../api/analysis'
import LoadingSpinner from '../components/shared/LoadingSpinner'
import SocioEconomicPanel from '../components/analysis/SocioEconomicPanel'
import { getRiskLabel, getClassification, formatPercent, type VideoResult } from '../types'

export default function VideoPage() {
  const [videoUrl, setVideoUrl] = useState('')
  const [error, setError] = useState('')
  const { video, loading, setPlatformResult } = usePlatformStore()

  const handleAnalyze = async () => {
    if (!videoUrl.trim()) return
    setError('')
    try {
      usePlatformStore.getState().setLoading(true)
      setPlatformResult('video', null)
      const result = await analyzeVideo(videoUrl)
      setPlatformResult('video', result)
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }; message?: string }
      setError(error.response?.data?.detail || error.message || 'Video analysis failed')
    } finally {
      usePlatformStore.getState().setLoading(false)
    }
  }

  const videoResult = video as VideoResult | null
  const hasTranscript = Boolean(videoResult?.transcription?.trim())
  const riskInfo = videoResult?.ok && hasTranscript ? getRiskLabel(videoResult.risk) : null
  const classification = videoResult?.ok && hasTranscript ? getClassification(videoResult.risk) : null

  const downloadReport = () => {
    if (!videoResult?.ok) return
    const report = [
      `Video URL: ${videoResult.video_url || videoUrl}`,
      '',
      'Transcript:',
      videoResult.transcription || '',
      '',
      `Risk Score: ${formatPercent(videoResult.risk)}`,
      `Risk Level: ${riskInfo?.label || ''}`,
      `Prediction: ${classification}`,
      `Latency: ${(videoResult.latency_ms || 0).toFixed(0)}ms`,
      `Timestamp: ${new Date().toLocaleString()}`,
    ].join('\n')
    const blob = new Blob([report], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `mindguard-video-report-${Date.now()}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="flex flex-col gap-[16px]">
      <div>
        <h2 className="text-[1.1rem] font-bold text-[#1f2937]">Video Analysis</h2>
        <p className="text-[0.74rem] text-[#6b7280] mt-[6px]">
          Paste any public video URL. Supports TikTok, Facebook, Instagram, Twitter/X, YouTube, Vimeo, Twitch, and many other sites.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[0.85fr_1.2fr] gap-[20px] items-start">
        <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[18px_20px]">
          <div className="text-[0.88rem] font-bold text-[#1f2937] mb-[12px] pb-[12px] border-b border-[#e5e7eb]">
            Source
          </div>
          <div className="text-[0.62rem] font-bold text-[#374151] uppercase tracking-[0.06em] mb-[4px]">Video URL</div>
          <input
            type="text"
            value={videoUrl}
            onChange={(e) => setVideoUrl(e.target.value)}
            placeholder="https://youtube.com/watch?v=..."
            className="w-full bg-[#fafbfc] border-[1.5px] border-[#e5e7eb] rounded-[7px] px-[10px] py-[7px] text-[0.7rem] text-[#4b5563] outline-none focus:border-[#0F766E] mb-[10px]"
          />
          <p className="text-[0.64rem] text-[#6b7280] mb-[8px]">
            Public videos only. First run may download or warm up the Whisper tiny model.
          </p>
          {error && (
            <div className="text-[0.65rem] text-[#dc2626] bg-[#fef2f2] rounded-[6px] px-[10px] py-[7px] mb-[8px] border border-[#fecaca]">
              {error}
            </div>
          )}
          <button
            onClick={handleAnalyze}
            disabled={!videoUrl.trim() || loading}
            className="w-full bg-gradient-to-r from-[#0F766E] to-[#1D9E75] text-white border-none rounded-[7px] py-[7px] text-[0.72rem] font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Transcribing and analysing...' : 'Transcribe and Analyse'}
          </button>
        </div>

        <div className="flex flex-col gap-[14px]">
          {loading ? (
            <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[18px_20px] min-h-[260px] flex items-center justify-center">
              <LoadingSpinner text="Downloading audio, transcribing, then analysing..." />
            </div>
          ) : videoResult?.ok && hasTranscript && riskInfo ? (
            <>
              <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[18px_20px]">
                <div className="text-[0.78rem] font-bold text-[#4b5563] uppercase tracking-[0.05em] mb-[10px]">Transcript</div>
                <div className="text-[0.72rem] text-[#4b5563] leading-[1.65] bg-[#fafbfc] border border-[#e5e7eb] rounded-[8px] px-[12px] py-[10px] max-h-[180px] overflow-y-auto whitespace-pre-wrap">
                  {videoResult.transcription}
                </div>
              </div>

              <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[18px_20px]">
                <div className="text-[0.78rem] font-bold text-[#4b5563] uppercase tracking-[0.05em] mb-[16px]">Prediction</div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-[14px] mb-[18px]">
                  <div>
                    <div className="text-[0.7rem] text-[#4b5563] mb-[4px]">Risk Score</div>
                    <div className="text-[2rem] leading-none font-semibold" style={{ color: riskInfo.color }}>{formatPercent(videoResult.risk)}</div>
                  </div>
                  <div>
                    <div className="text-[0.7rem] text-[#4b5563] mb-[4px]">Risk Level</div>
                    <div className="text-[2rem] leading-none font-semibold" style={{ color: riskInfo.color }}>{riskInfo.label}</div>
                  </div>
                  <div>
                    <div className="text-[0.7rem] text-[#4b5563] mb-[4px]">Latency</div>
                    <div className="text-[2rem] leading-none font-semibold text-[#4b5563]">{(videoResult.latency_ms || 0).toFixed(0)}ms</div>
                  </div>
                </div>

                <div className="flex flex-col items-center py-[6px]">
                  <div className="relative w-[260px] max-w-full h-[145px]">
                    <svg viewBox="0 0 260 145" className="w-full h-full">
                      <path d="M 30 125 A 100 100 0 0 1 230 125" fill="none" stroke="#e5e7eb" strokeWidth="18" />
                      <path
                        d="M 30 125 A 100 100 0 0 1 230 125"
                        fill="none"
                        stroke={riskInfo.color}
                        strokeWidth="18"
                        strokeDasharray={`${Math.max(videoResult.risk, 0.01) * 314} 314`}
                      />
                      <text x="130" y="102" textAnchor="middle" fontSize="24" fontWeight="700" fill="#111827">
                        {formatPercent(videoResult.risk)}
                      </text>
                    </svg>
                    <div className="absolute top-[2px] left-0 right-0 text-center text-[0.72rem] text-[#111827]">
                      {classification}
                    </div>
                  </div>
                </div>

                <div
                  className="mt-[10px] rounded-[8px] px-[12px] py-[10px] text-[0.8rem]"
                  style={{
                    background: videoResult.risk >= 0.55 ? '#fef2f2' : videoResult.risk >= 0.35 ? '#fffbeb' : '#dcfce7',
                    color: videoResult.risk >= 0.55 ? '#991b1b' : videoResult.risk >= 0.35 ? '#92400e' : '#166534',
                  }}
                >
                  {videoResult.risk >= 0.75 ? 'Critical signal - human review recommended.' : videoResult.risk >= 0.55 ? 'High-risk signal - review recommended.' : videoResult.risk >= 0.35 ? 'Moderate risk detected.' : 'Low risk detected.'}
                </div>

                <button
                  onClick={downloadReport}
                  className="mt-[12px] w-full bg-white border border-[#d1d5db] rounded-[8px] py-[9px] text-[0.82rem] text-[#4b5563] font-semibold hover:bg-[#f9fafb] cursor-pointer"
                >
                  Download report
                </button>
              </div>
            </>
          ) : (
            <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[16px_18px] flex flex-col items-center justify-center h-[200px] text-[#c4c9d0] gap-[5px]">
              <i className="ti ti-video text-[22px]" />
              <span className="text-[0.65rem]">Enter a video URL and click Transcribe</span>
            </div>
          )}
        </div>
      </div>

      {videoResult?.ok && hasTranscript && videoResult.signals && (
        <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[16px_18px]">
          <div className="text-[0.78rem] font-bold text-[#1f2937] mb-[10px] pb-[8px] border-b border-[#f1f5f9] flex items-center gap-[6px]">
            <i className="ti ti-chart-pie text-[14px] text-[#0F766E]" />
            Socio-economic signals in transcript
          </div>
          <SocioEconomicPanel signals={videoResult.signals} />
        </div>
      )}
    </div>
  )
}

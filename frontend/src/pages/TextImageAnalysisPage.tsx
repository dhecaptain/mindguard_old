import { useState } from 'react'
import { useAnalysisStore, usePlatformStore } from '../store'
import { analyzeText, analyzeImage } from '../api/analysis'
import InputPanel from '../components/dashboard/InputPanel'
import PredictionPanel from '../components/dashboard/PredictionPanel'
import AnalyticsPanel from '../components/dashboard/AnalyticsPanel'
import type { AnalysisResult } from '../types'
import { getRiskLabel, getClassification } from '../types'

export default function TextImageAnalysisPage() {
  const [error, setError] = useState('')
  const { analytics, lastResult, setLastResult, updateAnalytics } = useAnalysisStore()
  const { setLoading } = usePlatformStore()

  const handleAnalyze = async (text: string) => {
    try {
      setError('')
      setLoading(true)
      const res = await analyzeText({ text })
      const risk = getRiskLabel(res.prob)
      const result: AnalysisResult = {
        prob: res.prob,
        latency_ms: res.latency_ms,
        label: getClassification(res.prob),
        risk_level: res.risk_tier,
        risk_color: risk.color,
        alert_eligible: res.alert_eligible,
        crisis_escalation_eligible: res.crisis_escalation_eligible,
      }
      setLastResult(result)
      updateAnalytics(res.prob, text)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }

  const handleImageUpload = async (file: File) => {
    try {
      setError('')
      setLoading(true)
      const res = await analyzeImage(file)
      const risk = getRiskLabel(res.prob)
      const result: AnalysisResult = {
        prob: res.prob,
        latency_ms: res.latency_ms,
        label: getClassification(res.prob),
        risk_level: res.risk_tier,
        risk_color: risk.color,
        alert_eligible: res.alert_eligible,
        crisis_escalation_eligible: res.crisis_escalation_eligible,
      }
      setLastResult(result)
      updateAnalytics(res.prob, '[Image OCR]')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Image analysis failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-[16px]">
      {error && (
        <div className="text-[0.72rem] text-[#dc2626] bg-[#fef2f2] rounded-[8px] px-[14px] py-[9px] border border-[#fecaca]">
          {error}
        </div>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.2fr_1fr] gap-[16px]">
        <InputPanel onAnalyze={handleAnalyze} onImageUpload={handleImageUpload} />
        <PredictionPanel result={lastResult} />
        <AnalyticsPanel analytics={analytics} />
      </div>
    </div>
  )
}

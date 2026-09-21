import GaugeChart from './GaugeChart'
import type { AnalysisResult } from '../../types'
import { getRiskLabel } from '../../types'

interface PredictionPanelProps {
  result: AnalysisResult | null
}

export default function PredictionPanel({ result }: PredictionPanelProps) {
  if (!result) {
    return (
      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[18px_20px]">
        <div className="text-[0.9rem] font-bold text-[#1f2937] mb-[12px] pb-[10px] border-b border-[#f1f5f9] flex items-center gap-[8px]">
          <i className="ti ti-chart-donut text-[16px] text-[#0F766E]" />
          Prediction
        </div>
        <div className="flex flex-col items-center justify-center h-[240px] text-[#c4c9d0] gap-[8px]">
          <i className="ti ti-chart-donut text-[28px]" />
          <span className="text-[0.82rem]">Enter text and click Analyse to see prediction</span>
        </div>
      </div>
    )
  }

  const isHighRisk = result.alert_eligible
  const riskInfo = getRiskLabel(result.prob)
  const displayConfidence = (2 * Math.abs(result.prob - 0.5) * 100).toFixed(1)

  return (
    <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] p-[18px_20px]">
      <div className="text-[0.9rem] font-bold text-[#1f2937] mb-[12px] pb-[10px] border-b border-[#f1f5f9] flex items-center gap-[8px]">
        <i className="ti ti-chart-donut text-[16px] text-[#0F766E]" />
        Prediction
      </div>

      <GaugeChart prob={result.prob} />

      {/* Risk stats */}
      <div className="grid grid-cols-3 gap-[8px] mt-[12px] w-full">
        <div className="bg-[#fafbfc] rounded-[8px] border-[0.5px] border-[#f1f5f9] p-[8px_10px] text-center">
          <div className="text-[0.95rem] font-bold" style={{ color: isHighRisk ? '#dc2626' : '#0F766E' }}>{displayConfidence}%</div>
          <div className="text-[0.65rem] text-[#9ca3af] font-semibold uppercase tracking-[0.06em] mt-[2px]">Confidence</div>
        </div>
        <div className="bg-[#fafbfc] rounded-[8px] border-[0.5px] border-[#f1f5f9] p-[8px_10px] text-center">
          <div className="text-[0.95rem] font-bold" style={{ color: riskInfo.color }}>{riskInfo.label}</div>
          <div className="text-[0.65rem] text-[#9ca3af] font-semibold uppercase tracking-[0.06em] mt-[2px]">Level</div>
        </div>
        <div className="bg-[#fafbfc] rounded-[8px] border-[0.5px] border-[#f1f5f9] p-[8px_10px] text-center">
          <div className="text-[0.95rem] font-bold text-[#0F766E]">{result.latency_ms.toFixed(0)}ms</div>
          <div className="text-[0.65rem] text-[#9ca3af] font-semibold uppercase tracking-[0.06em] mt-[2px]">Latency</div>
        </div>
      </div>

      {/* Alert */}
      {result.crisis_escalation_eligible && (
        <div className="mt-[10px] bg-[#fef2f2] border-[0.5px] border-[#fecaca] rounded-[8px] p-[10px_12px] text-[0.78rem] text-[#991b1b] font-semibold flex items-center gap-[8px]">
          <i className="ti ti-alert-triangle text-[16px]" />
          Critical signal — human review is recommended
        </div>
      )}
    </div>
  )
}

interface AlertBannerProps {
  score: number
  message?: string
}

export default function AlertBanner({ score, message }: AlertBannerProps) {
  const isRisk = score >= 0.55
  if (!isRisk) return null

  return (
    <div className="bg-[#fef2f2] border-[0.5px] border-[#fecaca] rounded-[7px] p-[7px_10px] text-[0.68rem] text-[#991b1b] font-semibold flex items-center gap-[6px]">
      <i className="ti ti-alert-triangle text-[14px]" />
      {message || 'High-risk signal — human review recommended'}
    </div>
  )
}

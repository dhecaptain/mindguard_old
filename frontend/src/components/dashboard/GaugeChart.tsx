interface GaugeChartProps {
  prob: number
}

export default function GaugeChart({ prob }: GaugeChartProps) {
  const isRisk = prob >= 0.5
  const intensity = 2 * Math.abs(prob - 0.5)
  const displayPct = intensity * 100
  const color = isRisk ? '#dc2626' : '#0F6E56'

  const startX = 12, endX = 148
  const radius = (endX - startX) / 2
  const circumference = Math.PI * radius

  return (
    <div className="flex flex-col items-center">
      <svg className="w-[160px] h-[90px]" viewBox="0 0 160 90">
        {/* Track arc */}
        <path
          d="M 12 84 A 64 64 0 0 1 148 84"
          fill="none"
          stroke="#f1f5f9"
          strokeWidth="12"
          strokeLinecap="round"
        />
        {/* Fill arc - solid color, fills from left by confidence amount */}
        <path
          d="M 12 84 A 64 64 0 0 1 148 84"
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={`${(displayPct / 100) * circumference} ${circumference}`}
        />
        {/* Needle */}
        <line
          x1="80"
          y1="84"
          x2={80 + 62 * Math.cos(Math.PI - (displayPct / 100) * Math.PI)}
          y2={84 - 62 * Math.sin(Math.PI - (displayPct / 100) * Math.PI)}
          stroke={color}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <circle cx="80" cy="84" r="6" fill={color} />
        <text x="80" y="70" textAnchor="middle" fontSize="18" fontWeight="800" fill={color}>
          {displayPct.toFixed(1)}%
        </text>
      </svg>
      <div
        className="mt-[8px] px-[16px] py-[5px] rounded-full text-[0.8rem] font-bold"
        style={{
          background: isRisk ? '#fef2f2' : '#f0fdf4',
          color: isRisk ? '#991b1b' : '#166534',
        }}
      >
        {isRisk ? 'Suicidal signal' : 'Non-Suicidal signal'}
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { useSelfStore } from '../../store/selfStore'
import { platformLabelByKey } from '../../lib/selfPlatformConfig'

function useElapsed(startedAt: number | null, active: boolean) {
  const [ms, setMs] = useState(0)
  useEffect(() => {
    if (!active || startedAt == null) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMs(Date.now() - startedAt)
    const interval = setInterval(() => setMs(Date.now() - startedAt), 500)
    return () => clearInterval(interval)
  }, [startedAt, active])
  return ms
}

function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${s}s`
}

function finalStatusTone(status: string | undefined): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'ok') return 'success'
  if (status === 'error') return 'danger'
  if (status === 'no_data') return 'warning'
  return 'neutral'
}

function finalStatusLabel(status: string | undefined, message?: string): string {
  if (status === 'ok') return 'Analysed'
  if (status === 'error') return message || 'Failed'
  if (status === 'no_data') return message || 'No public posts found'
  return message || status || 'Completed'
}

interface PlatformRowProps {
  slug: string
  label: string
  stepLabel: string
  state: 'pending' | 'running' | 'done'
  finalStatus?: string
  finalMessage?: string
}

function PlatformRow({ label, stepLabel, state, finalStatus, finalMessage }: Omit<PlatformRowProps, 'slug'>) {
  const finalTone = finalStatusTone(finalStatus)
  return (
    <div className="flex items-center gap-[10px] py-[8px]">
      <div className="w-[22px] flex-shrink-0 flex justify-center">
        {state === 'running' ? (
          <div className="w-[15px] h-[15px] border-[2px] border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin" />
        ) : state === 'done' && (finalStatus === 'ok' || !finalStatus) ? (
          <i className="ti ti-circle-check text-[17px] text-[#059669]" />
        ) : state === 'done' && finalStatus === 'no_data' ? (
          <i className="ti ti-hourglass-low text-[17px] text-[#d97706]" />
        ) : state === 'done' ? (
          <i className="ti ti-x-circle text-[17px] text-[#dc2626]" />
        ) : (
          <div className="w-[8px] h-[8px] rounded-full bg-[#d1d5db] self-center" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[0.84rem] font-semibold text-[#1f2937]">{label}</div>
        <div className="text-[0.72rem] text-[#6b7280] truncate">
          {state === 'pending'
            ? 'Queued — the server will process this platform'
            : state === 'running'
              ? stepLabel
              : finalStatusLabel(finalStatus, finalMessage)}
        </div>
      </div>
      {state === 'done' && finalStatus ? (
        <span
          className={`text-[0.66rem] font-bold uppercase tracking-wide px-[7px] py-[2px] rounded-full ${
            finalTone === 'success'
              ? 'bg-[#d1fae5] text-[#065f46]'
              : finalTone === 'danger'
                ? 'bg-[#fee2e2] text-[#991b1b]'
                : finalTone === 'warning'
                  ? 'bg-[#fef3c7] text-[#92400e]'
                  : 'bg-[#f3f4f6] text-[#4b5563]'
          }`}
        >
          {finalStatus === 'ok' ? 'OK' : finalStatus === 'no_data' ? 'No data' : 'Failed'}
        </span>
      ) : null}
    </div>
  )
}

export default function AnalysisRunner() {
  const run = useSelfStore((s) => s.run)
  const error = useSelfStore((s) => s.error)
  const platforms = useSelfStore((s) => s.platforms)
  const runAnalysis = useSelfStore((s) => s.runAnalysis)
  const clearRun = useSelfStore((s) => s.clearRun)
  const clearError = useSelfStore((s) => s.clearError)

  const [retrying, setRetrying] = useState(false)
  const elapsed = useElapsed(run?.startedAt ?? null, Boolean(run?.running))

  if (!run) return null

  const retryTargets = run.status === 'partial' && run.final
    ? run.platforms
      .filter((p) => run.final?.[p.slug]?.status !== 'ok')
      .map((p) => p.slug)
    : run.platforms.map((p) => p.slug)
  const handleRetry = async () => {
    setRetrying(true)
    await runAnalysis(retryTargets)
    setRetrying(false)
  }

  return (
    <div className="bg-white rounded-xl border border-[#e5e7eb] p-[20px]">
      <div className="flex items-center justify-between gap-[10px] mb-[4px]">
        <div className="flex items-center gap-[8px]">
          <div className="text-[0.95rem] font-bold text-[#1f2937]">
            {run.running
              ? 'Running analysis'
              : run.status === 'failed'
                ? 'Analysis failed'
                : run.status === 'partial'
                  ? 'Analysis partially complete'
                  : 'Analysis complete'}
          </div>
          {run.running && (
            <div className="w-[16px] h-[16px] border-[2px] border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin" />
          )}
        </div>
        {run.running && (
          <span className="text-[0.73rem] text-[#6b7280] font-medium tabular-nums">
            Elapsed {formatElapsed(elapsed)}
          </span>
        )}
      </div>

      {run.running ? (
        <div className="text-[0.78rem] text-[#0F766E] font-medium mb-[6px]">{run.phase}</div>
      ) : run.status === 'failed' ? null : run.status === 'partial' ? (
        <div className="text-[0.78rem] text-[#92400e] font-medium mb-[6px]">
          Some connected platforms could not be analysed. Review the per-platform results below.
        </div>
      ) : (
        <div className="text-[0.78rem] text-[#059669] font-medium mb-[6px]">
          Results are ready below.
        </div>
      )}

      <div className="divide-y divide-[#f3f4f6]">
        {run.platforms.map((p) => (
          <PlatformRow
            key={p.slug}
            label={p.label}
            stepLabel={p.stepLabel}
            state={p.status}
            finalStatus={run.final?.[p.slug]?.status}
            finalMessage={run.final?.[p.slug]?.message}
          />
        ))}
      </div>

      {run.status === 'failed' && (
        <div className="mt-[14px] px-[12px] py-[10px] rounded-[8px] bg-[#fef2f2] border border-[#fecaca] text-[0.78rem] text-[#991b1b] leading-relaxed">
          {error || 'The analysis could not be completed. Please try again.'}
          <div className="mt-[8px] flex gap-[8px]">
            <button
              onClick={handleRetry}
              disabled={retrying}
              className="px-[14px] py-[7px] rounded-[8px] bg-[#0F766E] text-white text-[0.78rem] font-semibold disabled:opacity-50 cursor-pointer hover:bg-[#115E59]"
            >
              {retrying ? 'Retrying…' : 'Retry analysis'}
            </button>
            <button
              onClick={() => {
                clearError()
                clearRun()
              }}
              className="px-[14px] py-[7px] rounded-[8px] text-[0.78rem] font-semibold text-[#6b7280] hover:bg-[#f9fafb] cursor-pointer bg-transparent border border-[#d1d5db]"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {!run.running && (run.status === 'complete' || run.status === 'partial') && (
        <div className="mt-[14px] flex gap-[8px]">
          <button
            onClick={handleRetry}
            disabled={retrying}
            className="px-[14px] py-[7px] rounded-[8px] bg-[#0F766E] text-white text-[0.78rem] font-semibold disabled:opacity-50 cursor-pointer hover:bg-[#115E59]"
          >
            {retrying ? 'Re-running…' : `Re-run (${platformLabelByKey(retryTargets[0] ?? '', platforms)}${retryTargets.length > 1 ? ` +${retryTargets.length - 1}` : ''})`}
          </button>
          <button
            onClick={clearRun}
            className="px-[14px] py-[7px] rounded-[8px] text-[0.78rem] font-semibold text-[#6b7280] hover:bg-[#f9fafb] cursor-pointer bg-transparent border border-[#d1d5db]"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  )
}

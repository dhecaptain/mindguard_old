import { useEffect } from 'react'
import { useSelfStore } from '../store/selfStore'
import { useUiStore } from '../store'
import FindingsPanel from '../components/self/FindingsPanel'
import EmptyState from '../components/self/EmptyState'
import SelfStatusBadge, { type BadgeTone } from '../components/self/SelfStatusBadge'
import { formatDateTime, platformLabelByKey } from '../lib/selfPlatformConfig'
import type { AnalysisSession, PlatformProgress } from '../types/self'

const STATUS_TONE: Record<string, BadgeTone> = {
  completed: 'success',
  no_data: 'warning',
  partial: 'warning',
  failed: 'danger',
  running: 'running',
}

const PER_PLATFORM_TONE: Record<string, BadgeTone> = {
  ok: 'success',
  no_data: 'warning',
  error: 'danger',
}

function ProgressRows({ progress }: { progress: AnalysisSession['progress'] }) {
  const platformMap = useSelfStore((s) => s.platforms)
  if (!progress?.platforms) return null
  const entries = Object.entries(progress.platforms)
  if (!entries.length) return null

  return (
    <div className="bg-white rounded-xl border border-[#e5e7eb] p-[16px]">
      <h4 className="text-[0.72rem] uppercase tracking-wide text-[#6b7280] font-bold mb-[8px]">Per-platform status</h4>
      <div className="divide-y divide-[#f3f4f6]">
        {entries.map(([slug, info]: [string, PlatformProgress]) => {
          const display = platformLabelByKey(slug, platformMap)
          const status = info.status || 'ok'
          return (
            <div key={slug} className="flex items-start gap-[10px] py-[8px]">
              <div className="flex-1 min-w-0">
                <div className="text-[0.82rem] text-[#1f2937] font-medium">{display}</div>
                {info.message ? (
                  <div className="text-[0.72rem] text-[#6b7280] leading-relaxed mt-[2px]">{info.message}</div>
                ) : null}
              </div>
              <SelfStatusBadge tone={PER_PLATFORM_TONE[status] || 'neutral'}>
                {status === 'ok' ? 'Completed' : status === 'no_data' ? 'No data' : status === 'error' ? 'Failed' : status}
              </SelfStatusBadge>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function AnalysisSessionPage() {
  const session = useSelfStore((s) => s.selectedSession)
  const loadCatalog = useSelfStore((s) => s.loadCatalog)
  const clearSelectedSession = useSelfStore((s) => s.clearSelectedSession)
  const { setPage } = useUiStore()

  useEffect(() => {
    loadCatalog()
  }, [loadCatalog])

  if (!session) {
    return (
      <div className="flex flex-col gap-[16px]">
        <button
          onClick={() => { clearSelectedSession(); setPage('self-history') }}
          className="text-[0.82rem] font-semibold text-[#0F766E] hover:text-[#115E59] cursor-pointer bg-transparent border-none text-left"
        >
          ← Back to history
        </button>
        <EmptyState
          icon="ti ti-alert-circle"
          title="No session selected"
          body="Select an analysis session from your history to view the full report."
          action={
            <button
              onClick={() => setPage('self-history')}
              className="px-[16px] py-[9px] rounded-[8px] bg-[#0F766E] text-white text-[0.85rem] font-semibold cursor-pointer hover:bg-[#115E59]"
            >
              View history
            </button>
          }
        />
      </div>
    )
  }

  const platforms = useSelfStore.getState().platforms
  const statusTone = STATUS_TONE[session.status] || 'neutral'
  const platformNames = session.platforms?.length
    ? session.platforms.map((p) => platformLabelByKey(p, platforms)).join(', ')
    : '—'

  return (
    <div className="flex flex-col gap-[12px]">
      <button
        onClick={() => { clearSelectedSession(); setPage('self-history') }}
        className="text-[0.82rem] font-semibold text-[#0F766E] hover:text-[#115E59] cursor-pointer bg-transparent border-none text-left"
      >
        ← Back to history
      </button>

      <div className="bg-white rounded-xl border border-[#e5e7eb] px-[16px] py-[12px]">
        <div className="flex items-start justify-between gap-[10px]">
          <div>
            <h1 className="text-[1.05rem] font-bold text-[#1f2937]">Analysis session</h1>
            <p className="text-[0.78rem] text-[#6b7280] mt-[2px]">
              This is a historical report — not a live re-run.
            </p>
          </div>
          <SelfStatusBadge tone={statusTone} pulse={session.status === 'running'}>
            {session.status === 'no_data' ? 'No public posts' : session.status}
          </SelfStatusBadge>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-[10px] mt-[12px]">
          <div>
            <div className="text-[0.65rem] uppercase tracking-wide text-[#6b7280] font-bold">Started</div>
            <div className="text-[0.82rem] text-[#1f2937] mt-[2px]">{formatDateTime(session.started_at)}</div>
          </div>
          <div>
            <div className="text-[0.65rem] uppercase tracking-wide text-[#6b7280] font-bold">Completed</div>
            <div className="text-[0.82rem] text-[#1f2937] mt-[2px]">{formatDateTime(session.completed_at)}</div>
          </div>
          <div className="sm:col-span-2">
            <div className="text-[0.65rem] uppercase tracking-wide text-[#6b7280] font-bold">Platforms</div>
            <div className="text-[0.82rem] text-[#1f2937] mt-[2px] truncate" title={platformNames}>{platformNames}</div>
          </div>
        </div>
      </div>

      <FindingsPanel session={session} />

      <ProgressRows progress={session.progress} />

      {session.status === 'no_data' && (
        <div className="bg-[#fffbeb] rounded-xl border border-[#fde68a] p-[16px]">
          <h4 className="text-[0.82rem] font-bold text-[#92400e] mb-[4px]">Why no data?</h4>
          <p className="text-[0.78rem] text-[#92400e] leading-relaxed">
            We checked the connected platforms for publicly available content but didn't find any posts
            to analyse. This can happen when a profile is private, has no recent posts, or when the
            platform's data source is unavailable. Connect a different account with public activity,
            or check that your credentials are correct, and re-run the analysis.
          </p>
        </div>
      )}

      {session.status === 'partial' && (
        <div className="bg-[#f8fafc] rounded-xl border border-[#e5e7eb] p-[16px] text-[0.78rem] text-[#6b7280] leading-relaxed">
          Some platforms failed to load. The report shows results for the platforms that succeeded. 
          Failed platforms will show as red in the per-platform status above.
        </div>
      )}

      {session.insights?.length ? (
        <div className="bg-white rounded-xl border border-[#e5e7eb] p-[16px]">
          <h4 className="text-[0.95rem] font-bold text-[#1f2937] mb-[8px]">Insights</h4>
          <ul className="flex flex-col gap-[6px]">
            {session.insights.map((insight, i) => (
              <li key={i} className="text-[0.82rem] text-[#1f2937] leading-snug flex items-start gap-[8px]">
                <i className="ti ti-point-filled text-[10px] mt-[5px] text-[#0F766E] flex-shrink-0" />
                <span>{insight}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {session.recommendations?.length ? (
        <div className="bg-white rounded-xl border border-[#e5e7eb] p-[16px]">
          <h4 className="text-[0.95rem] font-bold text-[#1f2937] mb-[8px]">Recommended next steps</h4>
          <ul className="flex flex-col gap-[8px]">
            {session.recommendations.map((rec, i) => (
              <li key={i} className="text-[0.82rem] text-[#1f2937] leading-snug flex items-start gap-[8px]">
                <i className="ti ti-arrow-right-circle text-[15px] mt-[1px] text-[#0F766E] flex-shrink-0" />
                <span>{rec}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="bg-[#f8fafc] rounded-xl border border-[#e5e7eb] px-[16px] py-[10px] text-[0.72rem] text-[#6b7280] leading-relaxed flex items-start gap-[8px]">
        <i className="ti ti-info-circle text-[14px] text-[#6b7280] mt-[1px] flex-shrink-0" />
        <span>
          This is a historical snapshot of your analysis. To get updated results, go to your dashboard
          and run a new analysis.
        </span>
      </div>
    </div>
  )
}

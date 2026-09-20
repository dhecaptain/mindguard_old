import { useEffect, useMemo } from 'react'
import { useSelfStore } from '../store/selfStore'
import { useUiStore } from '../store'
import AnalysisRunner from '../components/self/AnalysisRunner'
import FindingsPanel from '../components/self/FindingsPanel'
import SessionCard from '../components/self/SessionCard'
import EmptyState from '../components/self/EmptyState'
import SelfStatusBadge from '../components/self/SelfStatusBadge'
import { accountStage, stageMeta, riskLevelTone } from '../lib/selfPlatformConfig'

const TONE_CLASSES: Record<string, string> = {
  success: 'bg-[#d1fae5] text-[#065f46]',
  warning: 'bg-[#fef3c7] text-[#92400e]',
  danger: 'bg-[#fee2e2] text-[#991b1b]',
  critical: 'bg-[#fecaca] text-[#7f1d1d]',
  neutral: 'bg-[#f3f4f6] text-[#4b5563]',
  info: 'bg-[#e0f2fe] text-[#075985]',
}

export default function AdultDashboardPage() {
  const { setPage } = useUiStore()
  const platforms = useSelfStore((s) => s.platforms)
  const accounts = useSelfStore((s) => s.accounts)
  const sessions = useSelfStore((s) => s.sessions)
  const run = useSelfStore((s) => s.run)
  const error = useSelfStore((s) => s.error)
  const catalogLoaded = useSelfStore((s) => s.catalogLoaded)
  const loadCatalog = useSelfStore((s) => s.loadCatalog)
  const runAnalysis = useSelfStore((s) => s.runAnalysis)
  const openSession = useSelfStore((s) => s.openSession)
  const clearError = useSelfStore((s) => s.clearError)

  useEffect(() => {
    if (!catalogLoaded) loadCatalog()
  }, [catalogLoaded, loadCatalog])

  const latestSession = useMemo(
    // The API orders durable sessions newest first. Always show the latest
    // run, including no_data/partial/failed outcomes, rather than hiding a
    // recent unsuccessful run behind an older successful report.
    () => sessions[0] || null,
    [sessions],
  )

  const flaggedCount = useMemo(() => {
    if (!latestSession?.findings?.platforms?.length) return latestSession?.findings?.top_posts?.length || 0
    return latestSession.findings.platforms.reduce(
      (sum, p) => sum + (p.distribution?.high || 0) + (p.distribution?.critical || 0),
      0,
    )
  }, [latestSession])

  const overall = latestSession?.findings ? riskLevelTone(latestSession.findings.overall_level) : null

  const handleRun = async () => {
    await runAnalysis()
  }

  return (
    <div className="flex flex-col gap-[16px]">
      <div className="flex items-start justify-between gap-[10px]">
        <div>
          <h1 className="text-[1.25rem] font-bold text-[#1f2937]">Your digital wellbeing</h1>
          <p className="text-[0.82rem] text-[#6b7280] mt-[3px] leading-relaxed">
            Connected accounts and social content analysis you own.
          </p>
        </div>
        <div className="flex items-center gap-[8px] flex-shrink-0">
          {accounts.length > 0 && !run?.running && (
            <button
              onClick={handleRun}
              className="px-[14px] py-[8px] rounded-[8px] bg-[#0F766E] text-white text-[0.82rem] font-semibold cursor-pointer hover:bg-[#115E59] disabled:opacity-50"
              disabled={accounts.length === 0}
            >
              Run analysis
            </button>
          )}
          <button
            onClick={() => setPage('my-accounts')}
            className="px-[14px] py-[8px] rounded-[8px] text-[0.82rem] font-semibold text-[#0F766E] hover:bg-[#f0fdfa] cursor-pointer bg-transparent border border-[#0F766E]"
          >
            Manage accounts
          </button>
        </div>
      </div>

      {error && (
        <div className="px-[14px] py-[10px] rounded-[8px] bg-[#fef2f2] border border-[#fecaca] text-[0.8rem] text-[#991b1b] flex items-center justify-between">
          <span>{error}</span>
          <button onClick={clearError} className="text-[0.78rem] font-semibold underline cursor-pointer bg-transparent border-none text-[#991b1b] hover:text-[#dc2626]">Dismiss</button>
        </div>
      )}

      {run?.running && <AnalysisRunner />}

      {!catalogLoaded ? (
        <div className="bg-white rounded-xl border border-[#e5e7eb] p-[32px] flex items-center gap-[10px] text-[0.85rem] text-[#6b7280]">
          <div className="w-[18px] h-[18px] border-[2px] border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin" />
          Loading account data…
        </div>
      ) : accounts.length === 0 ? (
        <EmptyState
          icon="ti ti-link"
          title="Connect your social accounts"
          body="Start by connecting your Reddit, Bluesky, YouTube, or other social accounts. We'll fetch your public content and analyse it for indicators of mental health risk — privately, with results you control."
          action={
            <button
              onClick={() => setPage('my-accounts')}
              className="px-[16px] py-[9px] rounded-[8px] bg-[#0F766E] text-white text-[0.85rem] font-semibold cursor-pointer hover:bg-[#115E59]"
            >
              Connect your first account
            </button>
          }
        />
      ) : !latestSession ? (
        <div className="bg-white rounded-xl border border-[#e5e7eb] p-[20px] flex flex-col gap-[14px]">
          <div>
            <h3 className="text-[1rem] font-bold text-[#1f2937] mb-[4px]">No analysis yet</h3>
            <p className="text-[0.82rem] text-[#6b7280] leading-relaxed">
              {accounts.length} account{accounts.length === 1 ? '' : 's'} connected. Run your first analysis to
              see how MindGuard evaluates your public content.
            </p>
          </div>
          <div className="flex gap-[8px]">
            <button
              onClick={handleRun}
              disabled={run?.running}
              className="px-[16px] py-[9px] rounded-[8px] bg-[#0F766E] text-white text-[0.85rem] font-semibold disabled:opacity-50 cursor-pointer hover:bg-[#115E59]"
            >
              {run?.running ? 'Analysing…' : 'Run analysis'}
            </button>
            <button
              onClick={() => setPage('my-accounts')}
              className="px-[16px] py-[9px] rounded-[8px] text-[0.85rem] font-semibold text-[#6b7280] border border-[#d1d5db] cursor-pointer hover:bg-[#f9fafb] bg-transparent"
            >
              Manage accounts
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-[10px]">
            <div className="bg-white rounded-xl border border-[#e5e7eb] p-[14px]">
              <div className="text-[0.65rem] uppercase tracking-wide text-[#6b7280] font-bold">Platforms analysed</div>
              <div className="text-[1.1rem] font-bold text-[#1f2937] mt-[4px]">
                {latestSession.findings?.platforms_analyzed?.length || latestSession.platforms?.length || 0}
              </div>
            </div>
            <div className="bg-white rounded-xl border border-[#e5e7eb] p-[14px]">
              <div className="text-[0.65rem] uppercase tracking-wide text-[#6b7280] font-bold">Posts analysed</div>
              <div className="text-[1.1rem] font-bold text-[#1f2937] mt-[4px]">
                {latestSession.findings?.posts_analyzed ?? '—'}
              </div>
            </div>
            <div className="bg-white rounded-xl border border-[#e5e7eb] p-[14px]">
              <div className="text-[0.65rem] uppercase tracking-wide text-[#6b7280] font-bold">Flagged posts</div>
              <div className="text-[1.1rem] font-bold text-[#1f2937] mt-[4px]">{flaggedCount}</div>
            </div>
            <div className="bg-white rounded-xl border border-[#e5e7eb] p-[14px]">
              <div className="text-[0.65rem] uppercase tracking-wide text-[#6b7280] font-bold">Wellbeing level</div>
              <div className="mt-[4px]">
                {overall ? (
                  <SelfStatusBadge tone={overall.tone}>{overall.label}</SelfStatusBadge>
                ) : (
                  <span className="text-[0.82rem] text-[#9ca3af]">—</span>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-[12px] items-start">
            <FindingsPanel session={latestSession} />

            <div className="flex flex-col gap-[12px]">
              <div className="bg-white rounded-xl border border-[#e5e7eb] p-[16px]">
                <h4 className="text-[0.72rem] uppercase tracking-wide text-[#6b7280] font-bold mb-[10px]">Connected accounts</h4>
                <div className="flex flex-col gap-[8px]">
                  {accounts.map((account) => {
                    const spec = platforms?.find((p) => p.key === account.platform)
                    if (!spec) return null
                    const stage = accountStage(account)
                    const meta = stageMeta(stage)
                    return (
                      <div key={account.platform} className="flex items-center gap-[8px]">
                        <i className={`${spec.icon} text-[15px] text-[#0F766E] w-[18px] text-center`} />
                        <span className="text-[0.78rem] font-medium text-[#1f2937] flex-1 truncate">{spec.display_name}</span>
                        <span
                          className={`text-[0.64rem] font-bold uppercase tracking-wide px-[6px] py-[1px] rounded-full ${TONE_CLASSES[meta.tone] || TONE_CLASSES.neutral}`}
                        >
                          {meta.label}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>

              {latestSession.recommendations?.length ? (
                <div className="bg-white rounded-xl border border-[#e5e7eb] p-[16px]">
                  <h4 className="text-[0.72rem] uppercase tracking-wide text-[#6b7280] font-bold mb-[8px]">Recommended next steps</h4>
                  <ul className="flex flex-col gap-[8px]">
                    {latestSession.recommendations.slice(0, 3).map((rec, i) => (
                      <li key={i} className="text-[0.78rem] text-[#1f2937] leading-snug flex items-start gap-[6px]">
                        <i className="ti ti-arrow-right-circle text-[14px] mt-[1px] text-[#0F766E] flex-shrink-0" />
                        <span>{rec}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </div>

          {sessions.length > 1 ? (
            <div>
              <div className="flex items-center justify-between mb-[10px]">
                <h3 className="text-[0.95rem] font-bold text-[#1f2937]">Recent analysis</h3>
                <button
                  onClick={() => setPage('self-history')}
                  className="text-[0.78rem] font-semibold text-[#0F766E] hover:text-[#115E59] cursor-pointer bg-transparent border-none"
                >
                  View all history →
                </button>
              </div>
              <div className="flex flex-col gap-[8px]">
                {sessions.slice(1, 4).map((session) => (
                  <SessionCard key={session.id} session={session} onOpen={(id) => { openSession(id); setPage('self-session') }} />
                ))}
              </div>
            </div>
          ) : null}

          <div className="bg-[#f8fafc] rounded-xl border border-[#e5e7eb] px-[16px] py-[10px] text-[0.72rem] text-[#6b7280] leading-relaxed flex items-start gap-[8px]">
            <i className="ti ti-shield-check text-[14px] text-[#0F766E] mt-[1px] flex-shrink-0" />
            <span>
              Only accounts you own or are authorised to manage can be analysed. We retrieve only content the platform already makes public; nothing is posted or shared.
            </span>
          </div>
        </>
      )}
    </div>
  )
}

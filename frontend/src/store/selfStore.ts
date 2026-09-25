import { create } from 'zustand'
import * as selfApi from '../api/self'
import type {
  AddAccountPayload,
  AnalysisSession,
  PlatformSpec,
  SelfSocialAccount,
  VerifyResult,
} from '../types/self'

export interface PlatformRunState {
  slug: string
  label: string
  stepLabel: string
  status: 'pending' | 'running' | 'done'
}

export interface RunState {
  id: string
  running: boolean
  phase: string
  platforms: PlatformRunState[]
  startedAt: number
  status: 'complete' | 'partial' | 'failed'
  final: Record<string, { status?: string; message?: string }> | null
}

function messageFromError(e: unknown): string {
  if (typeof e === 'object' && e !== null && 'response' in e) {
    const payload = (e as { response?: { data?: { detail?: { message?: string }; message?: string } } })
      .response?.data
    return payload?.detail?.message || payload?.message || 'Analysis failed. Please try again.'
  }
  return 'Analysis failed. Please try again.'
}

interface SelfState {
  platforms: PlatformSpec[] | null
  accounts: SelfSocialAccount[]
  sessions: AnalysisSession[]
  sessionsTotal: number
  catalogLoaded: boolean
  selectedSession: AnalysisSession | null
  run: RunState | null
  error: string | null
  busy: Record<string, boolean>
  verificationCodes: Record<string, string>
  loadCatalog: () => Promise<void>
  addAccount: (payload: AddAccountPayload) => Promise<void>
  removeAccount: (platform: string) => Promise<void>
  verifyAccount: (platform: string, verificationCode?: string) => Promise<VerifyResult | null>
  getVerificationCode: (platform: string) => Promise<string | null>
  runAnalysis: (targets?: string[]) => Promise<AnalysisSession | null>
  openSession: (id: string) => Promise<AnalysisSession | null>
  clearError: () => void
  clearRun: () => void
  clearSelectedSession: () => void
}

export const useSelfStore = create<SelfState>((set, get) => {
  async function refreshAccounts(): Promise<void> {
    const [accounts, platforms] = await Promise.all([
      selfApi.getSocialAccounts(),
      selfApi.getSelfPlatforms(),
    ])
    set({ accounts, platforms })
  }

  async function refreshSessions(): Promise<void> {
    const { sessions, total } = await selfApi.getAnalysisSessions()
    set({ sessions, sessionsTotal: total })
  }

  return {
    platforms: null,
    accounts: [],
    sessions: [],
    sessionsTotal: 0,
    catalogLoaded: false,
    selectedSession: null,
    run: null,
    error: null,
    busy: {},
    verificationCodes: {},

    loadCatalog: async () => {
      try {
        const [accounts, platforms, sessions] = await Promise.all([
          selfApi.getSocialAccounts(),
          selfApi.getSelfPlatforms(),
          selfApi.getAnalysisSessions(),
        ])
        set({
          accounts,
          platforms,
          sessions: sessions.sessions,
          sessionsTotal: sessions.total,
          catalogLoaded: true,
          error: null,
        })
      } catch (e) {
        set({ catalogLoaded: true, error: messageFromError(e) })
      }
    },

    addAccount: async (payload) => {
      set({ busy: { ...get().busy, [payload.platform]: true }, error: null })
      try {
        const result = await selfApi.addSocialAccount(payload)
        if (result.verification_code) {
          set({ verificationCodes: { ...get().verificationCodes, [payload.platform]: result.verification_code } })
        }
        await refreshAccounts()
      } catch (e) {
        set({ error: messageFromError(e) })
        throw e
      } finally {
        set({ busy: { ...get().busy, [payload.platform]: false } })
      }
    },

    removeAccount: async (platform) => {
      set({ busy: { ...get().busy, [platform]: true }, error: null })
      try {
        await selfApi.deleteSocialAccount(platform)
        await refreshAccounts()
      } catch (e) {
        set({ error: messageFromError(e) })
        throw e
      } finally {
        set({ busy: { ...get().busy, [platform]: false } })
      }
    },

    verifyAccount: async (platform, verificationCode) => {
      set({ busy: { ...get().busy, [platform]: true }, error: null })
      try {
        const code = verificationCode || get().verificationCodes[platform]
        if (!code) {
          set({ error: `Get a new verification code for ${platform} first, add it to the public profile bio/about section, then verify.` })
          return null
        }
        const result = await selfApi.verifySocialAccount(platform, code)
        const nextCodes = { ...get().verificationCodes }
        delete nextCodes[platform]
        set({ verificationCodes: nextCodes })
        await refreshAccounts()
        return result
      } catch (e) {
        set({ error: messageFromError(e) })
        return null
      } finally {
        set({ busy: { ...get().busy, [platform]: false } })
      }
    },

    getVerificationCode: async (platform) => {
      set({ busy: { ...get().busy, [platform]: true }, error: null })
      try {
        const result = await selfApi.rotateSocialAccountCode(platform)
        set({ verificationCodes: { ...get().verificationCodes, [platform]: result.verification_code } })
        return result.verification_code
      } catch (e) {
        set({ error: messageFromError(e) })
        return null
      } finally {
        set({ busy: { ...get().busy, [platform]: false } })
      }
    },

    runAnalysis: async (targets) => {
      const state = get()
      if (state.run?.running) return null

      const slugToSpec = new Map(
        (state.platforms || []).map((p) => [p.key, p] as const),
      )
      const targetsSet =
        targets && targets.length
          ? new Set(targets)
          : new Set(state.accounts.map((a) => a.platform))
      const runPlatforms: PlatformRunState[] = [...targetsSet].map((slug) => {
        const spec = slugToSpec.get(slug)
        return {
          slug,
          label: spec?.display_name || slug,
          stepLabel: spec?.analyze_step_label || `Fetching ${slug}`,
          status: 'pending' as const,
        }
      })

      if (!runPlatforms.length) {
        set({
          error:
            runPlatforms.length === 0
              ? 'Connect at least one account before running analysis.'
              : null,
        })
        return null
      }

      const runId = `run-${Date.now()}`
      const startedAt = Date.now()
      set({
        run: {
          id: runId,
          running: true,
          phase: 'Preparing analysis…',
          platforms: runPlatforms,
          startedAt,
          status: 'complete',
          final: null,
        },
        error: null,
      })

      const setPhase = (phase: string): void => {
        const current = get().run
        if (current?.id === runId) set({ run: { ...current, phase } })
      }
      // The API currently returns one completed session and does not expose
      // streaming progress. Keep the UI honest instead of simulating stages
      // that have not happened yet.
      setPhase('Fetching and analysing your connected platforms…')

      try {
        const res =
          targetsSet.size === 1
            ? await selfApi.analyzeSelfPlatform([...targetsSet][0])
            : await selfApi.analyzeSelfAll()
        const session = res.session
        await Promise.all([refreshAccounts(), refreshSessions()])
        const current = get().run
        if (current?.id === runId) {
          const terminalStatus = session.status === 'failed'
            ? 'failed'
            : session.status === 'partial'
              ? 'partial'
              : 'complete'
          set({
            run: {
              ...current,
              running: false,
              status: terminalStatus,
              phase: terminalStatus === 'failed'
                ? 'Analysis failed'
                : terminalStatus === 'partial'
                  ? 'Analysis partially complete'
                  : 'Analysis complete',
              platforms: current.platforms.map((p) => ({ ...p, status: 'done' })),
              final: session.progress?.platforms ?? null,
            },
          })
        }
        return session
      } catch (e) {
        await Promise.all([refreshAccounts(), refreshSessions()])
        const current = get().run
        if (current?.id === runId) {
          set({
            run: {
              ...current,
              running: false,
              status: 'failed',
              phase: 'Analysis failed',
              final: null,
            },
            error: messageFromError(e),
          })
        }
        return null
      }
    },

    openSession: async (id) => {
      try {
        const { session } = await selfApi.getAnalysisSession(id)
        set({ selectedSession: session, error: null })
        return session
      } catch (e) {
        set({ error: messageFromError(e) })
        return null
      }
    },

    clearError: () => set({ error: null }),
    clearRun: () => set({ run: null }),
    clearSelectedSession: () => set({ selectedSession: null }),
  }
})

import type { PlatformSpec, SelfSocialAccount } from '../../types/self'
import {
  accountStage,
  canAnalyze,
  credentialNote,
  stageMeta,
} from '../../lib/selfPlatformConfig'
import SelfStatusBadge, { type BadgeTone } from './SelfStatusBadge'

interface Props {
  spec: PlatformSpec
  account: SelfSocialAccount | undefined
  busy: boolean
  verificationCode?: string
  runningPlatforms: ReadonlySet<string>
  onVerify: (slug: string) => void
  onGetCode: (slug: string) => void
  onRequestConsent: (slug: string) => void
  onAnalyse: (slug: string) => void
  onRemove: (slug: string) => void
}

const TONE_MAP: Record<string, BadgeTone> = {
  success: 'success',
  warning: 'warning',
  danger: 'danger',
  info: 'info',
  neutral: 'neutral',
  critical: 'critical',
  running: 'running',
}

export default function AccountCard({
  spec,
  account,
  busy,
  verificationCode,
  runningPlatforms,
  onVerify,
  onGetCode,
  onRequestConsent,
  onAnalyse,
  onRemove,
}: Props) {
  const stage = accountStage(account, runningPlatforms)
  const meta = stageMeta(stage)
  const readiness = canAnalyze(spec, account)
  const credential = credentialNote(spec, account)

  const identity = spec.verified_handle || account?.handle || spec.verified_profile_url || account?.profile_url

  return (
    <div className="bg-white rounded-xl border border-[#e5e7eb] p-[16px] flex flex-col gap-[10px]">
      <div className="flex items-start justify-between gap-[8px]">
        <div className="flex items-center gap-[10px] min-w-0">
          <div className="w-[36px] h-[36px] rounded-lg bg-[#f0fdfa] flex items-center justify-center flex-shrink-0">
            <i className={`${spec.icon} text-[18px] text-[#0F766E]`} />
          </div>
          <div className="min-w-0">
            <div className="text-[0.88rem] font-bold text-[#1f2937]">{spec.display_name}</div>
            <div className="text-[0.73rem] text-[#6b7280] truncate">
              {stage === 'not_connected'
                ? 'Not connected'
                : identity || (account?.has_credentials ? 'Credentials configured' : 'Connected')}
            </div>
          </div>
        </div>
        <SelfStatusBadge tone={TONE_MAP[meta.tone]} pulse={stage === 'running'}>
          {meta.label}
        </SelfStatusBadge>
      </div>

      <div className="text-[0.75rem] text-[#6b7280] leading-relaxed">{spec.blurb}</div>

      {credential && !account && (
        <div className="px-[10px] py-[7px] rounded-[8px] bg-[#fffbeb] border border-[#fde68a] text-[0.73rem] text-[#92400e] leading-relaxed">
          {credential}
        </div>
      )}
      {credential && account && (
        <div className="px-[10px] py-[7px] rounded-[8px] bg-[#f8fafc] border border-[#e5e7eb] text-[0.73rem] text-[#6b7280] leading-relaxed">
          {credential}
        </div>
      )}

      {account && !spec.consented && (
        <div className="px-[10px] py-[8px] rounded-[8px] bg-[#fffbeb] border border-[#fde68a] text-[0.73rem] text-[#92400e] leading-relaxed">
          This account is connected, but {spec.display_name} is not covered by the current consent. Request platform consent before your counsellor can use it.
          {!spec.consent_pending && (
            <button
              type="button"
              onClick={() => onRequestConsent(spec.key)}
              disabled={busy}
              className="mt-[7px] block text-[#0F766E] font-semibold hover:underline disabled:opacity-50"
            >
              Request {spec.display_name} consent
            </button>
          )}
          {spec.consent_pending && <div className="mt-[5px] text-[#92400e]">Consent request pending — check the student or guardian email.</div>}
        </div>
      )}

      {account && account.verification_status === 'pending' && verificationCode ? (
        <div className="px-[10px] py-[8px] rounded-[8px] bg-[#eff6ff] border border-[#bfdbfe] text-[0.73rem] text-[#1e3a5f] leading-relaxed">
          Add this one-time code to the public bio/about section, then select Verify ownership: <code className="font-bold">{verificationCode}</code>
        </div>
      ) : null}

      {!spec.analyzable && (
        <div className="px-[10px] py-[7px] rounded-[8px] bg-[#f3f4f6] text-[0.73rem] text-[#4b5563] leading-relaxed">
          Read-only platform — MindGuard does not analyse public content on {spec.display_name}.
        </div>
      )}

      <div className="flex items-center gap-[8px] flex-wrap pt-[2px]">
        {account && account.verification_status === 'pending' && spec.analyzable ? (
          <>
            <button
              onClick={() => onGetCode(spec.key)}
              disabled={busy}
              className="px-[12px] py-[7px] rounded-[8px] border border-[#0F766E] text-[#0F766E] text-[0.78rem] font-semibold disabled:opacity-50 cursor-pointer hover:bg-[#f0fdfa]"
            >
              {busy ? 'Preparing…' : 'Get a new code'}
            </button>
            <button
              onClick={() => onVerify(spec.key)}
              disabled={busy}
              className="px-[12px] py-[7px] rounded-[8px] bg-[#0F766E] text-white text-[0.78rem] font-semibold disabled:opacity-50 cursor-pointer hover:bg-[#115E59]"
            >
              {busy ? 'Verifying…' : 'Verify ownership'}
            </button>
          </>
        ) : null}

        {readiness.ready && spec.analyzable && (
          <button
            onClick={() => onAnalyse(spec.key)}
            disabled={busy || stage === 'running'}
            className="px-[12px] py-[7px] rounded-[8px] bg-[#0F766E] text-white text-[0.78rem] font-semibold disabled:opacity-50 cursor-pointer hover:bg-[#115E59]"
          >
            {busy ? 'Working…' : stage === 'running' ? 'Analysing…' : account?.analysis_status === 'completed' ? 'Re-analyse' : 'Analyse'}
          </button>
        )}

        {account ? (
          <button
            onClick={() => onRemove(spec.key)}
            disabled={busy}
            className="px-[12px] py-[7px] rounded-[8px] text-[0.78rem] font-semibold text-[#dc2626] hover:bg-[#fef2f2] disabled:opacity-50 cursor-pointer bg-transparent border border-[#fecaca]"
          >
            Remove
          </button>
        ) : null}
      </div>
    </div>
  )
}

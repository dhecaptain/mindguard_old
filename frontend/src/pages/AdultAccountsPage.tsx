import { useEffect, useMemo, useState } from 'react'
import { useSelfStore } from '../store/selfStore'
import AccountCard from '../components/self/AccountCard'
import EmptyState from '../components/self/EmptyState'
import { handleField, credentialFields } from '../lib/selfPlatformConfig'
import type { PlatformSpec } from '../types/self'

export default function AdultAccountsPage() {
  const platforms = useSelfStore((s) => s.platforms)
  const accounts = useSelfStore((s) => s.accounts)
  const busy = useSelfStore((s) => s.busy)
  const run = useSelfStore((s) => s.run)
  const catalogLoaded = useSelfStore((s) => s.catalogLoaded)
  const loadCatalog = useSelfStore((s) => s.loadCatalog)
  const addAccount = useSelfStore((s) => s.addAccount)
  const removeAccount = useSelfStore((s) => s.removeAccount)
  const verifyAccount = useSelfStore((s) => s.verifyAccount)
  const getVerificationCode = useSelfStore((s) => s.getVerificationCode)
  const requestPlatformConsent = useSelfStore((s) => s.requestPlatformConsent)
  const verificationCodes = useSelfStore((s) => s.verificationCodes)
  const error = useSelfStore((s) => s.error)
  const runAnalysis = useSelfStore((s) => s.runAnalysis)

  const [selectedPlatform, setSelectedPlatform] = useState<string | null>(null)
  const [handleValue, setHandleValue] = useState('')
  const [credentialValues, setCredentialValues] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [consentNotice, setConsentNotice] = useState<string | null>(null)
  const [verificationNotice, setVerificationNotice] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    if (!catalogLoaded) loadCatalog()
  }, [catalogLoaded, loadCatalog])

  const accountMap = useMemo(() => {
    const map = new Map<string, typeof accounts[0]>()
    for (const a of accounts) map.set(a.platform, a)
    return map
  }, [accounts])

  const runningPlatforms = useMemo(() => new Set(run?.platforms?.filter(p => p.status === 'running').map(p => p.slug) || []), [run])

  const spec: PlatformSpec | null = useMemo(() => {
    if (!selectedPlatform || !platforms) return null
    return platforms.find((p) => p.key === selectedPlatform) || null
  }, [selectedPlatform, platforms])

  const specHandle = spec ? handleField(spec) : null
  const specCreds = spec ? credentialFields(spec) : []
  const isUrlOnly = spec?.required_input === 'url'

  const clearForm = () => {
    setHandleValue('')
    setCredentialValues({})
    setFormError(null)
  }

  const handleVerify = async (platform: string, code?: string) => {
    setVerificationNotice(null)
    const result = await verifyAccount(platform, code)
    if (result?.verified) {
      setVerificationNotice({ tone: 'success', text: result.message || `${platform} ownership verified successfully. The account is ready for counsellor review.` })
      return
    }
    const latestError = useSelfStore.getState().error
    setVerificationNotice({ tone: 'error', text: latestError || `We couldn't verify ${platform}. Check that the current code appears in the public profile bio/about, then try again.` })
  }

  const handleAdd = async () => {
    setFormError(null)
    if (!spec) return

    if (!spec.consented) {
      setFormError(`Consent for ${spec.display_name} is required before this account can be connected.`)
      return
    }

    const handle = isUrlOnly ? undefined : handleValue.trim()
    const profileUrl = isUrlOnly ? handleValue.trim() : undefined

    if (!handle && !profileUrl) {
      setFormError(`Please enter your ${spec.handle_label}.`)
      return
    }

    // Basic validation hints
    if (spec.key === 'facebook' && profileUrl && !profileUrl.startsWith('http')) {
      setFormError('Please enter a full Facebook profile URL starting with https://')
      return
    }

    // Check credentials
    for (const cred of specCreds) {
      if (cred.serverKey) continue
      if (cred.required && !credentialValues[cred.name]?.trim()) {
        setFormError(`${cred.label} is required — ${cred.hint || 'see instructions below'}`)
        return
      }
    }

    setAdding(true)
    try {
      const credentials: Record<string, string> = {}
      for (const cred of specCreds) {
        if (cred.name && credentialValues[cred.name]) {
          credentials[cred.name] = credentialValues[cred.name]
        }
      }

      await addAccount({
        platform: spec.key,
        handle,
        profile_url: profileUrl,
        credentials: Object.keys(credentials).length ? credentials : undefined,
      })
      clearForm()
    } catch (err: unknown) {
      const msg = typeof err === 'object' && err !== null && 'response' in err
        ? (err as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail?.message
        : undefined
      setFormError(msg || 'Failed to add account. Please check the details and try again.')
    } finally {
      setAdding(false)
    }
  }

  const handleRequestConsent = async () => {
    if (!spec) return
    setFormError(null)
    setConsentNotice(null)
    try {
      await requestPlatformConsent(spec.key)
      setConsentNotice(
        spec.consent_pending
          ? `Consent for ${spec.display_name} is already pending.`
          : `A consent request for ${spec.display_name} was sent. Complete it from the email before adding the account.`,
      )
    } catch {
      // The store exposes the structured API error in the shared error state;
      // keep this panel focused on the selected platform.
      setConsentNotice(null)
    }
  }

  return (
    <div className="flex flex-col gap-[16px]">
      <div className="flex items-start justify-between gap-[10px]">
        <div>
          <h1 className="text-[1.25rem] font-bold text-[#1f2937]">My accounts</h1>
          <p className="text-[0.82rem] text-[#6b7280] mt-[3px] leading-relaxed">
            Connect only your own accounts, or accounts you are authorised to manage.
          </p>
        </div>
      </div>

      {verificationNotice && <div role={verificationNotice.tone === 'error' ? 'alert' : 'status'} aria-live="polite" className={`rounded-[10px] border px-[12px] py-[10px] text-[0.8rem] ${verificationNotice.tone === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-[#fecaca] bg-[#fef2f2] text-[#991b1b]'}`}><i className={`ti ${verificationNotice.tone === 'success' ? 'ti-circle-check' : 'ti-alert-circle'} mr-2`} />{verificationNotice.text}</div>}
      {error && !verificationNotice && (
        <div role="alert" className="rounded-[10px] border border-[#fecaca] bg-[#fef2f2] px-[12px] py-[10px] text-[0.8rem] text-[#991b1b]">
          {error}
        </div>
      )}

      <div className="bg-[#f0fdfa] rounded-xl border border-[#a7f3d0] px-[14px] py-[10px] flex items-start gap-[8px]">
        <i className="ti ti-shield-check text-[16px] text-[#059669] mt-[1px] flex-shrink-0" />
        <p className="text-[0.78rem] text-[#065f46] leading-relaxed">
          MindGuard only reads content the platform already makes public. Nothing is posted or shared on your behalf.
          You cannot use this tool to analyse someone else's social media presence.
        </p>
      </div>

      <div className="bg-white rounded-xl border border-[#e5e7eb] p-[20px]">
        <h3 className="text-[0.95rem] font-bold text-[#1f2937] mb-[14px]">Add account</h3>

        <div className="grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-9 gap-[6px] mb-[14px]">
          {platforms?.map((p) => {
            const connected = accountMap.has(p.key)
            return (
              <button
                key={p.key}
                onClick={() => {
                  if (selectedPlatform === p.key) {
                    setSelectedPlatform(null)
                    clearForm()
                  } else {
                    setSelectedPlatform(p.key)
                    clearForm()
                  }
                }}
                className={`flex items-center justify-center gap-[5px] px-[8px] py-[7px] rounded-[8px] border text-[0.72rem] font-medium cursor-pointer transition-colors ${
                  selectedPlatform === p.key
                    ? 'bg-[#0f2724] text-[#e2f4f1] border-[#0F766E]'
                    : connected
                      ? 'bg-[#f0fdfa] text-[#065f46] border-[#a7f3d0]'
                      : 'bg-[#fafbfc] text-[#4b5563] border-[#e5e7eb] hover:border-[#0F766E]'
                }`}
              >
                <i className={`${p.icon} text-[13px]`} />
                <span className="truncate">{p.display_name}</span>
                {connected && <i className="ti ti-check text-[11px] text-[#059669] flex-shrink-0" />}
              </button>
            )
          })}
        </div>

        {!selectedPlatform ? (
          <p className="text-[0.78rem] text-[#6b7280]">Select a platform above to add your account.</p>
        ) : spec ? (
          <div className="border border-[#e5e7eb] rounded-[10px] p-[16px] bg-[#fafbfc]">
            <div className="flex items-start gap-[10px] mb-[12px]">
              <div className="w-[32px] h-[32px] rounded-lg bg-[#f0fdfa] flex items-center justify-center flex-shrink-0">
                <i className={`${spec.icon} text-[17px] text-[#0F766E]`} />
              </div>
              <div>
                <div className="text-[0.88rem] font-bold text-[#1f2937]">{spec.display_name}</div>
                <div className="text-[0.75rem] text-[#6b7280] leading-relaxed">{spec.blurb}</div>
              </div>
            </div>

            {!spec.consented && (
              <div className="mb-[14px] rounded-[10px] border border-amber-200 bg-amber-50 px-[12px] py-[10px] text-[0.78rem] text-amber-900 leading-relaxed">
                <div className="font-semibold">Consent required before connecting this platform</div>
                <p className="mt-[3px]">
                  {spec.consent_pending
                    ? 'A consent request is already pending. Check the student email or guardian inbox, then return here after it is accepted.'
                    : 'This platform is not covered by your current consent. Request an add-on consent first. For a minor account, the request goes to the registered parent or guardian.'}
                </p>
                {!spec.consent_pending && (
                  <button
                    type="button"
                    onClick={() => void handleRequestConsent()}
                    disabled={Boolean(busy[spec.key])}
                    className="mt-[9px] rounded-[8px] bg-[#0F766E] px-[12px] py-[7px] text-[0.78rem] font-semibold text-white disabled:opacity-50"
                  >
                    {busy[spec.key] ? 'Sending…' : `Request ${spec.display_name} consent`}
                  </button>
                )}
                {consentNotice && <div className="mt-[8px] text-emerald-800">{consentNotice}</div>}
              </div>
            )}

            <div className="flex flex-col gap-[10px] mb-[12px]">
              <div>
                <label className="block text-[0.72rem] font-bold text-[#4b5563] uppercase tracking-wide mb-[4px]">
                  {specHandle?.label || 'Handle'}
                </label>
                <input
                  value={handleValue}
                  onChange={(e) => setHandleValue(e.target.value)}
                  placeholder={specHandle?.example || ''}
                  className="w-full bg-white border border-[#d1d5db] rounded-[8px] px-[12px] py-[9px] text-[0.85rem] text-[#1f2937] placeholder:text-[#9ca3af] focus:border-[#0F766E] focus:ring-1 focus:ring-[#0F766E] outline-none"
                />
                <p className="text-[0.72rem] text-[#6b7280] mt-[4px] leading-relaxed">
                  {specHandle?.format}
                </p>
              </div>

              {specCreds.map((cred) =>
                cred.serverKey ? (
                  <div key={cred.name || 'server'} className="px-[12px] py-[9px] rounded-[8px] bg-[#f8fafc] border border-[#e5e7eb] text-[0.75rem] text-[#6b7280] leading-relaxed">
                    {cred.hint || cred.label}
                  </div>
                ) : (
                  <div key={cred.name}>
                    <label className="block text-[0.72rem] font-bold text-[#4b5563] uppercase tracking-wide mb-[4px]">
                      {cred.label}
                    </label>
                    <input
                      type={cred.type}
                      value={credentialValues[cred.name] || ''}
                      onChange={(e) => setCredentialValues({ ...credentialValues, [cred.name]: e.target.value })}
                      placeholder={cred.placeholder}
                      className="w-full bg-white border border-[#d1d5db] rounded-[8px] px-[12px] py-[9px] text-[0.85rem] text-[#1f2937] placeholder:text-[#9ca3af] focus:border-[#0F766E] focus:ring-1 focus:ring-[#0F766E] outline-none"
                    />
                    {cred.hint && (
                      <p className="text-[0.72rem] text-[#6b7280] mt-[4px] leading-relaxed">{cred.hint}</p>
                    )}
                    {cred.steps?.length ? (
                      <div className="mt-[8px] px-[12px] py-[10px] rounded-[8px] bg-[#f0fdfa] border border-[#a7f3d0]">
                        <div className="text-[0.72rem] font-bold text-[#065f46] mb-[4px]">How to get your {cred.label}:</div>
                        <ol className="flex flex-col gap-[4px] pl-[18px] list-decimal">
                          {cred.steps.map((step, i) => (
                            <li key={i} className="text-[0.72rem] text-[#065f46] leading-relaxed">{step}</li>
                          ))}
                        </ol>
                      </div>
                    ) : null}
                  </div>
                ),
              )}
            </div>

            <div className="text-[0.72rem] text-[#4b5563] leading-relaxed mb-[12px]">
              <div className="flex items-start gap-[6px] mb-[3px]">
                <i className="ti ti-database text-[12px] mt-[2px] text-[#6b7280] flex-shrink-0" />
                <span><strong>What's fetched:</strong> {spec.capabilities}</span>
              </div>
              <div className="flex items-start gap-[6px] mb-[3px]">
                <i className="ti ti-alert-triangle text-[12px] mt-[2px] text-[#d97706] flex-shrink-0" />
                <span><strong>Limitations:</strong> {spec.limitations}</span>
              </div>
              <div className="flex items-start gap-[6px]">
                <i className="ti ti-eye text-[12px] mt-[2px] text-[#6b7280] flex-shrink-0" />
                <span><strong>Requires:</strong> {spec.requires_public}</span>
              </div>
            </div>

            {formError && (
              <div className="px-[12px] py-[8px] rounded-[8px] bg-[#fef2f2] border border-[#fecaca] text-[0.78rem] text-[#991b1b] mb-[10px]">
                {formError}
              </div>
            )}

            <div className="flex gap-[8px]">
              <button
                onClick={handleAdd}
                disabled={adding || !spec.consented}
                className="px-[16px] py-[9px] rounded-[8px] bg-[#0F766E] text-white text-[0.82rem] font-semibold disabled:opacity-50 cursor-pointer hover:bg-[#115E59]"
              >
                {adding ? 'Adding…' : `Add ${spec.display_name} account`}
              </button>
              <button
                onClick={() => { setSelectedPlatform(null); clearForm() }}
                className="px-[16px] py-[9px] rounded-[8px] text-[0.82rem] font-semibold text-[#6b7280] border border-[#d1d5db] cursor-pointer hover:bg-[#f9fafb] bg-transparent"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {accounts.length > 0 ? (
        <div>
          <h3 className="text-[0.95rem] font-bold text-[#1f2937] mb-[10px]">Connected accounts ({accounts.length})</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-[10px]">
            {accounts.map((account) => {
              const specItem = platforms?.find((p) => p.key === account.platform)
              if (!specItem) return null
              return (
                <AccountCard
                  key={account.platform}
                  spec={specItem}
                  account={account}
                  busy={Boolean(busy[account.platform])}
                  verificationCode={verificationCodes[account.platform]}
                  runningPlatforms={runningPlatforms}
                  onVerify={handleVerify}
                  onGetCode={getVerificationCode}
                  onRequestConsent={(slug) => void requestPlatformConsent(slug)}
                  onAnalyse={(slug) => runAnalysis([slug])}
                  onRemove={removeAccount}
                />
              )
            })}
          </div>
        </div>
      ) : (
        !selectedPlatform ? (
          <EmptyState
            icon="ti ti-user-plus"
            title="No accounts connected yet"
            body="Select a platform above to add your first account. MindGuard can analyse Reddit, Bluesky, Mastodon, YouTube, and more — for accounts you own or are authorised to manage."
          />
        ) : null
      )}
    </div>
  )
}

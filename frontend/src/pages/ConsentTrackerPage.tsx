import { useEffect, useState } from 'react'
import { getConsents, createConsent, dispatchConsent, cancelConsent, remindConsent, exportConsents, recordConsentDecision } from '../api/counsellor'
import { getStudents } from '../api/counsellor'
import RosterPanel from '../components/consent/RosterPanel'
import ConsentDetailDrawer from '../components/consent/ConsentDetailDrawer'
import BulkConsentUpload from '../components/consent/BulkConsentUpload'
import type { Consent, ConsentStatus } from '../types'
import type { StudentDTO } from '../api/counsellor'
import { updateInstitutionGuardianConsentRecipient } from '../api/admin'
import { useAuthStore } from '../store'

function formatDate(d?: string) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function expiryHint(c: Consent): { label: string; tone: string } | null {
  if (c.status !== 'PENDING' && c.status !== 'VIEWED') return null
  if (!c.expires_at) return null
  const ms = new Date(c.expires_at).getTime() - Date.now()
  if (ms <= 0) return { label: 'expired', tone: 'text-[#ef4444] font-semibold' }
  const days = Math.ceil(ms / 86400000)
  if (days <= 2) return { label: `expires in ${days}d`, tone: 'text-[#d97706] font-semibold' }
  return { label: `expires in ${days}d`, tone: 'text-[#9ca3af]' }
}

const STATUS_STYLE: Record<ConsentStatus, string> = {
  DRAFT: 'bg-[#f1f5f9] text-[#6b7280]',
  PENDING: 'bg-[#fef3c7] text-[#92400e]',
  VIEWED: 'bg-[#dbeafe] text-[#1e40af]',
  ACCEPTED: 'bg-[#d1fae5] text-[#065f46]',
  DECLINED: 'bg-[#fee2e2] text-[#991b1b]',
  EXPIRED: 'bg-[#f1f5f9] text-[#6b7280]',
  REVOKED: 'bg-[#fee2e2] text-[#991b1b]',
  RENEWAL_DUE: 'bg-[#fff7ed] text-[#9a3412]',
  INVALID: 'bg-[#fee2e2] text-[#991b1b]',
}

const DELIVERY_STYLE: Record<string, string> = {
  delivered: 'bg-[#d1fae5] text-[#065f46]',
  bounced: 'bg-[#fee2e2] text-[#991b1b]',
  complained: 'bg-[#fef3c7] text-[#92400e]',
}

const DELIVERY_LABEL: Record<string, string> = {
  delivered: 'Delivered',
  bounced: 'Bounced',
  complained: 'Complaint',
}

const FILTER_TABS: Array<{ key: string; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'PENDING', label: 'Pending' },
  { key: 'VIEWED', label: 'Viewed' },
  { key: 'ACCEPTED', label: 'Accepted' },
  { key: 'DECLINED', label: 'Declined' },
  { key: 'EXPIRED', label: 'Expired' },
  { key: 'REVOKED', label: 'Revoked' },
]

const PAGE_SIZE = 50

const PLATFORMS = ['Reddit', 'Bluesky', 'Mastodon', 'YouTube']

// ─── New Consent Modal ────────────────────────────────────────────────────────

interface NewConsentModalProps {
  students: StudentDTO[]
  onClose: () => void
  onCreated: (consent: Consent) => void
  onDispatched?: () => void
}

function NewConsentModal({ students, onClose, onCreated, onDispatched }: NewConsentModalProps) {
  const [tab, setTab] = useState<'single' | 'bulk'>('single')
  const [studentId, setStudentId] = useState('')
  const [recipientEmail, setRecipientEmail] = useState('')
  const [recipientRole, setRecipientRole] = useState<'student' | 'parent'>('student')
  const [platforms, setPlatforms] = useState<string[]>([])
  const [mode, setMode] = useState<'ON_DEMAND' | 'CONTINUOUS'>('ON_DEMAND')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const togglePlatform = (p: string) => {
    setPlatforms((prev) => prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p])
  }

  const handleSubmit = async () => {
    if (!studentId || !recipientEmail || platforms.length === 0) {
      setError('Please fill in all required fields and select at least one platform.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const consent = await createConsent(studentId, {
        recipient_email: recipientEmail,
        recipient_role: recipientRole,
        platforms,
        mode,
      })
      onCreated(consent)
      onClose()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-[480px] max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-[20px] py-[14px] border-b border-[#f1f5f9]">
          <h3 className="text-[0.95rem] font-bold text-[#1f2937]">New Consent</h3>
          <button onClick={onClose} className="text-[#9ca3af] hover:text-[#6b7280] cursor-pointer bg-transparent border-none">
            <i className="ti ti-x text-[18px]" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex px-[20px] pt-[12px] pb-0 gap-[4px]">
          {(
            [
              { key: 'single', label: 'Single Student', icon: 'ti ti-user-plus' },
              { key: 'bulk', label: 'Bulk Upload', icon: 'ti ti-cloud-upload' },
            ] as const
          ).map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-[6px] px-[12px] py-[7px] rounded-t-[8px] text-[0.8rem] font-semibold cursor-pointer border border-b-0 transition-colors ${
                tab === t.key
                  ? 'bg-[#f0fdfa] text-[#0F766E] border-[#e5e7eb]'
                  : 'bg-white text-[#6b7280] border-transparent hover:bg-[#f9fafb]'
              }`}
            >
              <i className={`${t.icon} text-[13px]`} />
              {t.label}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-[14px] p-[20px]">
          {tab === 'single' && (
            <>
          {/* Student */}
          <div>
            <label className="block text-[0.78rem] font-semibold text-[#374151] mb-[4px]">Student *</label>
            <select
              value={studentId}
              onChange={(e) => setStudentId(e.target.value)}
              className="w-full rounded-[8px] border border-[#e5e7eb] px-[10px] py-[8px] text-[0.82rem] text-[#1f2937] bg-white focus:outline-none focus:ring-2 focus:ring-[#0F766E]"
            >
              <option value="">Select student...</option>
              {students.map((s) => (
                <option key={s.id} value={s.id}>{s.name} ({s.email})</option>
              ))}
            </select>
          </div>

          {/* Recipient email */}
          <div>
            <label className="block text-[0.78rem] font-semibold text-[#374151] mb-[4px]">Recipient Email *</label>
            <input
              type="email"
              value={recipientEmail}
              onChange={(e) => setRecipientEmail(e.target.value)}
              placeholder="recipient@example.com"
              className="w-full rounded-[8px] border border-[#e5e7eb] px-[10px] py-[8px] text-[0.82rem] text-[#1f2937] placeholder-[#9ca3af] focus:outline-none focus:ring-2 focus:ring-[#0F766E]"
            />
          </div>

          {/* Recipient role */}
          <div>
            <label className="block text-[0.78rem] font-semibold text-[#374151] mb-[4px]">Recipient Role</label>
            <div className="flex gap-[8px]">
              {(['student', 'parent'] as const).map((r) => (
                <button
                  key={r}
                  onClick={() => setRecipientRole(r)}
                  className={`px-[14px] py-[6px] rounded-[7px] text-[0.8rem] font-semibold cursor-pointer border transition-colors capitalize ${
                    recipientRole === r
                      ? 'bg-[#0F766E] text-white border-[#0F766E]'
                      : 'bg-white text-[#6b7280] border-[#e5e7eb] hover:bg-[#f9fafb]'
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>

          {/* Platforms */}
          <div>
            <label className="block text-[0.78rem] font-semibold text-[#374151] mb-[6px]">Platforms * (select at least one)</label>
            <div className="flex flex-wrap gap-[8px]">
              {PLATFORMS.map((p) => (
                <button
                  key={p}
                  onClick={() => togglePlatform(p)}
                  className={`px-[12px] py-[5px] rounded-[7px] text-[0.8rem] font-semibold cursor-pointer border transition-colors ${
                    platforms.includes(p)
                      ? 'bg-[#0F766E] text-white border-[#0F766E]'
                      : 'bg-white text-[#6b7280] border-[#e5e7eb] hover:bg-[#f9fafb]'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* Mode */}
          <div>
            <label className="block text-[0.78rem] font-semibold text-[#374151] mb-[4px]">Mode</label>
            <div className="flex gap-[8px]">
              <button
                onClick={() => setMode('ON_DEMAND')}
                className={`px-[14px] py-[6px] rounded-[7px] text-[0.8rem] font-semibold cursor-pointer border transition-colors ${
                  mode === 'ON_DEMAND'
                    ? 'bg-[#0F766E] text-white border-[#0F766E]'
                    : 'bg-white text-[#6b7280] border-[#e5e7eb] hover:bg-[#f9fafb]'
                }`}
              >
                On-demand
              </button>
              <button
                onClick={() => setMode('CONTINUOUS')}
                className={`px-[14px] py-[6px] rounded-[7px] text-[0.8rem] font-semibold cursor-pointer border transition-colors ${
                  mode === 'CONTINUOUS'
                    ? 'bg-[#0F766E] text-white border-[#0F766E]'
                    : 'bg-white text-[#6b7280] border-[#e5e7eb] hover:bg-[#f9fafb]'
                }`}
              >
                Continuous
              </button>
            </div>
          </div>

          {error && (
            <div className="flex items-center gap-[6px] text-[#ef4444] text-[0.82rem]">
              <i className="ti ti-alert-circle" /> {error}
            </div>
          )}

          <div className="flex gap-[8px] pt-[4px]">
            <button
              onClick={handleSubmit}
              disabled={submitting}
              className="flex-1 flex items-center justify-center gap-[6px] px-[14px] py-[8px] bg-[#0F766E] text-white rounded-[8px] text-[0.82rem] font-semibold cursor-pointer hover:bg-[#0d5c56] transition-colors disabled:opacity-50"
            >
              {submitting ? (
                <div className="w-[14px] h-[14px] border-2 border-white/40 border-t-white rounded-full animate-spin" />
              ) : (
                <i className="ti ti-send text-[14px]" />
              )}
              {submitting ? 'Creating & Dispatching...' : 'Create & Dispatch'}
            </button>
            <button
              onClick={onClose}
              disabled={submitting}
              className="px-[14px] py-[8px] border border-[#e5e7eb] text-[#6b7280] rounded-[8px] text-[0.82rem] font-semibold cursor-pointer hover:bg-[#f9fafb] transition-colors bg-white disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
            </>
          )}

          {tab === 'bulk' && (
            <BulkConsentUpload
              onDispatched={() => {
                onDispatched?.()
                onClose()
              }}
            />
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function ConsentTrackerPage() {
  const role = useAuthStore((state) => state.user?.role_type?.toLowerCase())
  const [tab, setTab] = useState<'consents' | 'roster'>('consents')
  const [filterTab, setFilterTab] = useState('all')
  const [consents, setConsents] = useState<Consent[]>([])
  const [students, setStudents] = useState<StudentDTO[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [dispatchNotice, setDispatchNotice] = useState<Consent | null>(null)
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(0)
  const [total, setTotal] = useState(0)
  const [bulkNotice, setBulkNotice] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [detailConsentId, setDetailConsentId] = useState<string | null>(null)
  const [decideConsentId, setDecideConsentId] = useState<string | null>(null)
  const [decideSignature, setDecideSignature] = useState('')
  const [guardianEditConsentId, setGuardianEditConsentId] = useState<string | null>(null)
  const [guardianEmailDraft, setGuardianEmailDraft] = useState('')
  const [guardianNotice, setGuardianNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    const t = setTimeout(() => { setSearch(searchInput); setPage(0) }, 300)
    return () => clearTimeout(t)
  }, [searchInput])

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [consentData, studentData] = await Promise.all([
        getConsents({
          ...(filterTab !== 'all' ? { status: filterTab } : {}),
          ...(search ? { search } : {}),
          ...(dateFrom ? { dateFrom } : {}),
          ...(dateTo ? { dateTo } : {}),
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        }),
        getStudents(),
      ])
      setConsents(consentData.consents)
      setTotal(consentData.total)
      setStudents(studentData)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [filterTab, search, dateFrom, dateTo, page])

  const handleAction = async (action: () => Promise<any>, id: string) => {
    setActionLoading(id)
    try {
      const result = await action()
      if (result?.email_sent !== undefined || result?.consent_url) {
        setDispatchNotice(result)
      }
      await load()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setActionLoading(null)
    }
  }

  const saveGuardianEmail = async (consent: Consent) => {
    const email = guardianEmailDraft.trim().toLowerCase()
    if (!email) {
      setGuardianNotice({ type: 'error', text: 'Enter the parent or guardian email address.' })
      return
    }
    setActionLoading(consent.id); setGuardianNotice(null)
    try {
      const result = await updateInstitutionGuardianConsentRecipient(consent.id, email)
      setGuardianEditConsentId(null)
      setGuardianEmailDraft('')
      setGuardianNotice({
        type: result.email_sent ? 'success' : 'error',
        text: result.email_sent
          ? `Guardian address updated and a fresh consent link sent to ${email}. The previous link is no longer valid.`
          : `Guardian address updated, but email delivery was not confirmed${result.email_error ? `: ${result.email_error}` : '.'} Use Remind to retry after checking the address.`,
      })
      await load()
    } catch (e) {
      setGuardianNotice({ type: 'error', text: e instanceof Error ? e.message : 'Unable to update guardian address.' })
    } finally { setActionLoading(null) }
  }

  const handleExport = async () => {
    setError(null)
    try {
      const blob = await exportConsents({
        ...(filterTab !== 'all' ? { status: filterTab } : {}),
        ...(search ? { search } : {}),
        ...(dateFrom ? { dateFrom } : {}),
        ...(dateTo ? { dateTo } : {}),
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `mindguard-consents-${new Date().toISOString().slice(0, 10)}.csv`
      link.click()
      URL.revokeObjectURL(url)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const toggleSelected = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectPage = () => {
    const allSelected = consents.length > 0 && consents.every((c) => selected.has(c.id))
    setSelected(allSelected ? new Set() : new Set(consents.map((c) => c.id)))
  }

  const handleBulkAction = async (action: 'resend' | 'cancel') => {
    const ids = [...selected]
    if (ids.length === 0) return
    setActionLoading('bulk')
    setBulkNotice(null)
    let ok = 0
    let failed = 0
    try {
      for (const id of ids) {
        const consent = consents.find((c) => c.id === id)
        if (!consent) continue
        try {
          if (action === 'resend') {
            if (consent.status === 'DRAFT') await dispatchConsent(id)
            else await remindConsent(id)
          } else {
            await cancelConsent(id)
          }
          ok += 1
        } catch {
          failed += 1
        }
      }
      setBulkNotice(`${action === 'resend' ? 'Resent' : 'Cancelled'} ${ok} consent(s)${failed ? `, ${failed} failed` : ''}.`)
      setSelected(new Set())
      await load()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setActionLoading(null)
    }
  }

  const canBulkResend = selected.size > 0 && [...selected].some((id) => {
    const c = consents.find((x) => x.id === id)
    return c && c.status !== 'ACCEPTED' && c.status !== 'REVOKED'
  })
  const canBulkCancel = selected.size > 0 && [...selected].some((id) => {
    const c = consents.find((x) => x.id === id)
    return c && c.status === 'PENDING'
  })

  const filtered = consents

  return (
    <div className="flex flex-col gap-[16px]">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-[1.3rem] font-bold text-[#1f2937]">Consent Tracker</h2>
          <p className="text-[0.82rem] text-[#6b7280] mt-[2px]">
            Manage data-sharing consents and the student roster
          </p>
        </div>
        {tab === 'consents' && (
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-[6px] px-[14px] py-[8px] bg-[#0F766E] text-white rounded-[8px] text-[0.82rem] font-semibold cursor-pointer hover:bg-[#0d5c56] transition-colors"
          >
            <i className="ti ti-plus text-[14px]" />
            New Consent
          </button>
        )}
      </div>

      {/* Consents / Roster tabs */}
      <div className="flex items-center gap-[2px] bg-[#f1f5f9] rounded-[8px] p-[4px] w-fit">
        {(['consents', 'roster'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-[14px] py-[6px] rounded-[6px] text-[0.82rem] font-semibold cursor-pointer transition-colors border-none capitalize ${
              tab === t
                ? 'bg-white text-[#1f2937] shadow-sm'
                : 'bg-transparent text-[#6b7280] hover:text-[#374151]'
            }`}
          >
            {t === 'consents' ? 'Consents' : 'Roster'}
          </button>
        ))}
      </div>

      {tab === 'roster' && <RosterPanel />}

      {tab === 'consents' && (<>
      {/* Filter tabs + search + export */}
      <div className="flex flex-wrap items-center gap-[10px]">
        <div className="flex items-center gap-[2px] bg-[#f1f5f9] rounded-[8px] p-[4px] w-fit">
          {FILTER_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => { setFilterTab(t.key); setPage(0) }}
              className={`px-[12px] py-[5px] rounded-[6px] text-[0.8rem] font-semibold cursor-pointer transition-colors border-none ${
                filterTab === t.key
                  ? 'bg-white text-[#1f2937] shadow-sm'
                  : 'bg-transparent text-[#6b7280] hover:text-[#374151]'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="relative flex-1 min-w-[220px] max-w-[360px]">
          <i className="ti ti-search absolute left-[10px] top-1/2 -translate-y-1/2 text-[14px] text-[#9ca3af]" />
          <input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search by student name, email, or ID..."
            className="w-full rounded-[8px] border border-[#e5e7eb] pl-[30px] pr-[10px] py-[7px] text-[0.8rem] text-[#1f2937] placeholder-[#9ca3af] bg-white focus:outline-none focus:ring-2 focus:ring-[#0F766E]"
          />
        </div>
        <div className="flex items-center gap-[6px]">
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => { setDateFrom(e.target.value); setPage(0) }}
            title="Created from"
            className="rounded-[8px] border border-[#e5e7eb] px-[10px] py-[7px] text-[0.8rem] text-[#1f2937] bg-white focus:outline-none focus:ring-2 focus:ring-[#0F766E]"
          />
          <span className="text-[0.78rem] text-[#9ca3af]">to</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => { setDateTo(e.target.value); setPage(0) }}
            title="Created to"
            className="rounded-[8px] border border-[#e5e7eb] px-[10px] py-[7px] text-[0.8rem] text-[#1f2937] bg-white focus:outline-none focus:ring-2 focus:ring-[#0F766E]"
          />
        </div>
        <button
          onClick={handleExport}
          className="flex items-center gap-[6px] px-[12px] py-[7px] border border-[#e5e7eb] bg-white text-[#374151] rounded-[8px] text-[0.8rem] font-semibold cursor-pointer hover:bg-[#f9fafb] transition-colors"
        >
          <i className="ti ti-download text-[14px]" />
          Export CSV
        </button>
      </div>

      {bulkNotice && (
        <div className="rounded-[10px] bg-[#ecfdf5] border border-[#bbf7d0] px-[16px] py-[10px] text-[0.82rem] text-[#065f46]">
          {bulkNotice}
        </div>
      )}

      {guardianNotice && <div role={guardianNotice.type === 'error' ? 'alert' : 'status'} className={`rounded-[10px] border px-[16px] py-[10px] text-[0.82rem] ${guardianNotice.type === 'error' ? 'border-red-200 bg-red-50 text-red-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}>{guardianNotice.text}</div>}

      {selected.size > 0 && (
        <div className="flex items-center gap-[10px] rounded-[10px] bg-[#f0fdfa] border border-[#99f6e4] px-[16px] py-[10px]">
          <span className="text-[0.82rem] font-semibold text-[#134e4a]">{selected.size} selected</span>
          <button
            onClick={() => handleBulkAction('resend')}
            disabled={!canBulkResend || actionLoading === 'bulk'}
            className="px-[12px] py-[6px] bg-[#0F766E] text-white rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#0d5c56] transition-colors disabled:opacity-50"
          >
            {actionLoading === 'bulk' ? '...' : 'Resend selected'}
          </button>
          <button
            onClick={() => handleBulkAction('cancel')}
            disabled={!canBulkCancel || actionLoading === 'bulk'}
            className="px-[12px] py-[6px] bg-[#fee2e2] text-[#991b1b] rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#fecaca] transition-colors disabled:opacity-50"
          >
            Cancel selected
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="px-[12px] py-[6px] text-[0.78rem] font-semibold text-[#6b7280] cursor-pointer hover:text-[#374151] bg-transparent border-none"
          >
            Clear
          </button>
        </div>
      )}

      {dispatchNotice && (
        <div className={`rounded-[10px] border px-[16px] py-[12px] text-[0.84rem] ${
          dispatchNotice.email_sent
            ? 'bg-[#ecfdf5] border-[#bbf7d0] text-[#065f46]'
            : 'bg-[#fff7ed] border-[#fed7aa] text-[#9a3412]'
        }`}>
          <div className="font-bold">
            {dispatchNotice.email_sent ? 'Consent email sent.' : 'Consent created, but email was not sent.'}
          </div>
          {!dispatchNotice.email_sent && dispatchNotice.email_error && (
            <div className="mt-[4px]">{dispatchNotice.email_error}</div>
          )}
          {dispatchNotice.consent_url && (
            <div className="mt-[6px] break-all">
              Consent link: <a className="underline font-semibold" href={dispatchNotice.consent_url} target="_blank" rel="noreferrer">{dispatchNotice.consent_url}</a>
            </div>
          )}
        </div>
      )}

      <div className="bg-white rounded-xl border border-[rgba(229,231,235,0.7)] overflow-hidden">
        <div className="flex items-center justify-between px-[20px] py-[14px] border-b border-[#f1f5f9]">
          <div className="flex items-center gap-[8px]">
            <i className="ti ti-file-check text-[16px] text-[#6b7280]" />
            <span className="text-[0.9rem] font-bold text-[#1f2937]">Consents</span>
            {!loading && (
              <span className="text-[0.78rem] text-[#9ca3af] ml-[4px]">({total})</span>
            )}
          </div>
          <div className="flex items-center gap-[8px]">
            <button
              onClick={handleExport}
              className="flex items-center gap-[6px] px-[12px] py-[6px] border border-[#e5e7eb] bg-white text-[#374151] rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#f9fafb] transition-colors"
            >
              <i className="ti ti-download text-[14px]" />
              Export CSV
            </button>
            <button
              onClick={load}
              className="flex items-center gap-[6px] px-[12px] py-[6px] bg-[#0F766E] text-white rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#115E59] transition-colors"
            >
              <i className="ti ti-refresh text-[14px]" />
              Refresh
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-[60px] text-[#6b7280]">
            <div className="w-[24px] h-[24px] border-2 border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin mr-[10px]" />
            <span className="text-[0.82rem]">Loading consents...</span>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-[60px] text-[#ef4444]">
            <i className="ti ti-alert-circle text-[32px] mb-[8px]" />
            <span className="text-[0.82rem]">{error}</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-[60px] text-[#9ca3af]">
            <i className="ti ti-file-x text-[32px] mb-[8px]" />
            <span className="text-[0.82rem]">No consents found</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[0.82rem]">
              <thead className="bg-[#f9fafb]">
                <tr className="text-[#6b7280] font-semibold text-[0.72rem] uppercase tracking-wider">
                  <th className="py-[10px] pl-[20px] pr-[4px] w-[36px]">
                    <input
                      type="checkbox"
                      checked={consents.length > 0 && consents.every((c) => selected.has(c.id))}
                      onChange={toggleSelectPage}
                      className="w-[15px] h-[15px] accent-[#0F766E] cursor-pointer"
                    />
                  </th>
                  <th className="text-left py-[10px] px-[20px]">Student</th>
                  <th className="text-left py-[10px] px-[20px]">Recipient</th>
                  <th className="text-left py-[10px] px-[20px]">Mode</th>
                  <th className="text-left py-[10px] px-[20px]">Status</th>
                  <th className="text-left py-[10px] px-[20px]">Delivery</th>
                  <th className="text-left py-[10px] px-[20px]">Dispatched</th>
                  <th className="text-left py-[10px] px-[20px]">Expires</th>
                  <th className="text-left py-[10px] px-[20px]">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f1f5f9]">
                {filtered.map((consent) => {
                  const isActing = actionLoading === consent.id
                  return (
                    <tr key={consent.id} className={`hover:bg-[#f8fafc] transition-colors ${selected.has(consent.id) ? 'bg-[#f0fdfa]' : ''}`}>
                      <td className="py-[12px] pl-[20px] pr-[4px] w-[36px]">
                        <input
                          type="checkbox"
                          checked={selected.has(consent.id)}
                          onChange={() => toggleSelected(consent.id)}
                          className="w-[15px] h-[15px] accent-[#0F766E] cursor-pointer"
                        />
                      </td>
                      <td className="py-[12px] px-[20px] font-medium text-[#1f2937]">
                        {consent.student_name || consent.student_id}
                      </td>
                      <td className="py-[12px] px-[20px]">
                        {guardianEditConsentId === consent.id ? (
                          <div className="min-w-[220px] space-y-2">
                            <input type="email" value={guardianEmailDraft} onChange={(e) => setGuardianEmailDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void saveGuardianEmail(consent) }} placeholder="parent@example.org" className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" aria-label="Correct parent or guardian email" />
                            <div className="flex gap-2"><button onClick={() => void saveGuardianEmail(consent)} disabled={isActing} className="rounded-md bg-teal-800 px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-50">{isActing ? 'Sending…' : 'Save & send new link'}</button><button onClick={() => { setGuardianEditConsentId(null); setGuardianEmailDraft('') }} className="text-xs font-semibold text-slate-500">Cancel</button></div>
                            <p className="text-[0.68rem] text-amber-800">The previous link will be invalidated.</p>
                          </div>
                        ) : <div className="flex items-center gap-2"><span className="text-[#1f2937]">{consent.recipient_email}</span>{role === 'school_admin' && consent.recipient_role === 'parent' && ['PENDING', 'VIEWED', 'EXPIRED', 'INVALID'].includes(consent.status) && <button onClick={() => { setGuardianEditConsentId(consent.id); setGuardianEmailDraft(consent.recipient_email) }} className="text-xs font-semibold text-teal-800 underline">Edit email</button>}</div>}
                        <div className="text-[0.7rem] text-[#9ca3af] capitalize">{consent.recipient_role}</div>
                      </td>
                      <td className="py-[12px] px-[20px] text-[#6b7280]">
                        {consent.mode === 'ON_DEMAND' ? 'On-demand' : 'Continuous'}
                      </td>
                      <td className="py-[12px] px-[20px]">
                        <span className={`inline-block px-[8px] py-[2px] rounded-full text-[0.7rem] font-semibold ${STATUS_STYLE[consent.status]}`}>
                          {consent.status.replace(/_/g, ' ')}
                        </span>
                      </td>
                      <td className="py-[12px] px-[20px]">
                        {consent.delivery_status ? (
                          <span
                            className={`inline-block px-[8px] py-[2px] rounded-full text-[0.7rem] font-semibold ${DELIVERY_STYLE[consent.delivery_status] || 'bg-[#f1f5f9] text-[#6b7280]'}`}
                            title={consent.last_delivery_event_at ? `Reported ${formatDate(consent.last_delivery_event_at)}` : undefined}
                          >
                            {DELIVERY_LABEL[consent.delivery_status] || consent.delivery_status}
                          </span>
                        ) : (
                          <span className="text-[#d1d5db]">—</span>
                        )}
                      </td>
                      <td className="py-[12px] px-[20px] text-[#6b7280]">
                        {formatDate(consent.dispatched_at)}
                      </td>
                      <td className="py-[12px] px-[20px]">
                        {consent.expires_at ? (
                          <div className="text-[#374151]">{formatDate(consent.expires_at)}</div>
                        ) : (
                          <span className="text-[#d1d5db]">—</span>
                        )}
                        {(() => {
                          const hint = expiryHint(consent)
                          return hint ? (
                            <div className={`text-[0.7rem] mt-[2px] ${hint.tone}`}>{hint.label}</div>
                          ) : null
                        })()}
                      </td>
                      <td className="py-[12px] px-[20px]">
                        <div className="flex items-center gap-[6px]">
                          <button
                            onClick={() => setDetailConsentId(consent.id)}
                            title="View audit trail"
                            className="px-[10px] py-[4px] border border-[#e5e7eb] bg-white text-[#374151] rounded-[6px] text-[0.72rem] font-semibold cursor-pointer hover:bg-[#f9fafb] transition-colors"
                          >
                            <i className="ti ti-eye text-[13px]" />
                          </button>
                          {consent.status === 'DRAFT' && (
                            <button
                              onClick={() => handleAction(() => dispatchConsent(consent.id), consent.id)}
                              disabled={isActing}
                              className="px-[10px] py-[4px] bg-[#0F766E] text-white rounded-[6px] text-[0.72rem] font-semibold cursor-pointer hover:bg-[#0d5c56] transition-colors disabled:opacity-50"
                            >
                              {isActing ? '...' : 'Dispatch'}
                            </button>
                          )}
                          {(consent.status === 'PENDING' || consent.status === 'VIEWED') && (
                            <>
                              {decideConsentId === consent.id ? (
                                <div className="flex items-center gap-[6px]">
                                  <input
                                    autoFocus
                                    value={decideSignature}
                                    onChange={(e) => setDecideSignature(e.target.value)}
                                    onKeyDown={(e) => { if (e.key === 'Escape') setDecideConsentId(null) }}
                                    placeholder="Recipient name"
                                    title="Name of the person who gave their decision (optional)"
                                    className="w-[130px] rounded-[6px] border border-[#e5e7eb] px-[8px] py-[4px] text-[0.72rem] focus:outline-none focus:ring-2 focus:ring-[#0F766E]"
                                  />
                                  <button
                                    onClick={() => handleAction(
                                      () => recordConsentDecision(consent.id, 'ACCEPTED', decideSignature.trim() || undefined),
                                      consent.id,
                                    )}
                                    disabled={isActing}
                                    className="px-[10px] py-[4px] bg-[#0F766E] text-white rounded-[6px] text-[0.72rem] font-semibold cursor-pointer hover:bg-[#0d5c56] transition-colors disabled:opacity-50"
                                  >
                                    {isActing ? '...' : 'Accept'}
                                  </button>
                                  <button
                                    onClick={() => handleAction(
                                      () => recordConsentDecision(consent.id, 'DECLINED', decideSignature.trim() || undefined),
                                      consent.id,
                                    )}
                                    disabled={isActing}
                                    className="px-[10px] py-[4px] bg-[#fee2e2] text-[#991b1b] rounded-[6px] text-[0.72rem] font-semibold cursor-pointer hover:bg-[#fecaca] transition-colors disabled:opacity-50"
                                  >
                                    Decline
                                  </button>
                                  <button
                                    onClick={() => { setDecideConsentId(null); setDecideSignature('') }}
                                    className="text-[0.72rem] font-semibold text-[#6b7280] cursor-pointer hover:text-[#374151] bg-transparent border-none"
                                  >
                                    ✕
                                  </button>
                                </div>
                              ) : (
                                <button
                                  onClick={() => { setDecideConsentId(consent.id); setDecideSignature('') }}
                                  disabled={isActing}
                                  title="Record the recipient's decision collected on paper or verbally"
                                  className="px-[10px] py-[4px] bg-[#f0fdfa] text-[#0F766E] border border-[#99f6e4] rounded-[6px] text-[0.72rem] font-semibold cursor-pointer hover:bg-[#ccfbf1] transition-colors disabled:opacity-50"
                                >
                                  Record decision
                                </button>
                              )}
                              <button
                                onClick={() => handleAction(() => remindConsent(consent.id), consent.id)}
                                disabled={isActing}
                                className="px-[10px] py-[4px] bg-[#dbeafe] text-[#1e40af] rounded-[6px] text-[0.72rem] font-semibold cursor-pointer hover:bg-[#bfdbfe] transition-colors disabled:opacity-50"
                              >
                                {isActing ? '...' : 'Remind'}
                              </button>
                              <button
                                onClick={() => handleAction(() => cancelConsent(consent.id), consent.id)}
                                disabled={isActing}
                                className="px-[10px] py-[4px] bg-[#fee2e2] text-[#991b1b] rounded-[6px] text-[0.72rem] font-semibold cursor-pointer hover:bg-[#fecaca] transition-colors disabled:opacity-50"
                              >
                                Cancel
                              </button>
                            </>
                          )}
                          {(consent.status === 'DECLINED' || consent.status === 'EXPIRED') && (
                            <button
                              onClick={() => handleAction(() => dispatchConsent(consent.id), consent.id)}
                              disabled={isActing}
                              className="px-[10px] py-[4px] bg-[#0F766E] text-white rounded-[6px] text-[0.72rem] font-semibold cursor-pointer hover:bg-[#0d5c56] transition-colors disabled:opacity-50"
                            >
                              {isActing ? '...' : 'Re-dispatch'}
                            </button>
                          )}
                          {consent.status === 'ACCEPTED' && (
                            <span className="text-[0.72rem] text-[#22c55e] font-semibold flex items-center gap-[4px]">
                              <i className="ti ti-check" /> Accepted
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {!loading && !error && total > PAGE_SIZE && (
          <div className="flex items-center justify-between px-[20px] py-[10px] border-t border-[#f1f5f9]">
            <span className="text-[0.78rem] text-[#6b7280]">
              Showing {(page * PAGE_SIZE) + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
            </span>
            <div className="flex items-center gap-[6px]">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="px-[10px] py-[5px] border border-[#e5e7eb] bg-white text-[#374151] rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#f9fafb] transition-colors disabled:opacity-40"
              >
                <i className="ti ti-chevron-left text-[13px]" />
              </button>
              <span className="text-[0.78rem] text-[#6b7280]">{page + 1} / {Math.ceil(total / PAGE_SIZE)}</span>
              <button
                onClick={() => setPage((p) => Math.min(Math.ceil(total / PAGE_SIZE) - 1, p + 1))}
                disabled={(page + 1) * PAGE_SIZE >= total}
                className="px-[10px] py-[5px] border border-[#e5e7eb] bg-white text-[#374151] rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#f9fafb] transition-colors disabled:opacity-40"
              >
                <i className="ti ti-chevron-right text-[13px]" />
              </button>
            </div>
          </div>
        )}
      </div>

      {showModal && (
        <NewConsentModal
          students={students}
          onClose={() => setShowModal(false)}
          onCreated={(consent) => {
            setDispatchNotice(consent)
            load()
          }}
          onDispatched={() => load()}
        />
      )}

      {detailConsentId && (
        <ConsentDetailDrawer
          consentId={detailConsentId}
          onClose={() => setDetailConsentId(null)}
        />
      )}
      </>)}
    </div>
  )
}

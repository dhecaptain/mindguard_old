import { useEffect, useState, useRef } from 'react'
import { useAuthStore, useUiStore, useNotificationStore, usePlatformStore } from '../../store'
import type { PageKey } from '../../store/uiStore'
import { useCounsellorStore } from '../../store/counsellorStore'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { getAlerts } from '../../api/counsellor'
import { clearToken } from '../../lib/tokenStorage'
import { NOTIFICATION_TYPE_LABELS, NOTIFICATION_TYPE_ICONS } from '../../types'

const STUDENT_NAV_ITEMS: { key: string; icon: string; label: string }[] = [
  { key: 'dashboard', icon: 'ti ti-brain', label: 'Dashboard' },
  { key: 'feedback', icon: 'ti ti-message-check', label: 'Counsellor updates' },
  { key: 'my-accounts', icon: 'ti ti-link', label: 'My Accounts' },
  { key: 'communications', icon: 'ti ti-mail', label: 'Messages' },
  { key: 'appointments', icon: 'ti ti-calendar-event', label: 'Appointments' },
  { key: 'resources', icon: 'ti ti-ambulance', label: 'Crisis Resources' },
  { key: 'team', icon: 'ti ti-users', label: 'Team' },
  { key: 'voice-support', icon: 'ti ti-wave-sine', label: 'Calm with voice' },
]

const ADULT_STUDENT_NAV_ITEMS: { key: string; icon: string; label: string }[] = [
  ...STUDENT_NAV_ITEMS.slice(0, 2),
  ...STUDENT_NAV_ITEMS.slice(2),
]

const INSTITUTION_STUDENT_NAV_ITEMS: { key: string; icon: string; label: string }[] = [
  { key: 'dashboard', icon: 'ti ti-heart-handshake', label: 'My wellbeing space' },
  { key: 'feedback', icon: 'ti ti-message-check', label: 'Counsellor updates' },
  { key: 'my-accounts', icon: 'ti ti-link', label: 'Optional accounts' },
  { key: 'communications', icon: 'ti ti-mail', label: 'Messages' },
  { key: 'appointments', icon: 'ti ti-calendar-event', label: 'Appointments' },
  { key: 'resources', icon: 'ti ti-lifebuoy', label: 'Get support now' },
  { key: 'voice-support', icon: 'ti ti-wave-sine', label: 'Calm with voice' },
]

const GUARDIAN_NAV_ITEMS: { key: string; icon: string; label: string }[] = [
  { key: 'dashboard', icon: 'ti ti-home-heart', label: 'Guardian home' },
  { key: 'communications', icon: 'ti ti-mail', label: 'Messages' },
  { key: 'resources', icon: 'ti ti-lifebuoy', label: 'Support resources' },
  { key: 'voice-support', icon: 'ti ti-wave-sine', label: 'Calm with voice' },
]

const COUNSELLOR_NAV_BASE = [
  { key: 'counsellor-dashboard', icon: 'ti ti-layout-dashboard', label: 'Dashboard' },
  { key: 'institution', icon: 'ti ti-building-community', label: 'Institution' },
  { key: 'students', icon: 'ti ti-users', label: 'Students' },
  { key: 'batch', icon: 'ti ti-player-play', label: 'Batch Analysis' },
  { key: 'unified', icon: 'ti ti-chart-dots-3', label: 'Multi-Platform' },
  { key: 'guest-analysis', icon: 'ti ti-user-scan', label: 'Guest Analysis' },
  { key: 'referrals', icon: 'ti ti-link', label: 'Referrals' },
  { key: 'communications', icon: 'ti ti-mail', label: 'Communications' },
  { key: 'appointments', icon: 'ti ti-calendar-event', label: 'Appointments' },
  { key: 'alert-queue', icon: 'ti ti-bell-ringing', label: 'Alert Queue' },
  { key: 'consent-tracker', icon: 'ti ti-file-check', label: 'Consent Tracker' },
  { key: 'audit-log', icon: 'ti ti-history', label: 'Audit Log' },
  { key: 'profile', icon: 'ti ti-user-cog', label: 'My profile' },
  { key: 'voice-support', icon: 'ti ti-wave-sine', label: 'Voice support' },
] as const

const SCHOOL_ADMIN_NAV_ITEMS = [
  { key: 'institution', icon: 'ti ti-building-community', label: 'Institution setup' },
  { key: 'institution-students', icon: 'ti ti-users', label: 'Student onboarding' },
  { key: 'institution-counsellors', icon: 'ti ti-stethoscope', label: 'Counsellors' },
  { key: 'assignments', icon: 'ti ti-user-check', label: 'Assignments' },
  { key: 'institution-policy', icon: 'ti ti-settings', label: 'Institution policy' },
  { key: 'consent-tracker', icon: 'ti ti-file-check', label: 'Consent tracker' },
  { key: 'audit-log', icon: 'ti ti-history', label: 'Audit log' },
  { key: 'profile', icon: 'ti ti-user-cog', label: 'My profile' },
  { key: 'voice-support', icon: 'ti ti-wave-sine', label: 'Voice support' },
] as const

const ADMIN_NAV_ITEMS = [
  { key: 'admin', icon: 'ti ti-shield-check', label: 'Dashboard' },
  { key: 'institutions', icon: 'ti ti-building-community', label: 'Institutions' },
  { key: 'workplace-admin', icon: 'ti ti-building-skyscraper', label: 'Workplace pilot' },
  { key: 'counsellors', icon: 'ti ti-stethoscope', label: 'Counsellors' },
  { key: 'consent-tracker', icon: 'ti ti-file-check', label: 'Consent Tracker' },
  { key: 'students', icon: 'ti ti-school', label: 'Students' },
  { key: 'archived-students', icon: 'ti ti-archive', label: 'Archived students' },
  { key: 'audit-log', icon: 'ti ti-history', label: 'Audit' },
  { key: 'alert-queue', icon: 'ti ti-bell-ringing', label: 'Alert Queue' },
  { key: 'communications', icon: 'ti ti-mail', label: 'Communications' },
  { key: 'appointments', icon: 'ti ti-calendar-event', label: 'Appointments' },
  { key: 'voice-support', icon: 'ti ti-wave-sine', label: 'Voice support' },
  { key: 'profile', icon: 'ti ti-user-cog', label: 'My profile' },
]

const COMPANY_ADMIN_NAV_ITEMS = [
  { key: 'workplace', icon: 'ti ti-layout-dashboard', label: 'Overview' },
  { key: 'workplace-setup', icon: 'ti ti-list-check', label: 'Setup & policies' },
  { key: 'workplace-providers', icon: 'ti ti-stethoscope', label: 'Providers' },
  { key: 'workplace-enrollment', icon: 'ti ti-link', label: 'Enrollment' },
  { key: 'workplace-reports', icon: 'ti ti-chart-line', label: 'Aggregate reports' },
  { key: 'workplace-audit', icon: 'ti ti-history', label: 'Audit history' },
  { key: 'voice-support', icon: 'ti ti-wave-sine', label: 'Voice support' },
  { key: 'profile', icon: 'ti ti-user-cog', label: 'Account profile' },
]
const EMPLOYEE_NAV_ITEMS = [
  { key: 'workplace', icon: 'ti ti-home-heart', label: 'My wellbeing' },
  { key: 'workplace-checkins', icon: 'ti ti-clipboard-heart', label: 'Private check-ins' },
  { key: 'workplace-support', icon: 'ti ti-heart-handshake', label: 'Request support' },
  { key: 'workplace-messages', icon: 'ti ti-message-circle', label: 'Provider messages' },
  { key: 'workplace-appointments', icon: 'ti ti-calendar-event', label: 'Appointments' },
  { key: 'voice-support', icon: 'ti ti-wave-sine', label: 'Calm with voice' },
]
const PROVIDER_NAV_ITEMS = [
  { key: 'workplace', icon: 'ti ti-layout-dashboard', label: 'Overview' },
  { key: 'workplace-cases', icon: 'ti ti-briefcase-2', label: 'Shared cases' },
  { key: 'workplace-appointments', icon: 'ti ti-calendar-event', label: 'Appointments' },
  { key: 'voice-support', icon: 'ti ti-wave-sine', label: 'Voice support' },
]

function RolePill({ role }: { role?: string }) {
  const r = role?.toLowerCase() || 'user'
  const styles: Record<string, string> = {
    student: 'bg-[#dbeafe] text-[#1e40af]',
    counsellor: 'bg-[#d1fae5] text-[#065f46]',
    school_admin: 'bg-[#d1fae5] text-[#065f46]',
    admin: 'bg-[#fef3c7] text-[#92400e]',
    company_admin: 'bg-[#dbeafe] text-[#1e40af]',
    workplace_employee: 'bg-[#d1fae5] text-[#065f46]',
    workplace_provider: 'bg-[#ede9fe] text-[#5b21b6]',
  }
  return (
    <div className={`rounded-full px-[8px] py-[2px] text-[0.65rem] font-bold uppercase flex-shrink-0 ${styles[r] || 'bg-[rgba(15,118,110,0.15)] text-[#34d399]'}`}>
      {role || 'User'}
    </div>
  )
}

export default function Sidebar() {
  const { currentPage, setPage, sidebarOpen, sidebarCollapsed, toggleSidebarCollapsed } = useUiStore()
  const { user } = useAuthStore()
  const { reddit, bluesky, mastodon, youtube, file, facebook, twitter, video } = usePlatformStore()
  const referralCount = useCounsellorStore((s) => s.referralCount)
  const {
    notifications, unreadCount, fetchNotifications,
    markRead, markAllRead, fetchPreferences,
  } = useNotificationStore()
  const [openAlertCount, setOpenAlertCount] = useState(0)
  const [showNotifs, setShowNotifs] = useState(false)
  const [copied, setCopied] = useState(false)
  const notifRef = useRef<HTMLDivElement>(null)

  const role = user?.role_type?.toLowerCase() || 'student'
  const isCounsellor = role === 'counsellor' || role === 'school_admin'
  const isAdmin = role === 'admin'
  const isAdult = user?.user_category === 'adult'
  const isInstitutionStudent = user?.user_category === 'institution_managed'
  const isGuardian = user?.user_category === 'parent' || role === 'parent'
  const isWorkplace = ['company_admin', 'workplace_employee', 'workplace_provider'].includes(role)
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const isCollapsed = isDesktop && sidebarCollapsed

  const navItems = isWorkplace
    ? role === 'company_admin' ? COMPANY_ADMIN_NAV_ITEMS : role === 'workplace_provider' ? PROVIDER_NAV_ITEMS : EMPLOYEE_NAV_ITEMS
    : isAdmin
    ? ADMIN_NAV_ITEMS.map((item) =>
        item.key === 'alert-queue' && openAlertCount > 0 ? { ...item, badge: openAlertCount } : item
      )
    : role === 'school_admin'
      ? SCHOOL_ADMIN_NAV_ITEMS
      : isCounsellor
      ? COUNSELLOR_NAV_BASE.map((item) =>
          item.key === 'alert-queue' && openAlertCount > 0 ? { ...item, badge: openAlertCount } : item
        )
      : isGuardian
        ? GUARDIAN_NAV_ITEMS
        : isAdult
        ? ADULT_STUDENT_NAV_ITEMS
        : isInstitutionStudent
          ? INSTITUTION_STUDENT_NAV_ITEMS
          : STUDENT_NAV_ITEMS

  const analysedPlatforms: Record<string, boolean> = {
    reddit: Boolean(reddit),
    bluesky: Boolean(bluesky),
    mastodon: Boolean(mastodon),
    youtube: Boolean(youtube),
    file: Boolean(file),
    facebook: Boolean(facebook),
    twitter: Boolean(twitter),
    video: Boolean(video?.ok),
  }

  const sectionLabel = isWorkplace ? (role === 'company_admin' ? 'Company admin' : role === 'workplace_provider' ? 'Care provider' : 'Employee') : isAdmin ? 'Admin' : role === 'school_admin' ? 'School Admin' : isCounsellor ? 'Counsellor' : 'Student'

  // Fetch open alert count for counsellors and admins
  useEffect(() => {
    if (!isCounsellor && !isAdmin) return
    const fetchCount = async () => {
      try {
        const alerts = await getAlerts('OPEN')
        setOpenAlertCount(alerts.length)
      } catch /* eslint-disable no-empty */ {}
    }
    fetchCount()
    const interval = setInterval(fetchCount, 60000)
    return () => clearInterval(interval)
  }, [isCounsellor, isAdmin])

  // Poll notifications every 30 seconds + fetch preferences
  useEffect(() => {
    if (isWorkplace) return
    fetchNotifications()
    fetchPreferences()
    const interval = setInterval(fetchNotifications, 30000)
    return () => clearInterval(interval)
  }, [fetchNotifications, fetchPreferences, isWorkplace])

  // Close notification panel on outside click
  useEffect(() => {
    if (!showNotifs) return
    const handler = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setShowNotifs(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showNotifs])

  const handleCopyReferral = () => {
    const code = user?.referral_code
    if (!code) return
    const link = `${window.location.origin}/?ref=${code}`
    navigator.clipboard.writeText(link).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const initials = user?.name
    ? user.name.split(' ').map((p: string) => p[0]).join('').toUpperCase().slice(0, 2)
    : 'MG'

  return (
    <div
      className={`fixed md:static inset-y-0 left-0 z-40 flex-shrink-0 bg-[#080d12] flex flex-col border-r border-[#161d26] transition-all duration-200 ${
        isCollapsed ? 'w-[60px]' : 'w-[240px]'
      }`}
      style={{
        transform: isDesktop
          ? 'none'
          : sidebarOpen
          ? 'translateX(0)'
          : 'translateX(-100%)',
      }}
    >
      {/* Brand + notification bell */}
      <div className={`flex items-center gap-[10px] border-b border-[#161d26] ${isCollapsed ? 'justify-center px-[8px] py-[14px]' : 'px-[16px] py-[14px]'}`}>
        <div className="w-[32px] h-[32px] rounded-lg bg-gradient-to-br from-[#0F766E] to-[#1D9E75] flex items-center justify-center text-white font-extrabold text-[0.82rem] flex-shrink-0">
          MG
        </div>
        {!isCollapsed && <div className="text-[#f3f4f6] text-[1rem] font-bold tracking-tight flex-1">MindGuard</div>}
        {/* Notification bell */}
        {!isCollapsed && (
          <div className="relative" ref={notifRef}>
            <button
              onClick={() => setShowNotifs((v) => !v)}
              className="relative w-[28px] h-[28px] flex items-center justify-center rounded-[6px] hover:bg-[#161d26] transition-colors cursor-pointer bg-transparent border-none text-[#6b7280] hover:text-[#d1d5db]"
            >
              <i className="ti ti-bell text-[17px]" />
              {unreadCount > 0 && (
                <span className="absolute top-[-3px] right-[-3px] bg-[#ef4444] text-white text-[0.55rem] font-bold min-w-[16px] h-[16px] rounded-full flex items-center justify-center px-[3px]">
                  {unreadCount > 9 ? '9+' : unreadCount}
                </span>
              )}
            </button>
            {/* Notifications panel */}
            {showNotifs && (
              <div className="absolute top-[36px] right-0 w-[260px] sm:w-[320px] max-w-[90vw] bg-white rounded-[12px] border border-[rgba(229,231,235,0.7)] shadow-xl z-50">
                <div className="flex items-center justify-between px-[14px] py-[10px] border-b border-[#f3f4f6]">
                  <span className="text-[0.85rem] font-bold text-[#1f2937]">Notifications</span>
                  <div className="flex items-center gap-[6px]">
                    {unreadCount > 0 && (
                      <button onClick={markAllRead} className="text-[0.72rem] text-[#0F766E] font-semibold cursor-pointer bg-transparent border-none hover:underline">
                        Mark all read
                      </button>
                    )}
                    <button
                      onClick={() => { setShowNotifs(false); setPage('notification-preferences') }}
                      className="text-[0.72rem] text-[#6b7280] font-semibold cursor-pointer bg-transparent border-none hover:text-[#0F766E]"
                      title="Notification settings"
                    >
                      <i className="ti ti-settings text-[14px]" />
                    </button>
                  </div>
                </div>
                <div className="max-h-[320px] overflow-y-auto">
                  {notifications.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-[28px] text-[#9ca3af] text-[0.8rem]">
                      <i className="ti ti-bell-off text-[24px] mb-[6px]" />
                      No notifications yet
                    </div>
                  ) : (
                    notifications.slice(0, 30).map((n) => {
                      const icon = NOTIFICATION_TYPE_ICONS[n.type] || 'ti ti-bell'
                      const typeLabel = NOTIFICATION_TYPE_LABELS[n.type] || n.type
                      return (
                        <div
                          key={n.id}
                          className={`flex items-start gap-[10px] px-[14px] py-[10px] border-b border-[#f9fafb] cursor-pointer hover:bg-[#f9fafb] transition-colors ${!n.read ? 'bg-[#f0fdf9]' : ''}`}
                          onClick={() => markRead(n.id)}
                        >
                          <div className={`w-[28px] h-[28px] rounded-full flex items-center justify-center flex-shrink-0 ${
                            n.type === 'alert' ? 'bg-[#fef2f2] text-[#dc2626]' :
                            n.type === 'group_message' ? 'bg-[#f5f3ff] text-[#7c3aed]' :
                            n.type === 'message' ? 'bg-[#f0fdfa] text-[#0F766E]' :
                            n.type === 'broadcast' ? 'bg-[#fef3c7] text-[#d97706]' :
                            'bg-[#f3f4f6] text-[#6b7280]'
                          }`}>
                            <i className={`${icon} text-[14px]`} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-[4px]">
                              <span className="text-[0.62rem] font-medium text-[#6b7280] uppercase">{typeLabel}</span>
                              {!n.read && <div className="w-[6px] h-[6px] rounded-full bg-[#0F766E]" />}
                            </div>
                            <div className="text-[0.8rem] font-semibold text-[#1f2937] truncate">{n.title}</div>
                            <div className="text-[0.73rem] text-[#6b7280] mt-[2px] line-clamp-2">{n.message}</div>
                            <div className="text-[0.65rem] text-[#9ca3af] mt-[3px]">
                              {new Date(n.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                            </div>
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Section label */}
      {!isCollapsed && (
        <div className="text-[#4b5563] text-[0.65rem] font-bold uppercase tracking-[0.12em] px-[16px] pt-[14px] pb-[6px]">
          {sectionLabel}
        </div>
      )}

      {/* Nav items */}
      <div className="flex-1 overflow-y-auto py-[4px]">
        {(navItems as { key: string; icon: string; label: string; badge?: number }[]).map((item) => {
          const isActive = currentPage === item.key
          const isAnalysed = analysedPlatforms[item.key]
          return (
            <div
              key={item.key}
              onClick={() => setPage(item.key as PageKey)}
              className={`relative flex items-center cursor-pointer transition-colors duration-150 ${
                isCollapsed
                  ? 'justify-center mx-[6px] py-[10px] rounded-[8px]'
                  : 'gap-[10px] px-[14px] py-[9px] mx-[8px] my-[1px] rounded-[8px] text-[0.82rem]'
              } ${
                isActive
                  ? 'bg-[#0f2724] text-[#e2f4f1] font-semibold'
                  : 'text-[#6b7280] hover:bg-[#0e1520] hover:text-[#d1d5db]'
              } ${isActive && !isCollapsed ? 'border-l-[3px] border-[#1D9E75] pl-[11px]' : ''}`}
            >
              <i className={`${item.icon} text-[18px] ${isActive ? 'text-[#34d399]' : ''}`} />
              {!isCollapsed && <span className="flex-1">{item.label}</span>}
              {isAnalysed && (
                <span
                  className={`flex items-center justify-center rounded-full bg-[#0F766E] text-white ${
                    isCollapsed ? 'absolute right-[7px] top-[7px] h-[8px] w-[8px]' : 'h-[18px] w-[18px]'
                  }`}
                  title={`${item.label} analysed`}
                >
                  {!isCollapsed && <i className="ti ti-check text-[12px]" />}
                </span>
              )}
              {!isCollapsed && (item.key === 'referrals' ? (
                referralCount > 0 && (
                  <span className="bg-[#ef4444] text-white text-[0.6rem] font-bold px-[6px] py-[1px] rounded-full min-w-[18px] text-center">
                    {referralCount}
                  </span>
                )
              ) : item.badge != null && item.badge > 0 ? (
                <span className="bg-[#ef4444] text-white text-[0.6rem] font-bold px-[6px] py-[1px] rounded-full min-w-[18px] text-center">
                  {item.badge}
                </span>
              ) : null)}
            </div>
          )
        })}
      </div>

      {/* Collapse toggle - desktop only */}
      <div className="hidden md:block px-[8px] py-[4px]">
        <button
          onClick={toggleSidebarCollapsed}
          className="w-full flex items-center justify-center py-[6px] rounded-[8px] text-[#6b7280] hover:bg-[#0e1520] hover:text-[#d1d5db] transition-colors cursor-pointer bg-transparent border-none"
          aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <i className={`ti ${sidebarCollapsed ? 'ti-chevron-right' : 'ti-chevron-left'} text-[16px]`} />
        </button>
      </div>

      {/* Referral link copy */}
      {!isCollapsed && user?.referral_code && (
        <div className="px-[12px] py-[8px] border-t border-[#161d26]">
          <button
            onClick={handleCopyReferral}
            title={`Referral code: ${user.referral_code}`}
            className="w-full flex items-center gap-[8px] px-[10px] py-[7px] rounded-[8px] text-[0.73rem] font-medium text-[#6b7280] hover:bg-[#0e1520] hover:text-[#d1d5db] transition-colors cursor-pointer bg-transparent border border-[#1a2332] group"
          >
            <i className={`${copied ? 'ti ti-circle-check text-[#34d399]' : 'ti ti-link'} text-[15px]`} />
            <span className="flex-1 text-left truncate">
              {copied ? 'Link copied!' : `Invite: ${user.referral_code}`}
            </span>
            <i className="ti ti-copy text-[13px] opacity-0 group-hover:opacity-100 transition-opacity" />
          </button>
        </div>
      )}

      {/* User footer */}
      <div className={`px-[16px] py-[12px] border-t border-[#161d26] flex items-center ${isCollapsed ? 'justify-center' : 'gap-[10px]'}`}>
        <div className="w-[34px] h-[34px] rounded-full bg-gradient-to-br from-[#0F766E] to-[#1D9E75] flex items-center justify-center text-white font-bold text-[0.78rem] flex-shrink-0">
          {initials}
        </div>
        {!isCollapsed && (
          <>
            <div className="flex-1 min-w-0">
              <div className="text-[#f3f4f6] text-[0.85rem] font-semibold truncate">
                {user?.name || 'User'}
              </div>
              <div className="text-[#4b5563] text-[0.7rem] truncate">
                {user?.email || ''}
              </div>
            </div>
            <RolePill role={user?.role_type} />
          </>
        )}
      </div>
      <button
        onClick={() => {
          clearToken()
          useAuthStore.getState().logout()
        }}
        className={`w-full py-[10px] text-[#6b7280] text-[0.75rem] font-medium border-t border-[#161d26] cursor-pointer hover:text-[#d1d5db] hover:bg-[#0e1520] transition-colors flex items-center justify-center gap-[6px] bg-transparent`}
      >
        <i className="ti ti-logout text-[15px]" />
        {!isCollapsed && 'Sign out'}
      </button>
    </div>
  )
}

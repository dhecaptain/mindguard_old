import { useUiStore, useAuthStore } from '../../store'
import { useCallback, useEffect, useState } from 'react'

const PAGE_TITLES: Record<string, string> = {
  dashboard: 'Dashboard',
  'text-image': 'Text / Image Analysis',
  batch: 'Batch Analysis',
  reddit: 'Reddit Analysis',
  video: 'Video Analysis',
  bluesky: 'Bluesky Analysis',
  mastodon: 'Mastodon Analysis',
  youtube: 'YouTube Analysis',
  file: 'File Upload Analysis',
  facebook: 'Facebook Analysis',
  twitter: 'Twitter / X Analysis',
  unified: 'Multi-Platform Profile',
  resources: 'Crisis Resources',
  team: 'Team',
  'counsellor-dashboard': 'MindGuard',
  students: 'Student Management',
  referrals: 'Referrals',
  communications: 'Communications',
  'alert-queue': 'MindGuard',
  'consent-tracker': 'MindGuard',
  'audit-log': 'MindGuard',
  admin: 'Admin Panel',
  'notification-preferences': 'Notification Preferences',
  'guest-analysis': 'Guest Analysis',
  'voice-support': 'Voice Grounding Companion',
  'workplace': 'Workplace Wellbeing',
  'workplace-setup': 'Workplace Setup',
  'workplace-providers': 'Independent Providers',
  'workplace-enrollment': 'Employee Enrollment',
  'workplace-reports': 'Protected Aggregate Reports',
  'workplace-audit': 'Workplace Audit History',
  'workplace-checkins': 'Private Check-ins',
  'workplace-support': 'Provider Support',
  'workplace-cases': 'Shared Workplace Cases',
  'workplace-messages': 'Private Provider Messages',
  'workplace-appointments': 'Workplace Appointments',
}

export default function TopBar() {
  const { currentPage, unreadCount, toggleSidebar } = useUiStore()
  const { user } = useAuthStore()
  const handleToggle = useCallback(() => toggleSidebar(), [toggleSidebar])
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768)

  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])

  const title = PAGE_TITLES[currentPage] || 'MindGuard'
  const initials = user?.name
    ? user.name.split(' ').map((p: string) => p[0]).join('').toUpperCase().slice(0, 2)
    : 'MG'
  const displayName = user?.name?.split(' ')[0] || user?.email?.split('@')[0] || 'User'

  return (
    <div className="h-[52px] bg-white/95 border-b border-[rgba(229,231,235,0.8)] flex items-center justify-between px-[14px] md:px-[24px] flex-shrink-0">
      <div className="flex items-center gap-[10px]">
        {isMobile && (
          <button
            onClick={handleToggle}
            className="flex items-center justify-center w-[34px] h-[34px] rounded-[7px] text-[#6b7280] hover:bg-[#f1f5f9] transition-colors bg-transparent border-none cursor-pointer flex-shrink-0"
            aria-label="Toggle menu"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
        )}
        <div className="text-[0.95rem] font-semibold text-[#1f2937]">{title}</div>
      </div>
      <div className="flex items-center gap-[12px]">
        <div className="relative text-[#6b7280]">
          <i className="ti ti-bell text-[19px]" />
          {unreadCount > 0 && (
            <div className="absolute -top-[1px] -right-[1px] w-[7px] h-[7px] bg-[#ef4444] rounded-full border-[1.5px] border-white" />
          )}
        </div>
        <div className="flex items-center gap-[8px]">
          <span className="text-[0.82rem] text-[#6b7280] font-medium">{displayName}</span>
          <div className="w-[30px] h-[30px] rounded-full bg-gradient-to-br from-[#0F766E] to-[#1D9E75] flex items-center justify-center text-white font-bold text-[0.72rem]">
            {initials}
          </div>
        </div>
      </div>
    </div>
  )
}

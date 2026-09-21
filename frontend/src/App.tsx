import { useEffect, useState, useCallback, useRef } from 'react'
import { useAuthStore, useUiStore } from './store'
import { getMe, logout as apiLogout } from './api/auth'
import { initSupabase } from './lib/supabase'
import { getToken, clearToken } from './lib/tokenStorage'
import { useIdleTimeout } from './hooks/useIdleTimeout'
import SignInPage from './components/auth/SignInPage'
import TermsPage from './components/auth/TermsPage'
import MainLayout from './components/layout/MainLayout'
import AuthCallbackPage from './pages/AuthCallbackPage'
import ConsentPortalPage from './pages/ConsentPortalPage'
import InvitePage from './pages/InvitePage'
import OnboardingPage from './pages/OnboardingPage'
import MyAccountsPage from './pages/MyAccountsPage'
import AdultDashboardPage from './pages/AdultDashboardPage'
import AdultAccountsPage from './pages/AdultAccountsPage'
import AnalysisHistoryPage from './pages/AnalysisHistoryPage'
import AnalysisSessionPage from './pages/AnalysisSessionPage'
import DemoRequestPage from './pages/DemoRequestPage'
import DashboardPage from './pages/DashboardPage'
import TextImageAnalysisPage from './pages/TextImageAnalysisPage'
import BatchAnalysisPage from './pages/BatchAnalysisPage'
import RedditPage from './pages/RedditPage'
import VideoPage from './pages/VideoPage'
import BlueskyPage from './pages/BlueskyPage'
import MastodonPage from './pages/MastodonPage'
import YouTubePage from './pages/YouTubePage'
import FileUploadPage from './pages/FileUploadPage'
import FacebookPage from './pages/FacebookPage'
import TwitterPage from './pages/TwitterPage'
import MultiPlatformPage from './pages/MultiPlatformPage'
import CrisisResourcesPage from './pages/CrisisResourcesPage'
import TeamPage from './pages/TeamPage'
import CounsellorDashboardPage from './pages/CounsellorDashboardPage'
import StudentManagementPage from './pages/StudentManagementPage'
import ReferralsPage from './pages/ReferralsPage'
import CommunicationsPage from './pages/CommunicationsPage'
import StudentCommunicationsPage from './pages/StudentCommunicationsPage'
import AlertQueuePage from './pages/AlertQueuePage'
import ConsentTrackerPage from './pages/ConsentTrackerPage'
import AuditLogPage from './pages/AuditLogPage'
import AdminPage from './pages/AdminPage'
import AdminCounsellorsPage from './pages/AdminCounsellorsPage'
import NotificationPreferencesPage from './pages/NotificationPreferencesPage'
import AppointmentsPage from './pages/AppointmentsPage'
import LandingPage from './pages/LandingPage'
import InstitutionWorkspacePage from './pages/InstitutionWorkspacePage'
import AdminInstitutionsPage from './pages/AdminInstitutionsPage'

const IDLE_TIMEOUT_MS = 15 * 60 * 1000   // 15 minutes
const IDLE_WARNING_MS = 60 * 1000         // warn 1 minute before

function IdleWarningModal({ countdown, onStay, onLogout }: { countdown: number; onStay: () => void; onLogout: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[9999]">
      <div className="bg-white rounded-[16px] p-[32px] w-[380px] max-w-[90vw] shadow-2xl text-center">
        <div className="w-[56px] h-[56px] rounded-full bg-[#fef3c7] flex items-center justify-center mx-auto mb-[16px]">
          <i className="ti ti-clock text-[28px] text-[#d97706]" />
        </div>
        <h3 className="text-[1.1rem] font-bold text-[#1f2937] mb-[8px]">Session expiring soon</h3>
        <p className="text-[0.85rem] text-[#6b7280] mb-[6px]">
          You've been inactive. Your session will end in
        </p>
        <div className="text-[2rem] font-bold text-[#d97706] mb-[20px]">{countdown}s</div>
        <div className="flex gap-[10px]">
          <button
            onClick={onLogout}
            className="flex-1 px-[14px] py-[10px] rounded-[8px] text-[0.85rem] font-semibold text-[#6b7280] border border-[#d1d5db] cursor-pointer hover:bg-[#f9fafb] bg-transparent"
          >
            Sign out
          </button>
          <button
            onClick={onStay}
            className="flex-1 px-[14px] py-[10px] rounded-[8px] text-[0.85rem] font-semibold text-white bg-[#0F766E] cursor-pointer hover:bg-[#115E59]"
          >
            Stay signed in
          </button>
        </div>
      </div>
    </div>
  )
}

function PageRouter() {
  const { currentPage } = useUiStore()
  const role = useAuthStore((s) => s.user?.role_type?.toLowerCase())
  const userCategory = useAuthStore((s) => s.user?.user_category)

  if (role === 'admin') {
    switch (currentPage) {
      case 'admin': return <AdminPage />
      case 'counsellors': return <AdminCounsellorsPage />
      case 'institutions': return <AdminInstitutionsPage />
      case 'assignments': return <AdminCounsellorsPage />
      case 'counsellor-dashboard': return <CounsellorDashboardPage />
      case 'students': return <StudentManagementPage />
      case 'batch': return <BatchAnalysisPage />
      case 'reddit': return <RedditPage />
      case 'video': return <VideoPage />
      case 'bluesky': return <BlueskyPage />
      case 'mastodon': return <MastodonPage />
      case 'youtube': return <YouTubePage />
      case 'file': return <FileUploadPage />
      case 'facebook': return <FacebookPage />
      case 'twitter': return <TwitterPage />
      case 'unified': return <MultiPlatformPage />
      case 'referrals': return <ReferralsPage />
      case 'communications': return <CommunicationsPage />
      case 'appointments': return <AppointmentsPage />
      case 'alert-queue': return <AlertQueuePage />
      case 'consent-tracker': return <ConsentTrackerPage />
      case 'audit-log': return <AuditLogPage />
      case 'notification-preferences': return <NotificationPreferencesPage />
      default: return <AdminPage />
    }
  }

  if (role === 'counsellor' || role === 'school_admin') {
    switch (currentPage) {
      case 'institution': return <InstitutionWorkspacePage />
      case 'counsellor-dashboard': return <CounsellorDashboardPage />
      case 'students': return <StudentManagementPage />
      case 'batch': return <BatchAnalysisPage />
      case 'reddit': return <RedditPage />
      case 'video': return <VideoPage />
      case 'bluesky': return <BlueskyPage />
      case 'mastodon': return <MastodonPage />
      case 'youtube': return <YouTubePage />
      case 'file': return <FileUploadPage />
      case 'facebook': return <FacebookPage />
      case 'twitter': return <TwitterPage />
      case 'unified': return <MultiPlatformPage />
      case 'referrals': return <ReferralsPage />
      case 'communications': return <CommunicationsPage />
      case 'appointments': return <AppointmentsPage />
      case 'alert-queue': return <AlertQueuePage />
      case 'consent-tracker': return <ConsentTrackerPage />
      case 'audit-log': return <AuditLogPage />
      case 'notification-preferences': return <NotificationPreferencesPage />
      default: return <CounsellorDashboardPage />
    }
  }

  if (userCategory === 'adult') {
    return <AdultPageRouter />
  }

  switch (currentPage) {
    case 'dashboard': return <DashboardPage />
    case 'text-image': return <TextImageAnalysisPage />
    case 'resources': return <CrisisResourcesPage />
    case 'team': return <TeamPage />
    case 'communications': return <StudentCommunicationsPage />
    case 'appointments': return <AppointmentsPage />
    case 'my-accounts': return <MyAccountsPage />
    case 'notification-preferences': return <NotificationPreferencesPage />
    default: return <DashboardPage />
  }
}

function AdultPageRouter() {
  const { currentPage } = useUiStore()

  switch (currentPage) {
    case 'dashboard': return <AdultDashboardPage />
    case 'my-accounts': return <AdultAccountsPage />
    case 'self-history': return <AnalysisHistoryPage />
    case 'self-session': return <AnalysisSessionPage />
    case 'text-image': return <TextImageAnalysisPage />
    case 'resources': return <CrisisResourcesPage />
    case 'team': return <TeamPage />
    case 'communications': return <StudentCommunicationsPage />
    case 'appointments': return <AppointmentsPage />
    case 'notification-preferences': return <NotificationPreferencesPage />
    default: return <AdultDashboardPage />
  }
}

function AuthenticatedApp() {
  const { logout } = useAuthStore()
  const [showWarning, setShowWarning] = useState(false)
  const [countdown, setCountdown] = useState(60)
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const handleLogout = useCallback(async () => {
    setShowWarning(false)
    try { await apiLogout() } catch {/* eslint-disable no-empty */}{}
    logout()
  }, [logout])

  const handleWarning = useCallback(() => {
    setShowWarning(true)
    setCountdown(60)
    countdownRef.current = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          clearInterval(countdownRef.current!)
          handleLogout()
          return 0
        }
        return c - 1
      })
    }, 1000)
  }, [handleLogout])

  const { reset } = useIdleTimeout(handleWarning, handleLogout, IDLE_TIMEOUT_MS, IDLE_WARNING_MS)

  const handleStay = useCallback(() => {
    setShowWarning(false)
    if (countdownRef.current) clearInterval(countdownRef.current)
    reset()
  }, [reset])

  return (
    <>
      <MainLayout>
        <PageRouter />
      </MainLayout>
      {showWarning && (
        <IdleWarningModal countdown={countdown} onStay={handleStay} onLogout={handleLogout} />
      )}
    </>
  )
}

export default function App() {
  const { authenticated, termsAccepted, loading, setAuth, setTermsAccepted, setLoading } = useAuthStore()
  const setPage = useUiStore((s) => s.setPage)
  const [initialized, setInitialized] = useState(false)

  useEffect(() => {
    const boot = async () => {
      await initSupabase()
      const token = getToken()
      if (token) {
        try {
          const user = await getMe()
          setAuth(user)
          setTermsAccepted(Boolean(user.terms_accepted))
          if (user.role_type?.toLowerCase() === 'counsellor' || user.role_type?.toLowerCase() === 'school_admin') {
            setPage('counsellor-dashboard')
          } else if (user.role_type?.toLowerCase() === 'admin') {
            setPage('admin')
          }
        } catch {
          clearToken()
        }
      }
      setLoading(false)
      setInitialized(true)
    }
    boot()
  }, [setAuth, setLoading, setPage, setTermsAccepted])

  if (!initialized || loading) {
    return (
      <div className="min-h-screen bg-[#f7f9fb] flex items-center justify-center">
        <div className="flex flex-col items-center gap-[12px]">
          <div className="w-[32px] h-[32px] border-[2.5px] border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin" />
          <span className="text-[0.9rem] text-[#6b7280]">Loading MindGuard...</span>
        </div>
      </div>
    )
  }

  if (window.location.pathname === '/auth/callback' || window.location.pathname.startsWith('/auth/callback/')) {
    if (!authenticated) return <AuthCallbackPage />
  }

  if (window.location.pathname.startsWith('/consent/')) {
    const token = window.location.pathname.split('/consent/')[1]?.split('/')[0] || ''
    return <ConsentPortalPage token={token} />
  }

  if (window.location.pathname === '/invite' || window.location.pathname.startsWith('/invite/')) {
    return <InvitePage />
  }

  if (window.location.pathname === '/demo' || window.location.pathname === '/demo/') {
    return <DemoRequestPage />
  }

  if (!authenticated) {
    if (window.location.pathname === '/' || window.location.pathname === '') {
      return <LandingPage />
    }
    return <SignInPage onSuccess={() => {}} />
  }

  if (!termsAccepted) {
    return <TermsPage onAccepted={() => {}} />
  }

  const userCat = (useAuthStore.getState().user as unknown as { user_category?: string })?.user_category
  const roleType = (useAuthStore.getState().user as unknown as { role_type?: string })?.role_type
  const isStaff = roleType === 'admin' || roleType === 'school_admin' || roleType === 'counsellor' || userCat === 'staff'
  if (!isStaff && (userCat === 'pending' || !userCat)) {
    return <OnboardingPage onComplete={() => window.location.reload()} />
  }

  return <AuthenticatedApp />
}

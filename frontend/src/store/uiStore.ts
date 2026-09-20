import { create } from 'zustand'
import type { PlatformResult, VideoResult, Notification } from '../types'

export type PageKey =
  | 'dashboard' | 'text-image' | 'batch' | 'reddit' | 'video' | 'bluesky' | 'mastodon'
  | 'youtube' | 'file' | 'facebook' | 'twitter' | 'unified'
  | 'resources' | 'team'
  | 'students' | 'referrals' | 'communications' | 'counsellor-dashboard'
  | 'appointments'
  | 'alert-queue' | 'consent-tracker' | 'audit-log'
  | 'admin' | 'counsellors' | 'institutions' | 'assignments' | 'my-accounts'
  | 'institution'
  | 'notification-preferences'
  | 'self-history' | 'self-session'

function _initialPage(): PageKey {
  const key = window.location.hash.replace(/^#\/?/, '')
  return key === 'consent-tracker' ? 'consent-tracker' : 'dashboard'
}

interface UiState {
  currentPage: PageKey
  notifications: Notification[]
  unreadCount: number
  sidebarOpen: boolean
  sidebarCollapsed: boolean
  setPage: (p: PageKey) => void
  setNotifications: (n: Notification[]) => void
  markRead: (id: string) => void
  toggleSidebar: () => void
  setSidebarOpen: (v: boolean) => void
  toggleSidebarCollapsed: () => void
}

export const useUiStore = create<UiState>((set) => ({
  currentPage: _initialPage(),
  notifications: [],
  unreadCount: 0,
  sidebarOpen: false,
  sidebarCollapsed: false,
  setPage: (p) => set({ currentPage: p, sidebarOpen: false }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarOpen: (v) => set({ sidebarOpen: v }),
  toggleSidebarCollapsed: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setNotifications: (n) =>
    set({ notifications: n, unreadCount: n.filter((x) => !x.read_by?.length).length }),
  markRead: (id) =>
    set((state) => ({
      notifications: state.notifications.map((n) =>
        n.id === id ? { ...n, read_by: ['me'] } : n
      ),
      unreadCount: Math.max(0, state.unreadCount - 1),
    })),
}))

interface PlatformState {
  reddit: PlatformResult | null
  bluesky: PlatformResult | null
  mastodon: PlatformResult | null
  youtube: PlatformResult | null
  facebook: PlatformResult | null
  twitter: PlatformResult | null
  file: PlatformResult | null
  video: VideoResult | null
  loading: boolean
  setPlatformResult: (key: string, result: PlatformResult | VideoResult | null) => void
  setLoading: (v: boolean) => void
  clearAll: () => void
}

export const usePlatformStore = create<PlatformState>((set) => ({
  reddit: null,
  bluesky: null,
  mastodon: null,
  youtube: null,
  facebook: null,
  twitter: null,
  file: null,
  video: null,
  loading: false,
  setPlatformResult: (key: string, result: PlatformResult | VideoResult | null) => set({ [key]: result }),
  setLoading: (v) => set({ loading: v }),
  clearAll: () =>
    set({
      reddit: null, bluesky: null, mastodon: null, youtube: null,
      facebook: null, twitter: null, file: null, video: null,
    }),
}))

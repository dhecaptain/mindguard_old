import { create } from 'zustand'
import type { StudentDTO, Referral, Conversation, DashboardData, StudentDetail } from '../api/counsellor'
import type { Group, GroupMessage, GroupConversationPreview, DirectMessage } from '../types'

interface CounsellorState {
  students: StudentDTO[]
  studentDetail: StudentDetail | null
  referrals: Referral[]
  conversations: Conversation[]
  activeConversation: string | null
  messages: Record<string, DirectMessage[]>
  dashboard: DashboardData | null
  referralCount: number
  loading: boolean
  error: string | null
  requestedStudentId: string | null
  analysisStudentId: string | null

  // Group messaging
  groups: Group[]
  groupConversations: GroupConversationPreview[]
  activeGroupId: string | null
  groupMessages: Record<string, GroupMessage[]>

  setStudents: (students: StudentDTO[]) => void
  setStudentDetail: (d: StudentDetail | null) => void
  setReferrals: (referrals: Referral[]) => void
  addReferral: (r: Referral) => void
  updateReferralStatus: (id: string, status: string, notes?: string) => void
  setConversations: (conversations: Conversation[]) => void
  setActiveConversation: (id: string | null) => void
  setMessages: (otherId: string, messages: DirectMessage[]) => void
  addMessage: (otherId: string, msg: DirectMessage) => void
  setDashboard: (d: DashboardData | null) => void
  setReferralCount: (n: number) => void
  updateStudentStatus: (id: string, status: string) => void
  setLoading: (v: boolean) => void
  setError: (e: string | null) => void
  requestStudentWorkspace: (id: string | null) => void
  setAnalysisStudentId: (id: string | null) => void

  // Group actions
  setGroups: (groups: Group[]) => void
  setGroupConversations: (convs: GroupConversationPreview[]) => void
  setActiveGroupId: (id: string | null) => void
  setGroupMessages: (groupId: string, messages: GroupMessage[]) => void
  addGroupMessage: (groupId: string, msg: GroupMessage) => void
  clearMessaging: () => void
}

export const useCounsellorStore = create<CounsellorState>((set) => ({
  students: [],
  studentDetail: null,
  referrals: [],
  conversations: [],
  activeConversation: null,
  messages: {},
  dashboard: null,
  referralCount: 0,
  loading: false,
  error: null,
  requestedStudentId: null,
  analysisStudentId: null,

  // Group messaging
  groups: [],
  groupConversations: [],
  activeGroupId: null,
  groupMessages: {},

  setStudents: (students) => set({ students }),
  setStudentDetail: (d) => set({ studentDetail: d }),
  setReferrals: (referrals) => set({ referrals, referralCount: referrals.filter((r) => r.status === 'open').length }),
  addReferral: (r) => set((s) => ({ referrals: [r, ...s.referrals], referralCount: s.referralCount + 1 })),
  updateReferralStatus: (id, status, notes) =>
    set((s) => {
      const updated = s.referrals.map((r) => (r.id === id ? { ...r, status, notes: notes ?? r.notes } : r))
      return {
        referrals: updated,
        referralCount: updated.filter((r) => r.status === 'open').length,
      }
    }),
  setConversations: (conversations) => set({ conversations }),
  setActiveConversation: (id) => set({ activeConversation: id }),
  setMessages: (otherId, messages) =>
    set((s) => ({ messages: { ...s.messages, [otherId]: messages } })),
  addMessage: (otherId, msg) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [otherId]: [...(s.messages[otherId] || []), msg],
      },
    })),
  setDashboard: (d) => set({ dashboard: d }),
  setReferralCount: (n) => set({ referralCount: n }),
  updateStudentStatus: (id, status) =>
    set((s) => ({
      students: s.students.map((st) => (st.id === id ? { ...st, status } : st)),
    })),
  setLoading: (v) => set({ loading: v }),
  setError: (e) => set({ error: e }),
  requestStudentWorkspace: (id) => set({ requestedStudentId: id }),
  setAnalysisStudentId: (id) => set({ analysisStudentId: id }),

  // Group actions
  setGroups: (groups) => set({ groups }),
  setGroupConversations: (convs) => set({ groupConversations: convs }),
  setActiveGroupId: (id) => set({ activeGroupId: id }),
  setGroupMessages: (groupId, messages) =>
    set((s) => ({ groupMessages: { ...s.groupMessages, [groupId]: messages } })),
  addGroupMessage: (groupId, msg) =>
    set((s) => ({
      groupMessages: {
        ...s.groupMessages,
        [groupId]: [...(s.groupMessages[groupId] || []), msg],
      },
    })),
  clearMessaging: () =>
    set({
      activeConversation: null,
      activeGroupId: null,
      messages: {},
      groupMessages: {},
      conversations: [],
      groupConversations: [],
    }),
}))

import { useEffect, useState, useRef, useCallback } from 'react'
import { useAuthStore, useNotificationStore } from '../store'
import {
  getMyConversations, sendDirectMessage, getDirectConversation,
  getGroupMessages, sendGroupMessage, markGroupRead,
  subscribeToMessageEvents,
} from '../api/counsellor'
import type { Conversation, DirectMessage, GroupConversationPreview, GroupMessage } from '../types'
import NewMessageDialog, { type UserEntry } from '../components/shared/NewMessageDialog'

function formatTime(d: string) {
  if (!d) return ''
  const dt = new Date(d)
  const now = new Date()
  const diff = now.getTime() - dt.getTime()
  if (diff < 86400000) return dt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

type ChatMode = 'direct' | 'group'

export default function StudentCommunicationsPage() {
  const user = useAuthStore((s) => s.user)
  const isGuardian = user?.role_type === 'parent' || user?.user_category === 'parent'
  const isGroupMuted = useNotificationStore((s) => s.isGroupMuted)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [groupConversations, setGroupConversations] = useState<GroupConversationPreview[]>([])
  const [activeConversation, setActiveConversation] = useState<string | null>(null)
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null)
  const [chatMode, setChatMode] = useState<ChatMode>('direct')
  const [directMessages, setDirectMessages] = useState<DirectMessage[]>([])
  const [groupMessages, setGroupMessages] = useState<GroupMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [showNewMessage, setShowNewMessage] = useState(false)
  const [search, setSearch] = useState('')
  const [pageError, setPageError] = useState('')
  const [liveConnected, setLiveConnected] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const loadData = useCallback(async () => {
    try {
      const data = await getMyConversations()
      setConversations(data.direct || [])
      setGroupConversations(data.groups || [])
    } catch (error) { setPageError(error instanceof Error ? error.message : 'Could not load your conversations.') }
  }, [])

  useEffect(() => {
    // Fetch the current user's authorized conversations on entry.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadData()
  }, [loadData])

  useEffect(() => {
    const controller = new AbortController()
    void subscribeToMessageEvents(controller.signal, () => {
      void loadData()
      if (chatMode === 'direct' && activeConversation) {
        void getDirectConversation(activeConversation).then(setDirectMessages).catch(() => {})
      } else if (chatMode === 'group' && activeGroupId) {
        void getGroupMessages(activeGroupId).then((data) => setGroupMessages(data.messages || [])).catch(() => {})
      }
    }, setLiveConnected)
    return () => controller.abort()
  }, [activeConversation, activeGroupId, chatMode, loadData])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [directMessages, groupMessages])

  useEffect(() => {
    if (!activeConversation || chatMode !== 'direct') return
    getDirectConversation(activeConversation).then((data) => {
      setDirectMessages(data || [])
      void loadData()
    }).catch((error) => setPageError(error instanceof Error ? error.message : 'Could not load this conversation.'))
  }, [activeConversation, chatMode, loadData])

  useEffect(() => {
    if (!activeGroupId || chatMode !== 'group') return
    getGroupMessages(activeGroupId).then((data) => {
      setGroupMessages(data.messages || [])
      markGroupRead(activeGroupId).catch(() => {})
      loadData()
    }).catch((error) => setPageError(error instanceof Error ? error.message : 'Could not load this group.'))
  }, [activeGroupId, chatMode, loadData])

  const handleSend = async () => {
    if (!input.trim() || sending) return
    setSending(true)
    setPageError('')
    try {
      if (chatMode === 'group' && activeGroupId) {
        const msg = await sendGroupMessage(activeGroupId, input.trim())
        setGroupMessages((prev) => [...prev, msg])
      } else if (chatMode === 'direct' && activeConversation) {
        const msg = await sendDirectMessage(activeConversation, input.trim())
        setDirectMessages((prev) => [...prev, msg])
        loadData()
      }
      setInput('')
    } catch (error) { setPageError(error instanceof Error ? error.message : 'Message could not be sent.') }
    setSending(false)
  }

  const handleSelectConversation = (otherId: string) => {
    setActiveGroupId(null)
    setChatMode('direct')
    setActiveConversation(otherId)
  }

  const handleSelectGroup = (groupId: string) => {
    setActiveConversation(null)
    setChatMode('group')
    setActiveGroupId(groupId)
  }

  const handleNewMessage = (selectedUser: UserEntry) => {
    setShowNewMessage(false)
    setConversations((current) => [
      { other_id: selectedUser.id, other_name: selectedUser.name, other_email: selectedUser.email || '', last_message: '', last_time: '', last_sender: '', unread: 0 },
      ...current.filter((conversation) => conversation.other_id !== selectedUser.id),
    ])
    handleSelectConversation(selectedUser.id)
  }

  const activeConv = conversations.find((c) => c.other_id === activeConversation)
  const activeGroup = groupConversations.find((g) => g.group_id === activeGroupId)
  const filteredConversations = conversations.filter((c) => `${c.other_name} ${c.last_message}`.toLowerCase().includes(search.toLowerCase()))
  const filteredGroups = groupConversations.filter((g) => `${g.name} ${g.last_message}`.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="flex h-[calc(100dvh-150px)] min-h-[440px] flex-col gap-[12px] md:h-[calc(100vh-130px)] md:gap-[16px]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[1.3rem] font-bold text-[#1f2937]">Messages</h2>
          <p className="max-w-2xl text-[0.78rem] leading-5 text-[#6b7280]">
            {isGuardian ? 'Message only the child or guardian relationship linked to your verified account.' : 'Message your assigned counsellor, a linked parent or guardian, and groups you have been invited to. Messages are not an emergency service.'}
          </p>
        </div>
        <button
          onClick={() => setShowNewMessage(true)}
          className="px-[14px] py-[8px] bg-[#0F766E] text-white rounded-[8px] cursor-pointer hover:bg-[#115E59] flex items-center gap-[6px] text-[0.82rem] font-semibold border-none"
        >
          <i className="ti ti-plus text-[15px]" />
          New Message
        </button>
      </div>

      <div className={`w-fit rounded-full px-2.5 py-1 text-[0.68rem] font-semibold ${liveConnected ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}><i className={`ti ${liveConnected ? 'ti-broadcast' : 'ti-refresh'} mr-1`} />{liveConnected ? 'Live updates connected' : 'Connecting to live updates…'}</div>

      {pageError && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{pageError}</div>}

      <div className="flex min-h-0 flex-1 flex-col gap-[12px] md:flex-row">
        {/* Conversation list */}
        <div className={`${activeConversation || activeGroupId ? 'hidden md:flex' : 'flex'} w-full min-h-0 flex-shrink-0 flex-col rounded-xl border border-[rgba(229,231,235,0.7)] bg-white md:w-[260px]`}>
          <div className="flex-1 overflow-y-auto">
            <div className="sticky top-0 z-[1] border-b border-slate-100 bg-white p-3"><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search conversations…" aria-label="Search conversations" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-teal-700" /></div>
            {conversations.length === 0 && groupConversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-[40px] text-[#9ca3af]">
                <i className="ti ti-messages text-[28px] mb-[6px]" />
                <span className="text-[0.78rem]">No conversations</span>
              </div>
            ) : (
              <>
                {filteredConversations.map((c) => (
                  <div
                    key={c.other_id}
                    onClick={() => handleSelectConversation(c.other_id)}
                    className={`px-[14px] py-[10px] cursor-pointer border-b border-[#f8fafc] transition-colors ${
                      activeConversation === c.other_id && chatMode === 'direct'
                        ? 'bg-[#f0fdfa] border-l-[3px] border-l-[#0F766E]'
                        : 'hover:bg-[#f9fafb]'
                    }`}
                  >
                    <div className="flex items-center gap-[10px]">
                      <div className="w-[32px] h-[32px] rounded-full bg-gradient-to-br from-[#0F766E] to-[#1D9E75] flex items-center justify-center text-white font-bold text-[0.7rem] flex-shrink-0">
                        {c.other_name?.charAt(0) || '?'}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <span className="text-[0.78rem] font-semibold text-[#1f2937] truncate">{c.other_name}</span>
                          <span className="text-[0.62rem] text-[#9ca3af] flex-shrink-0">{formatTime(c.last_time)}</span>
                        </div>
                        <span className="text-[0.7rem] text-[#6b7280] truncate block">{c.last_message || 'No messages'}</span>
                      </div>
                    </div>
                  </div>
                ))}
                {filteredGroups.map((g) => {
                  const muted = isGroupMuted(g.group_id)
                  return (
                    <div
                      key={g.group_id}
                      onClick={() => handleSelectGroup(g.group_id)}
                      className={`px-[14px] py-[10px] cursor-pointer border-b border-[#f8fafc] transition-colors ${
                        activeGroupId === g.group_id && chatMode === 'group'
                          ? 'bg-[#f0fdfa] border-l-[3px] border-l-[#7c3aed]'
                          : 'hover:bg-[#f9fafb]'
                      }`}
                    >
                      <div className="flex items-center gap-[10px]">
                        <div className="w-[32px] h-[32px] rounded-full bg-gradient-to-br from-[#7c3aed] to-[#a78bfa] flex items-center justify-center text-white font-bold text-[0.7rem] flex-shrink-0">
                          <i className="ti ti-users text-[14px]" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between">
                            <span className="text-[0.78rem] font-semibold text-[#1f2937] truncate flex items-center gap-[4px]">
                              {g.name}
                              {muted && <i className="ti ti-bell-off text-[11px] text-[#9ca3af]" />}
                            </span>
                          </div>
                          <div className="flex items-center gap-[4px]">
                            {g.last_sender && (
                              <span className="text-[0.65rem] text-[#4b5563]">{g.last_sender}: </span>
                            )}
                            <span className="text-[0.7rem] text-[#6b7280] truncate flex-1">{g.last_message}</span>
                            {g.unread > 0 && (
                              <span className="bg-[#7c3aed] text-white text-[0.55rem] font-bold px-[5px] py-[1px] rounded-full">
                                {g.unread}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </>
            )}
          </div>
        </div>

        {/* Chat area */}
        <div className={`${activeConversation || activeGroupId ? 'flex' : 'hidden md:flex'} min-h-0 w-full flex-1 flex-col rounded-xl border border-[rgba(229,231,235,0.7)] bg-white`}>
          {!activeConversation && !activeGroupId ? (
            <div className="flex flex-col items-center justify-center flex-1 text-[#9ca3af]">
              <i className="ti ti-message text-[40px] mb-[10px]" />
              <span className="text-[0.9rem] font-medium">Select a conversation</span>
              <span className="text-[0.78rem]">Choose a counsellor or group to message</span>
            </div>
          ) : (
            <>
              <div className="px-[18px] py-[12px] border-b border-[#f1f5f9] flex items-center gap-[10px]">
                <button type="button" onClick={() => { setActiveGroupId(null); setActiveConversation(null) }} className="mr-1 rounded-lg p-2 text-slate-600 hover:bg-slate-100 md:hidden" aria-label="Back to conversations"><i className="ti ti-arrow-left" /></button>
                <div className={`w-[34px] h-[34px] rounded-full flex items-center justify-center text-white font-bold text-[0.72rem] ${
                  chatMode === 'group'
                    ? 'bg-gradient-to-br from-[#7c3aed] to-[#a78bfa]'
                    : 'bg-gradient-to-br from-[#0F766E] to-[#1D9E75]'
                }`}>
                  {chatMode === 'group' ? (
                    <i className="ti ti-users text-[15px]" />
                  ) : (
                    activeConv?.other_name?.charAt(0) || '?'
                  )}
                </div>
                <div>
                  <div className="text-[0.85rem] font-semibold text-[#1f2937]">
                    {chatMode === 'group' ? activeGroup?.name : activeConv?.other_name || 'Unknown'}
                  </div>
                  <div className="text-[0.68rem] text-[#6b7280]">
                    {chatMode === 'group' ? `${activeGroup?.member_count || 0} members` : activeConv?.other_email || ''}
                  </div>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-[18px] space-y-[8px]">
                {(chatMode === 'direct' ? directMessages : groupMessages).length === 0 ? (
                  <div className="flex items-center justify-center h-full text-[#9ca3af] text-[0.78rem]">
                    No messages yet. Send a message to start.
                  </div>
                ) : (
                  (chatMode === 'direct' ? directMessages : groupMessages).map((msg) => {
                    const isMyMessage = chatMode === 'direct'
                      ? msg.sender_id !== activeConversation
                      : msg.sender_id === user?.id
                    return (
                      <div key={msg.id} className={`flex ${isMyMessage ? 'justify-end' : 'justify-start'}`}>
                        <div className="max-w-[85%] md:max-w-[70%]">
                          {!isMyMessage && chatMode === 'group' && (
                            <div className="text-[0.68rem] font-medium text-[#4b5563] mb-[2px] ml-[2px]">
                              {'sender_name' in msg ? msg.sender_name : ''}
                            </div>
                          )}
                          <div className={`px-[14px] py-[9px] rounded-[14px] text-[0.82rem] ${
                            isMyMessage
                              ? 'bg-[#0F766E] text-white rounded-br-[4px]'
                              : 'bg-[#f3f4f6] text-[#1f2937] rounded-bl-[4px]'
                          }`}>
                            {msg.message}
                            <div className={`text-[0.6rem] mt-[3px] ${isMyMessage ? 'text-[#a7f3d0]' : 'text-[#9ca3af]'}`}>
                              {formatTime(msg.created_at)}
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })
                )}
                <div ref={bottomRef} />
              </div>

              <div className="px-[18px] py-[12px] border-t border-[#f1f5f9] flex items-center gap-[10px]">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                  maxLength={5000}
                  placeholder="Type a message..."
                  className="flex-1 px-[14px] py-[9px] rounded-[10px] border border-[#e5e7eb] text-[0.82rem] outline-none focus:border-[#0F766E]"
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || sending}
                  className="px-[14px] py-[9px] bg-[#0F766E] text-white rounded-[10px] cursor-pointer hover:bg-[#115E59] disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-[6px] text-[0.82rem] font-semibold border-none"
                >
                  <i className="ti ti-send text-[14px]" />
                  Send
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {showNewMessage && (
        <NewMessageDialog
          roleFilter={isGuardian ? 'student' : 'counsellor'}
          allowLinkedGuardian={!isGuardian}
          excludeId={user?.id}
          onSelect={handleNewMessage}
          onClose={() => setShowNewMessage(false)}
        />
      )}
    </div>
  )
}

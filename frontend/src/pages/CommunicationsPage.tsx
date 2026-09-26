import { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import { useAuthStore, useCounsellorStore, useNotificationStore } from '../store'
import {
  getMyConversations, sendDirectMessage, getDirectConversation,
  getGroupMessages, sendGroupMessage, markGroupRead,
  getGroup, addGroupMembers, removeGroupMember,
  subscribeToMessageEvents,
} from '../api/counsellor'
import GroupCreateDialog from '../components/counsellor/GroupCreateDialog'
import GroupMemberList from '../components/counsellor/GroupMemberList'
import NewMessageDialog from '../components/shared/NewMessageDialog'
import type { GroupDetail } from '../types'
import type { Message } from '../api/counsellor'
import type { UserEntry } from '../components/shared/NewMessageDialog'

function formatTime(d: string) {
  if (!d) return ''
  const dt = new Date(d)
  const now = new Date()
  const diff = now.getTime() - dt.getTime()
  if (diff < 86400000) return dt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

type ChatMode = 'direct' | 'group'

export default function CommunicationsPage() {
  const user = useAuthStore((s) => s.user)
  const isCounsellor = user?.role_type === 'counsellor' || user?.role_type === 'admin'
  const {
    conversations, setConversations,
    activeConversation, setActiveConversation,
    messages, setMessages, addMessage,
    groupConversations, setGroupConversations,
    activeGroupId, setActiveGroupId,
    groupMessages, setGroupMessages, addGroupMessage,
    setLoading,
  } = useCounsellorStore()
  const isGroupMuted = useNotificationStore((s) => s.isGroupMuted)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [chatMode, setChatMode] = useState<ChatMode>('direct')
  const [showCreate, setShowCreate] = useState(false)
  const [showNewMessage, setShowNewMessage] = useState(false)
  const [groupDetail, setGroupDetail] = useState<GroupDetail | null>(null)
  const [showMemberList, setShowMemberList] = useState(false)
  const [addMemberSearch, setAddMemberSearch] = useState('')
  const [addingMember, setAddingMember] = useState(false)
  const [search, setSearch] = useState('')
  const [pageError, setPageError] = useState('')
  const [liveConnected, setLiveConnected] = useState(false)
  const activeDirectMessages = useMemo(() => messages[activeConversation || ''] || [], [messages, activeConversation])
  const activeGroupMessages = useMemo(() => groupMessages[activeGroupId || ''] || [], [groupMessages, activeGroupId])

  const loadData = useCallback(async () => {
    try {
      const convData = await getMyConversations()
      setConversations(convData.direct || [])
      setGroupConversations(convData.groups || [])
    } catch (e) { setPageError(e instanceof Error ? e.message : 'Could not load conversations.') }
  }, [setConversations, setGroupConversations])

  useEffect(() => {
    // Fetch the conversation list after mount; the request owns its loading/error updates.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadData()
  }, [loadData])

  useEffect(() => {
    const controller = new AbortController()
    void subscribeToMessageEvents(controller.signal, () => {
      void loadData()
      if (chatMode === 'direct' && activeConversation) {
        void getDirectConversation(activeConversation).then((data) => setMessages(activeConversation, data)).catch(() => {})
      } else if (chatMode === 'group' && activeGroupId) {
        void getGroupMessages(activeGroupId).then((data) => setGroupMessages(activeGroupId, data.messages || [])).catch(() => {})
      }
    }, setLiveConnected)
    return () => controller.abort()
  }, [activeConversation, activeGroupId, chatMode, loadData, setMessages, setGroupMessages])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activeDirectMessages, activeGroupMessages])

  // Load direct messages
  useEffect(() => {
    if (!activeConversation || chatMode !== 'direct') return
    const load = async () => {
      setLoading(true)
      try {
        const data = await getDirectConversation(activeConversation)
        setMessages(activeConversation, data)
        void loadData()
      } catch (e) { setPageError(e instanceof Error ? e.message : 'Could not load this conversation.') }
      setLoading(false)
    }
    load()
  }, [activeConversation, chatMode, setMessages, setLoading, loadData])

  // Load group messages
  useEffect(() => {
    if (!activeGroupId || chatMode !== 'group') return
    const load = async () => {
      setLoading(true)
      try {
        const data = await getGroupMessages(activeGroupId)
        setGroupMessages(activeGroupId, data.messages || [])
        const detail = await getGroup(activeGroupId)
        setGroupDetail(detail)
        markGroupRead(activeGroupId).catch(() => {})
        loadData()
      } catch (e) { setPageError(e instanceof Error ? e.message : 'Could not load this group.') }
      setLoading(false)
    }
    load()
  }, [activeGroupId, chatMode, setGroupMessages, setLoading, loadData])

  const handleSend = async () => {
    if (!input.trim() || sending) return
    setSending(true)
    setPageError('')
    try {
      if (chatMode === 'group' && activeGroupId) {
        const msg = await sendGroupMessage(activeGroupId, input.trim())
        addGroupMessage(activeGroupId, msg)
      } else if (chatMode === 'direct' && activeConversation) {
        const msg = await sendDirectMessage(activeConversation, input.trim())
        addMessage(activeConversation, msg)
        loadData()
      }
      setInput('')
    } catch (e) { setPageError(e instanceof Error ? e.message : 'Message could not be sent.') }
    setSending(false)
  }

  const handleSelectConversation = (otherId: string) => {
    setActiveGroupId(null)
    setChatMode('direct')
    setActiveConversation(otherId)
    setShowMemberList(false)
  }

  const handleSelectGroup = (groupId: string) => {
    setActiveConversation(null)
    setChatMode('group')
    setActiveGroupId(groupId)
    setShowMemberList(false)
  }

  const handleRemoveMember = async (memberId: string) => {
    if (!activeGroupId) return
    try {
      await removeGroupMember(activeGroupId, memberId)
      const detail = await getGroup(activeGroupId)
      setGroupDetail(detail)
    } catch (e) { setPageError(e instanceof Error ? e.message : 'Could not update group members.') }
  }

  const handleAddMembers = async () => {
    if (!activeGroupId || !addMemberSearch.trim()) return
    setAddingMember(true)
    try {
      await addGroupMembers(activeGroupId, [addMemberSearch.trim()])
      const detail = await getGroup(activeGroupId)
      setGroupDetail(detail)
      setAddMemberSearch('')
    } catch (e) { setPageError(e instanceof Error ? e.message : 'Could not add this member.') }
    setAddingMember(false)
  }

  const currentDirectMessages = activeDirectMessages as Message[]
  const currentGroupMessages = activeGroupMessages
  const activeConv = conversations.find((c) => c.other_id === activeConversation)
  const activeGroup = groupConversations.find((g) => g.group_id === activeGroupId)
  const filteredConversations = conversations.filter((c) => `${c.other_name} ${c.last_message}`.toLowerCase().includes(search.toLowerCase()))
  const filteredGroups = groupConversations.filter((g) => `${g.name} ${g.last_message}`.toLowerCase().includes(search.toLowerCase()))

  const handleNewMessage = (selectedUser: UserEntry) => {
    setShowNewMessage(false)
    setConversations([
      { other_id: selectedUser.id, other_name: selectedUser.name, other_email: selectedUser.email || '', last_message: '', last_time: '', unread: 0 },
      ...conversations.filter((conversation) => conversation.other_id !== selectedUser.id),
    ])
    handleSelectConversation(selectedUser.id)
  }

  return (
    <div className="flex h-[calc(100dvh-150px)] min-h-[440px] flex-col gap-[12px] md:h-[calc(100vh-130px)] md:gap-[16px]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[1.3rem] font-bold text-[#1f2937]">Communications</h2>
          <p className="text-[0.82rem] text-[#6b7280] mt-[2px]">
            Message students assigned to your caseload or groups you are authorised to manage.
          </p>
        </div>
        <div className="flex flex-wrap gap-[8px]">
          <span className={`self-center rounded-full px-2 py-1 text-[0.68rem] font-semibold ${liveConnected ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}><i className={`ti ${liveConnected ? 'ti-broadcast' : 'ti-refresh'} mr-1`} />{liveConnected ? 'Live updates' : 'Reconnecting'}</span>
          <button
            onClick={() => setShowNewMessage(true)}
            className="px-[14px] py-[8px] bg-white text-[#0F766E] rounded-[8px] cursor-pointer hover:bg-[#f0fdfa] flex items-center gap-[6px] text-[0.82rem] font-semibold border border-[#0F766E]"
          >
            <i className="ti ti-plus text-[15px]" />
            New Message
          </button>
          {isCounsellor && (
            <button
              onClick={() => setShowCreate(true)}
              className="px-[14px] py-[8px] bg-[#0F766E] text-white rounded-[8px] cursor-pointer hover:bg-[#115E59] flex items-center gap-[6px] text-[0.82rem] font-semibold border-none"
            >
              <i className="ti ti-users-plus text-[15px]" />
              Create Group
            </button>
          )}
        </div>
      </div>

      {pageError && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{pageError}</div>}

      <div className="flex min-h-0 flex-1 flex-col gap-[12px] md:flex-row">
        {/* Conversation list */}
        <div className={`${activeConversation || activeGroupId ? 'hidden md:flex' : 'flex'} w-full min-h-0 flex-shrink-0 flex-col rounded-xl border border-[rgba(229,231,235,0.7)] bg-white md:w-[280px]`}>
          <div className="p-[12px] border-b border-[#f1f5f9]">
            <input
              placeholder="Search conversations..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              aria-label="Search conversations"
              className="w-full px-[10px] py-[7px] rounded-[7px] border border-[#e5e7eb] text-[0.78rem] outline-none focus:border-[#0F766E]"
            />
          </div>
          <div className="flex-1 overflow-y-auto">
            {conversations.length === 0 && groupConversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-[40px] text-[#9ca3af]">
                <i className="ti ti-messages text-[28px] mb-[6px]" />
                <span className="text-[0.78rem]">No conversations</span>
              </div>
            ) : (
              <>
                {/* Direct messages section */}
                {conversations.length > 0 && (
                  <div className="px-[12px] pt-[10px] pb-[4px]">
                    <div className="text-[0.65rem] font-bold uppercase text-[#6b7280] tracking-wider">Direct Messages</div>
                  </div>
                )}
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
                        <div className="flex items-center gap-[4px]">
                          <span className="text-[0.7rem] text-[#6b7280] truncate flex-1">{c.last_message || 'No messages'}</span>
                          {c.unread > 0 && (
                            <span className="bg-[#ef4444] text-white text-[0.55rem] font-bold px-[5px] py-[1px] rounded-full min-w-[16px] text-center flex-shrink-0">
                              {c.unread}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}

                {/* Groups section */}
                {groupConversations.length > 0 && (
                  <div className="px-[12px] pt-[14px] pb-[4px] border-t border-[#f3f4f6]">
                    <div className="text-[0.65rem] font-bold uppercase text-[#6b7280] tracking-wider">Groups</div>
                  </div>
                )}
                {filteredGroups.map((g) => {
                  const muted = isGroupMuted(g.group_id)
                  return (
                    <div
                      key={g.group_id}
                      onClick={() => handleSelectGroup(g.group_id)}
                      className={`px-[14px] py-[10px] cursor-pointer border-b border-[#f8fafc] transition-colors ${
                        activeGroupId === g.group_id && chatMode === 'group'
                          ? 'bg-[#f0fdfa] border-l-[3px] border-l-[#1D9E75]'
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
                            <div className="flex items-center gap-[4px]">
                              <span className="text-[0.6rem] text-[#9ca3af]">{g.member_count}</span>
                              <i className="ti ti-users text-[10px] text-[#9ca3af]" />
                            </div>
                          </div>
                          <div className="flex items-center gap-[4px]">
                            {g.last_sender && (
                              <span className="text-[0.65rem] font-medium text-[#4b5563] truncate">{g.last_sender}: </span>
                            )}
                            <span className="text-[0.7rem] text-[#6b7280] truncate flex-1">{g.last_message || 'No messages'}</span>
                            {g.unread > 0 && (
                              <span className="bg-[#7c3aed] text-white text-[0.55rem] font-bold px-[5px] py-[1px] rounded-full min-w-[16px] text-center flex-shrink-0">
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
              <span className="text-[0.78rem]">Choose a student or group to start messaging</span>
            </div>
          ) : chatMode === 'group' && activeGroupId ? (
            <>
              {/* Group chat header */}
              <div className="px-[18px] py-[12px] border-b border-[#f1f5f9] flex items-center gap-[10px]">
                <button type="button" onClick={() => { setActiveGroupId(null); setActiveConversation(null) }} className="mr-1 rounded-lg p-2 text-slate-600 hover:bg-slate-100 md:hidden" aria-label="Back to conversations"><i className="ti ti-arrow-left" /></button>
                <div className="w-[34px] h-[34px] rounded-full bg-gradient-to-br from-[#7c3aed] to-[#a78bfa] flex items-center justify-center text-white font-bold text-[0.72rem]">
                  <i className="ti ti-users text-[15px]" />
                </div>
                <div className="flex-1">
                  <div className="text-[0.85rem] font-semibold text-[#1f2937]">{activeGroup?.name || 'Group'}</div>
                  <div className="text-[0.68rem] text-[#6b7280]">
                    {groupDetail?.members?.length || activeGroup?.member_count || 0} members
                  </div>
                </div>
                <button
                  onClick={() => setShowMemberList(!showMemberList)}
                  className={`px-[10px] py-[6px] rounded-[7px] text-[0.78rem] font-medium cursor-pointer border transition-colors ${
                    showMemberList
                      ? 'bg-[#f0fdfa] text-[#0F766E] border-[#0F766E]'
                      : 'bg-transparent text-[#6b7280] border-[#e5e7eb] hover:bg-[#f9fafb]'
                  }`}
                >
                  <i className="ti ti-users text-[14px] mr-[4px]" />
                  Members
                </button>
              </div>

              <div className="relative flex flex-1 min-h-0">
                {/* Messages */}
                <div className="flex-1 flex flex-col min-w-0">
                  <div className="flex-1 overflow-y-auto p-[18px] space-y-[8px]">
                    {currentGroupMessages.length === 0 ? (
                      <div className="flex items-center justify-center h-full text-[#9ca3af] text-[0.78rem]">
                        No messages yet. Send a message to start the conversation.
                      </div>
                    ) : (
                      currentGroupMessages.map((msg) => {
                        const isMyMessage = msg.sender_id === user?.id
                        return (
                          <div key={msg.id} className={`flex ${isMyMessage ? 'justify-end' : 'justify-start'}`}>
                            <div className="max-w-[85%] md:max-w-[70%]">
                              {!isMyMessage && (
                                <div className="text-[0.68rem] font-medium text-[#4b5563] mb-[2px] ml-[2px]">
                                  {msg.sender_name}
                                </div>
                              )}
                              <div
                                className={`px-[14px] py-[9px] rounded-[14px] text-[0.82rem] ${
                                  isMyMessage
                                    ? 'bg-[#0F766E] text-white rounded-br-[4px]'
                                    : 'bg-[#f3f4f6] text-[#1f2937] rounded-bl-[4px]'
                                }`}
                              >
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

                  {/* Input */}
                  <div className="px-[18px] py-[12px] border-t border-[#f1f5f9] flex items-center gap-[10px]">
                    <input
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                      maxLength={5000}
                      placeholder={`Message ${activeGroup?.name || 'group'}...`}
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
                </div>

                {/* Member list sidebar */}
                {showMemberList && groupDetail && (
                  <div className="absolute inset-y-0 right-0 z-10 flex w-[85vw] max-w-[320px] flex-col border-l border-[#f1f5f9] bg-white shadow-xl md:static md:w-[220px] md:shadow-none">
                    <div className="px-[12px] py-[10px] border-b border-[#f1f5f9]">
                      <div className="text-[0.72rem] font-bold text-[#1f2937]">Members</div>
                      <div className="text-[0.62rem] text-[#6b7280]">{groupDetail.members?.length || 0} total</div>
                    </div>
                    <div className="flex-1 overflow-y-auto p-[8px]">
                      <GroupMemberList
                        members={groupDetail.members || []}
                        currentUserId={user?.id}
                        groupCreatorId={groupDetail.created_by}
                        onRemove={isCounsellor ? handleRemoveMember : undefined}
                      />
                    </div>
                    {isCounsellor && (
                      <div className="p-[8px] border-t border-[#f1f5f9]">
                        <div className="flex gap-[4px]">
                          <input
                            value={addMemberSearch}
                            onChange={(e) => setAddMemberSearch(e.target.value)}
                            placeholder="Add by user ID..."
                            className="flex-1 px-[8px] py-[5px] rounded-[6px] border border-[#e5e7eb] text-[0.7rem] outline-none"
                          />
                          <button
                            onClick={handleAddMembers}
                            disabled={!addMemberSearch.trim() || addingMember}
                            className="px-[8px] py-[5px] bg-[#0F766E] text-white rounded-[6px] text-[0.7rem] cursor-pointer hover:bg-[#115E59] disabled:opacity-50 border-none"
                          >
                            <i className="ti ti-plus text-[12px]" />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          ) : (
            <>
              {/* Direct chat header */}
              <div className="px-[18px] py-[12px] border-b border-[#f1f5f9] flex items-center gap-[10px]">
                <button type="button" onClick={() => { setActiveGroupId(null); setActiveConversation(null) }} className="mr-1 rounded-lg p-2 text-slate-600 hover:bg-slate-100 md:hidden" aria-label="Back to conversations"><i className="ti ti-arrow-left" /></button>
                <div className="w-[34px] h-[34px] rounded-full bg-gradient-to-br from-[#0F766E] to-[#1D9E75] flex items-center justify-center text-white font-bold text-[0.72rem]">
                  {activeConv?.other_name?.charAt(0) || '?'}
                </div>
                <div>
                  <div className="text-[0.85rem] font-semibold text-[#1f2937]">{activeConv?.other_name || 'Unknown'}</div>
                  <div className="text-[0.68rem] text-[#6b7280]">{activeConv?.other_email || ''}</div>
                </div>
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto p-[18px] space-y-[8px]">
                {currentDirectMessages.length === 0 ? (
                  <div className="flex items-center justify-center h-full text-[#9ca3af] text-[0.78rem]">
                    No messages yet. Send a message to start the conversation.
                  </div>
                ) : (
                  currentDirectMessages.map((msg) => {
                    const isMyMessage = msg.sender_id !== activeConversation
                    return (
                      <div key={msg.id} className={`flex ${isMyMessage ? 'justify-end' : 'justify-start'}`}>
                        <div
                          className={`max-w-[85%] break-words px-[14px] py-[9px] rounded-[14px] text-[0.82rem] md:max-w-[70%] ${
                            isMyMessage
                              ? 'bg-[#0F766E] text-white rounded-br-[4px]'
                              : 'bg-[#f3f4f6] text-[#1f2937] rounded-bl-[4px]'
                          }`}
                        >
                          {msg.message}
                          <div className={`text-[0.6rem] mt-[3px] ${isMyMessage ? 'text-[#a7f3d0]' : 'text-[#9ca3af]'}`}>
                            {formatTime(msg.created_at)}
                          </div>
                        </div>
                      </div>
                    )
                  })
                )}
                <div ref={bottomRef} />
              </div>

              {/* Input */}
              <div className="px-[18px] py-[12px] border-t border-[#f1f5f9] flex items-center gap-[10px]">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                  maxLength={5000}
                  placeholder={`Message ${activeConv?.other_name || 'user'}...`}
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

      {showCreate && (
        <GroupCreateDialog
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            loadData()
          }}
        />
      )}

      {showNewMessage && (
        <NewMessageDialog
          roleFilter="student"
          excludeId={user?.id}
          onSelect={handleNewMessage}
          onClose={() => setShowNewMessage(false)}
        />
      )}
    </div>
  )
}

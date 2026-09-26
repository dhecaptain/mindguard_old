import { useState, useEffect } from 'react'
import api from '../../api/client'

export interface UserEntry {
  id: string
  name: string
  email?: string
  role_type: string
}

interface Props {
  roleFilter: 'student' | 'counsellor' | 'parent'
  allowLinkedGuardian?: boolean
  excludeId?: string
  onSelect: (user: UserEntry) => void
  onClose: () => void
}

export default function NewMessageDialog({ roleFilter, allowLinkedGuardian = false, excludeId, onSelect, onClose }: Props) {
  const [targetRole, setTargetRole] = useState<'student' | 'counsellor' | 'parent'>(roleFilter)
  const [users, setUsers] = useState<UserEntry[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/users/directory', { params: { role: targetRole } })
      .then((res) => setUsers(res.data || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [targetRole])

  const filtered = users.filter(
    (u) =>
      u.id !== excludeId &&
      (u.name.toLowerCase().includes(search.toLowerCase()) ||
        (u.email || '').toLowerCase().includes(search.toLowerCase()))
  )

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[9999]">
      <div className="bg-white rounded-[16px] p-[24px] w-[420px] max-w-[95vw] shadow-2xl">
        <div className="flex items-center justify-between mb-[16px]">
          <h3 className="text-[1.05rem] font-bold text-[#1f2937]">New Message</h3>
          <button
            onClick={onClose}
            className="w-[28px] h-[28px] flex items-center justify-center rounded-[6px] text-[#6b7280] hover:bg-[#f3f4f6] cursor-pointer bg-transparent border-none"
          >
            <i className="ti ti-x text-[18px]" />
          </button>
        </div>

        {allowLinkedGuardian && <label className="mb-3 block text-xs font-semibold text-slate-600">Message
          <select value={targetRole} onChange={(event) => setTargetRole(event.target.value as 'counsellor' | 'parent')} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
            <option value="counsellor">My assigned counsellor</option>
            <option value="parent">My linked parent or guardian</option>
          </select>
        </label>}

        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by name..."
          className="w-full px-[12px] py-[8px] rounded-[8px] border border-[#e5e7eb] text-[0.82rem] outline-none focus:border-[#0F766E] mb-[12px]"
          autoFocus
        />

        <div className="max-h-[300px] overflow-y-auto border border-[#f1f5f9] rounded-[8px]">
          {loading ? (
            <div className="flex items-center justify-center py-[30px] text-[#9ca3af] text-[0.8rem]">
              <div className="w-[18px] h-[18px] border-[2px] border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin mr-[8px]" />
              Loading...
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-[30px] text-[#9ca3af]">
              <i className="ti ti-search-off text-[24px] mb-[6px]" />
              <span className="text-[0.78rem]">
                {search ? 'No users match your search' : 'No users found'}
              </span>
            </div>
          ) : (
            filtered.map((u) => (
              <div
                key={u.id}
                onClick={() => onSelect(u)}
                className="flex items-center gap-[10px] px-[12px] py-[9px] cursor-pointer hover:bg-[#f9fafb] transition-colors border-b border-[#f8fafc]"
              >
                <div className="w-[34px] h-[34px] rounded-full bg-gradient-to-br from-[#0F766E] to-[#1D9E75] flex items-center justify-center text-white font-bold text-[0.7rem] flex-shrink-0">
                  {u.name?.charAt(0) || '?'}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[0.82rem] font-medium text-[#1f2937] truncate">{u.name}</div>
                  <div className="text-[0.7rem] text-[#6b7280] truncate">{u.email}</div>
                </div>
                <i className="ti ti-chevron-right text-[14px] text-[#9ca3af]" />
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import api from '../api/client'

type Workspace = {
  institution: { name: string; type: string; status: string; settings_version?: number }
  counts: { students: number; staff: number; active_assignments: number }
}

export default function InstitutionWorkspacePage() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api.get<Workspace>('/institution/me'), api.get('/institution/settings')])
      .then(([overview, policy]) => { setWorkspace(overview.data); setSettings(policy.data) })
      .catch((err) => setError(err.message || 'Unable to load institution workspace'))
  }, [])

  if (error) return <div className="p-[32px] text-[#b91c1c]">{error}</div>
  if (!workspace) return <div className="p-[32px] text-[#64748b]">Loading institution workspace…</div>

  const cards = [
    ['Students', workspace.counts.students, 'ti ti-users'],
    ['Staff', workspace.counts.staff, 'ti ti-stethoscope'],
    ['Active assignments', workspace.counts.active_assignments, 'ti ti-user-check'],
  ]
  return (
    <div className="p-[24px] md:p-[36px] max-w-[1200px] mx-auto">
      <div className="flex flex-wrap items-start justify-between gap-[16px] mb-[28px]">
        <div>
          <p className="text-[0.75rem] font-bold uppercase tracking-[0.14em] text-[#0f766e]">Institution workspace</p>
          <h1 className="text-[1.8rem] font-bold text-[#172033] mt-[6px]">{workspace.institution.name}</h1>
          <p className="text-[#64748b] mt-[4px]">{workspace.institution.type} · <span className="font-semibold">{workspace.institution.status}</span></p>
        </div>
        <div className="rounded-full bg-[#ecfdf5] px-[12px] py-[6px] text-[0.75rem] font-bold text-[#047857]">Policy v{workspace.institution.settings_version || 1}</div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-[16px] mb-[24px]">
        {cards.map(([label, value, icon]) => <div key={label} className="rounded-[16px] border border-[#e2e8f0] bg-white p-[20px] shadow-sm"><i className={`${icon} text-[22px] text-[#0f766e]`} /><div className="text-[1.7rem] font-bold text-[#172033] mt-[12px]">{value}</div><div className="text-[0.8rem] text-[#64748b]">{label}</div></div>)}
      </div>
      <div className="rounded-[16px] border border-[#e2e8f0] bg-white p-[22px] shadow-sm">
        <h2 className="font-bold text-[#172033]">Active institution policy</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-[14px] mt-[18px] text-[0.85rem]">
          <div><span className="text-[#64748b]">Consent expiry</span><div className="font-semibold">{String(settings?.consent_expiry_days || 30)} days</div></div>
          <div><span className="text-[#64748b]">Retention</span><div className="font-semibold">{String(settings?.retention_days || 365)} days</div></div>
          <div><span className="text-[#64748b]">Risk threshold</span><div className="font-semibold">{String(settings?.alert_threshold || 'Global default')}</div></div>
        </div>
      </div>
    </div>
  )
}

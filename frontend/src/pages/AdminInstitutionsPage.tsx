import { useEffect, useState } from 'react'
import { getInstitutions, updateInstitution } from '../api/admin'
import type { Institution } from '../types'

export default function AdminInstitutionsPage() {
  const [institutions, setInstitutions] = useState<Institution[]>([])
  const [error, setError] = useState('')
  const load = () => getInstitutions().then(setInstitutions).catch((e) => setError(e.message || 'Unable to load institutions'))
  useEffect(() => { load() }, [])
  const changeStatus = async (id: string, status: string) => {
    try {
      const updated = await updateInstitution(id, { status })
      setInstitutions((items) => items.map((item) => item.id === id ? updated : item))
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to update institution') }
  }
  return (
    <div className="p-[24px] md:p-[36px] max-w-[1100px] mx-auto">
      <div className="flex items-start justify-between gap-4 mb-6">
        <div><p className="text-xs font-bold uppercase tracking-widest text-[#0f766e]">Global administration</p><h1 className="text-2xl font-bold text-[#172033] mt-1">Institutions</h1><p className="text-sm text-[#64748b] mt-1">Provision, activate, suspend, and archive tenant workspaces.</p></div>
        <button onClick={load} className="rounded-lg border border-[#cbd5e1] px-3 py-2 text-sm">Refresh</button>
      </div>
      {error && <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>}
      <div className="grid gap-4">
        {institutions.map((institution) => (
          <article key={institution.id} className="rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div><h2 className="font-bold text-[#172033]">{institution.name}</h2><p className="text-xs text-[#64748b] mt-1">{institution.type || 'other'} · policy v{(institution as Institution & { settings_version?: number }).settings_version || 1}</p></div>
              <span className="rounded-full bg-[#f1f5f9] px-3 py-1 text-xs font-bold uppercase text-[#475569]">{(institution as Institution & { status?: string }).status || 'ACTIVE'}</span>
            </div>
            <div className="flex flex-wrap gap-2 mt-5">
              <button onClick={() => changeStatus(institution.id, 'ACTIVE')} className="rounded-lg bg-[#0f766e] px-3 py-2 text-xs font-semibold text-white">Activate</button>
              <button onClick={() => changeStatus(institution.id, 'SUSPENDED')} className="rounded-lg border border-amber-300 px-3 py-2 text-xs font-semibold text-amber-700">Suspend</button>
              <button onClick={() => changeStatus(institution.id, 'ARCHIVED')} className="rounded-lg border border-red-200 px-3 py-2 text-xs font-semibold text-red-700">Archive</button>
            </div>
          </article>
        ))}
        {!institutions.length && <div className="rounded-2xl border border-dashed border-[#cbd5e1] bg-white p-10 text-center text-sm text-[#64748b]">No institutions provisioned yet.</div>}
      </div>
    </div>
  )
}

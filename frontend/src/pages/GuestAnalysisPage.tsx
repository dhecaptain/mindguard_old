import { useEffect, useMemo, useState } from 'react'
import Plot from '../lib/plotly'
import api from '../api/client'
import SocioEconomicPanel from '../components/analysis/SocioEconomicPanel'
import type { SocioeconomicSignal } from '../types'

type Result = { platform:string;status:string;overall?:number;n_posts?:number;message?:string;ownership_status:string;analysed_at:string;posts?:Array<{text:string;risk_score?:number}>;signals?:Record<string,SocioeconomicSignal[]> }
type GuestCase = { id:string;case_code:string;status:string;consent_method?:string;consented_at?:string;expires_at:string;created_at:string;notes?:Array<{type:string;private_note:string;visitor_update?:string;created_at:string}> }

const inputClass = 'min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm focus:border-teal-700 focus:outline-none'

export default function GuestAnalysisPage() {
  const [handles,setHandles] = useState({reddit:'',bluesky:'',mastodon:''})
  const [activeCase,setActiveCase] = useState<(GuestCase & {consent_url?:string})|null>(null)
  const [cases,setCases] = useState<GuestCase[]>([])
  const [results,setResults] = useState<Result[]>([])
  const [busy,setBusy] = useState(false)
  const [message,setMessage] = useState('')
  const [privateNote,setPrivateNote] = useState('')
  const [visitorUpdate,setVisitorUpdate] = useState('')
  const [referralNote,setReferralNote] = useState('')

  const loadCases = async () => setCases((await api.get('/v1/guest-analysis/cases')).data)
  useEffect(() => {
    let active = true
    api.get('/v1/guest-analysis/cases')
      .then(({ data }) => { if (active) setCases(data) })
      .catch(() => { if (active) setMessage('Could not load guest cases.') })
    return () => { active = false }
  }, [])
  const selected = useMemo(()=>Object.fromEntries(Object.entries(handles).filter(([,v])=>v.trim()).map(([k,v])=>[k,v.trim()])),[handles])

  const createCase = async () => {
    if (!Object.keys(selected).length) return
    setBusy(true);setMessage('')
    try { const {data}=await api.post('/v1/guest-analysis/cases',{platforms:selected});setActiveCase({...data});setResults([]);setMessage('Case created. Let the visitor review the consent link, or record an in-person attestation.');await loadCases() }
    catch(e){setMessage(e instanceof Error?e.message:'Unable to create guest case.')}
    finally{setBusy(false)}
  }
  const attest = async () => {
    if(!activeCase)return
    setBusy(true);setMessage('')
    try{await api.post(`/v1/guest-analysis/cases/${activeCase.id}/attest`,{confirmed:true});setActiveCase({...activeCase,status:'consented',consent_method:'counsellor_attestation',consented_at:new Date().toISOString()});setMessage('Consent attested. This authorizes the visit but does not technically verify account ownership.');await loadCases()}
    catch(e){setMessage(e instanceof Error?e.message:'Unable to record consent.')}
    finally{setBusy(false)}
  }
  const run = async()=>{
    if(!activeCase)return
    setBusy(true);setMessage('Running public-profile analysis…')
    try{const {data}=await api.post(`/v1/guest-analysis/cases/${activeCase.id}/run`);setResults(data.results);setMessage(data.ownership_warning);await loadCases()}
    catch(e){setMessage(e instanceof Error?e.message:'Guest analysis failed.')}
    finally{setBusy(false)}
  }
  const openCase=async(id:string)=>{
    setBusy(true);setMessage('')
    try{const {data}=await api.get(`/v1/guest-analysis/cases/${id}`);setActiveCase({...data.case,notes:data.notes||[]});setResults(data.sessions?.[0]?.results||[])}catch(e){setMessage(e instanceof Error?e.message:'Unable to open case.')}finally{setBusy(false)}
  }
  const renewConsent=async()=>{if(!activeCase)return;try{const {data}=await api.post(`/v1/guest-analysis/cases/${activeCase.id}/renew-consent`);setActiveCase({...activeCase,status:'pending_consent',consent_url:data.consent_url,consent_method:undefined,consented_at:undefined});setMessage('Fresh consent is required before these authorized handles can be analysed again.')}catch(e){setMessage(e instanceof Error?e.message:'Unable to renew consent.')}}
  const saveCaseNote=async()=>{if(!activeCase||!privateNote.trim())return;setBusy(true);try{await api.post(`/v1/guest-analysis/cases/${activeCase.id}/notes`,{private_note:privateNote,visitor_update:visitorUpdate||null});setPrivateNote('');setVisitorUpdate('');await openCase(activeCase.id);setMessage('Private guest case note saved. Any visitor update is separately shared.')}catch(e){setMessage(e instanceof Error?e.message:'Unable to save case note.')}finally{setBusy(false)}}
  const refer=async()=>{if(!activeCase||!referralNote.trim())return;setBusy(true);try{await api.post(`/v1/guest-analysis/cases/${activeCase.id}/referrals`,{note:referralNote});setReferralNote('');await openCase(activeCase.id);setMessage('Referral was recorded in this pseudonymous guest case.')}catch(e){setMessage(e instanceof Error?e.message:'Unable to record referral.')}finally{setBusy(false)}}
  const closeCase=async()=>{if(!activeCase||!window.confirm('Close this guest case? Further analysis will stop.'))return;try{await api.post(`/v1/guest-analysis/cases/${activeCase.id}/close`);setActiveCase({...activeCase,status:'closed'});setMessage('Guest case closed.')}catch(e){setMessage(e instanceof Error?e.message:'Unable to close the case.')}}
  const deleteCase=async()=>{if(!activeCase||!window.confirm('Permanently remove this guest case’s handles, retrieved content, results and notes now? This cannot be undone.'))return;try{await api.delete(`/v1/guest-analysis/cases/${activeCase.id}`);setActiveCase(null);setResults([]);setMessage('Guest case sensitive data was permanently deleted; a minimal audit entry remains.');await loadCases()}catch(e){setMessage(e instanceof Error?e.message:'Unable to delete the guest case.')}}
  const complete=results.filter(r=>r.status==='complete'&&Number.isFinite(Number(r.overall)))
  const riskBuckets = useMemo(() => {
    const counts = { Low: 0, Moderate: 0, High: 0, Critical: 0 }
    for (const result of complete) for (const post of result.posts || []) {
      const score = Number(post.risk_score)
      if (!Number.isFinite(score)) continue
      if (score >= .75) counts.Critical += 1
      else if (score >= .55) counts.High += 1
      else if (score >= .35) counts.Moderate += 1
      else counts.Low += 1
    }
    return counts
  }, [complete])
  const combinedSignals = useMemo(() => {
    const signals: Record<string, SocioeconomicSignal[]> = {}
    for (const result of complete) for (const [category, items] of Object.entries(result.signals || {})) {
      const existing = signals[category] || []
      for (const item of items) {
        if (!existing.some((current) => current.keyword === item.keyword && current.snippet === item.snippet)) existing.push(item)
      }
      signals[category] = existing
    }
    return signals
  }, [complete])
  const riskBucketTotal = Object.values(riskBuckets).reduce((sum, count) => sum + count, 0)
  const signalCount = Object.values(combinedSignals).reduce((sum, items) => sum + items.length, 0)

  return <main className="mx-auto max-w-6xl space-y-6 p-5 md:p-8">
    <header><p className="text-xs font-bold uppercase tracking-[.16em] text-teal-700">Pseudonymous visitor workflow</p><h1 className="mt-1 text-3xl font-bold text-slate-900">Guest analysis</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">For an in-person visitor who does not want a MindGuard account. Document consent before analysis. Counsellor attestation records authorization but does not prove ownership of a social account.</p></header>
    <section className="grid gap-6 lg:grid-cols-[1.4fr_.8fr]">
      <div className="rounded-2xl border bg-white p-5 shadow-sm"><h2 className="font-bold">Start a private guest case</h2><div className="mt-4 grid gap-3 sm:grid-cols-2"><label className="text-sm font-medium">Reddit username<input className={`${inputClass} mt-1`} value={handles.reddit} onChange={e=>setHandles({...handles,reddit:e.target.value})} placeholder="u/username" /></label><label className="text-sm font-medium">Bluesky handle<input className={`${inputClass} mt-1`} value={handles.bluesky} onChange={e=>setHandles({...handles,bluesky:e.target.value})} placeholder="name.bsky.social" /></label><label className="text-sm font-medium sm:col-span-2">Mastodon handle<input className={`${inputClass} mt-1`} value={handles.mastodon} onChange={e=>setHandles({...handles,mastodon:e.target.value})} placeholder="name@instance.social" /></label></div><p className="mt-3 text-xs text-slate-500">Only public posts are retrieved. MindGuard never requests social-media passwords or visitor API credentials.</p><button disabled={busy||!Object.keys(selected).length} onClick={createCase} className="mt-4 min-h-11 rounded-xl bg-teal-700 px-5 text-sm font-bold text-white disabled:opacity-50">{busy?'Working…':'Create consent session'}</button></div>
      <aside className="rounded-2xl border bg-white p-5 shadow-sm"><h2 className="font-bold">Recent guest cases</h2><div className="mt-3 space-y-2">{cases.length?cases.map(c=><button key={c.id} onClick={()=>void openCase(c.id)} className="block w-full rounded-xl border p-3 text-left hover:border-teal-500"><span className="block font-semibold">{c.case_code}</span><span className="text-xs text-slate-500">{c.status.replaceAll('_',' ')} · expires {new Date(c.expires_at).toLocaleDateString()}</span></button>):<p className="text-sm text-slate-500">No guest cases yet.</p>}</div></aside>
    </section>
    {activeCase&&<section className="rounded-2xl border bg-white p-5 shadow-sm"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs uppercase text-slate-500">Current case</p><h2 className="text-xl font-bold">{activeCase.case_code}</h2><p className="mt-1 text-xs text-slate-500">Sensitive records are scheduled for deletion after {new Date(activeCase.expires_at).toLocaleDateString()}.</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold uppercase">{activeCase.status.replaceAll('_',' ')}</span></div>{activeCase.consent_url&&<div className="mt-4 rounded-xl bg-teal-50 p-4"><p className="text-sm font-semibold text-teal-950">Visitor consent link</p><p className="mt-1 break-all text-xs text-teal-900">{activeCase.consent_url}</p><button onClick={()=>navigator.clipboard.writeText(activeCase.consent_url!)} className="mt-2 text-sm font-bold text-teal-800 underline">Copy link</button></div>}{activeCase.status==='pending_consent'&&<div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-sm text-amber-950">If the visitor gave informed consent in person, you may attest it here. This does not verify that the handles belong to them.</p><button disabled={busy} onClick={attest} className="mt-3 rounded-lg bg-amber-800 px-4 py-2 text-sm font-bold text-white">Record in-person consent</button></div>}<div className="mt-4 flex flex-wrap gap-2"><button disabled={busy||activeCase.status!=='consented'} onClick={run} className="min-h-11 rounded-xl bg-teal-700 px-5 text-sm font-bold text-white disabled:opacity-50">{busy?'Analysing…':'Run authorized platforms'}</button>{['analysed','consented'].includes(activeCase.status)&&<button onClick={()=>void renewConsent()} className="min-h-11 rounded-xl border px-4 text-sm font-semibold">Request fresh consent to analyse again</button>}{!['closed','deleted','expired_deleted'].includes(activeCase.status)&&<button onClick={()=>void closeCase()} className="min-h-11 rounded-xl border px-4 text-sm font-semibold">Close case</button>}<button onClick={()=>void deleteCase()} className="min-h-11 rounded-xl border border-rose-300 px-4 text-sm font-semibold text-rose-800">Delete sensitive case data now</button></div>
      <div className="mt-5 grid gap-4 lg:grid-cols-2"><section className="rounded-xl border p-4"><h3 className="font-semibold">Record care note</h3><p className="mt-1 text-xs text-slate-500">Private note is visible only to authorized counsellors. Visitor update is a separate, optional message.</p><textarea value={privateNote} onChange={e=>setPrivateNote(e.target.value)} className="mt-3 min-h-24 w-full rounded-lg border p-3" placeholder="Private case note"/><textarea value={visitorUpdate} onChange={e=>setVisitorUpdate(e.target.value)} className="mt-2 min-h-20 w-full rounded-lg border p-3" placeholder="Optional visitor-safe summary"/><button disabled={busy||!privateNote.trim()||['closed','declined','deleted','expired_deleted'].includes(activeCase.status)} onClick={()=>void saveCaseNote()} className="mt-3 rounded-lg bg-slate-900 px-4 py-2 text-sm font-bold text-white">Save note</button></section><section className="rounded-xl border p-4"><h3 className="font-semibold">Record a referral</h3><p className="mt-1 text-xs text-slate-500">This referral stays attached to the pseudonymous guest record and does not create an account or alert HR.</p><textarea value={referralNote} onChange={e=>setReferralNote(e.target.value)} className="mt-3 min-h-24 w-full rounded-lg border p-3" placeholder="Referral pathway and follow-up details"/><button disabled={busy||!referralNote.trim()||['closed','declined','deleted','expired_deleted'].includes(activeCase.status)} onClick={()=>void refer()} className="mt-3 rounded-lg border px-4 py-2 text-sm font-bold">Record referral</button></section></div>{activeCase.notes?.length? <div className="mt-4 space-y-2"><h3 className="font-semibold">Case history</h3>{activeCase.notes.map((n,index)=><article key={`${n.created_at}-${index}`} className="rounded-lg bg-slate-50 p-3 text-sm"><p className="text-xs font-semibold uppercase text-slate-500">{n.type.replaceAll('_',' ')} · {new Date(n.created_at).toLocaleString()}</p><p className="mt-1">{n.private_note}</p>{n.visitor_update&&<p className="mt-2 text-teal-900"><strong>Visitor update:</strong> {n.visitor_update}</p>}</article>)}</div>:null}</section>}
    {message&&<p role="status" className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-900">{message}</p>}
    {results.length > 0 && <section className="space-y-4">
      <div className="rounded-2xl border bg-white p-5 shadow-sm">
        <h2 className="font-bold">Platform comparison</h2>
        {complete.length > 0 ? <Plot
          data={[{ type: 'bar', x: complete.map(r => r.platform), y: complete.map(r => Math.max(0, Math.min(1, Number(r.overall)))), marker: { color: '#0f766e' }, text: complete.map(r => `${(Number(r.overall) * 100).toFixed(0)}%`), textposition: 'outside' }]}
          layout={{ height: 320, margin: { l: 45, r: 20, t: 20, b: 40 }, yaxis: { range: [0, 1.1], tickformat: '.0%' }, paper_bgcolor: 'transparent', plot_bgcolor: '#fff' }}
          config={{ responsive: true, displaylogo: false, toImageButtonOptions: { filename: `mindguard-${activeCase?.case_code || 'guest'}-platforms` } }}
          className="w-full"
        /> : <p className="mt-3 text-sm text-slate-500">No completed platform result is available to chart.</p>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{results.map(r => <article key={r.platform} className="rounded-2xl border bg-white p-5">
        <div className="flex justify-between"><h3 className="font-bold capitalize">{r.platform}</h3><span className={`text-xs font-bold ${r.status === 'complete' ? 'text-emerald-700' : 'text-red-700'}`}>{r.status}</span></div>
        {r.status === 'complete' ? <><p className="mt-3 text-3xl font-bold text-teal-800">{(Number(r.overall) * 100).toFixed(0)}%</p><p className="text-sm text-slate-500">{r.n_posts} public items reviewed</p></> : <p className="mt-3 text-sm text-red-700">{r.message}</p>}
        <p className="mt-3 text-xs text-amber-800">Visitor-authorized · ownership not technically verified</p>
      </article>)}</div>
      {riskBucketTotal > 0 && <div className="rounded-2xl border bg-white p-5 shadow-sm">
        <h2 className="font-bold">Reviewed-item distribution</h2>
        <p className="mt-1 text-sm text-slate-500">Interactive distribution of the individual public items reviewed across the authorized guest platforms.</p>
        <Plot data={[{type:'pie',labels:Object.keys(riskBuckets),values:Object.values(riskBuckets),hole:.45,marker:{colors:['#059669','#d97706','#ea580c','#dc2626']},textinfo:'label+percent'}]} layout={{height:320,margin:{l:30,r:30,t:20,b:20},paper_bgcolor:'transparent',showlegend:true}} config={{responsive:true,displaylogo:false,toImageButtonOptions:{filename:`mindguard-${activeCase?.case_code||'guest'}-risk-distribution`}}} className="w-full"/>
      </div>}
      {signalCount > 0 && <div className="rounded-2xl border bg-white p-5 shadow-sm">
        <h2 className="font-bold">Combined socio-economic context</h2>
        <p className="mt-1 text-sm text-slate-500">Keyword matches provide supporting context only and are not proof of suicidal intent.</p>
        <div className="mt-4"><SocioEconomicPanel signals={combinedSignals}/></div>
      </div>}
      <div className="overflow-hidden rounded-2xl border bg-white shadow-sm">
        <div className="border-b p-5"><h2 className="font-bold">Detailed authorized result table</h2></div>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-slate-600"><tr><th className="p-3">Platform</th><th className="p-3">Status</th><th className="p-3">Signal</th><th className="p-3">Items</th><th className="p-3">Analysed</th></tr></thead><tbody>{results.map(r=><tr key={`detail-${r.platform}`} className="border-t"><td className="p-3 font-semibold capitalize">{r.platform}</td><td className="p-3 capitalize">{r.status}</td><td className="p-3">{r.status==='complete'&&Number.isFinite(Number(r.overall))?`${(Number(r.overall)*100).toFixed(0)}%`:'—'}</td><td className="p-3">{r.n_posts??'—'}</td><td className="p-3">{new Date(r.analysed_at).toLocaleString()}</td></tr>)}</tbody></table></div>
      </div>
    </section>}
  </main>
}

export function GuestConsentPage(){
  const token=new URLSearchParams(window.location.search).get('token')||''
  const [accepted,setAccepted]=useState(false);const [status,setStatus]=useState('');const [busy,setBusy]=useState(false)
  const [details,setDetails]=useState<{case_code:string;consent_expires_at:string;retention_expires_at:string;accounts:Array<{platform:string;handle:string;ownership_status:string}>}|null>(null)
  useEffect(() => {
    if (!token) return
    let active = true
    api.get('/v1/guest-analysis/consent', { params: { token } })
      .then(({ data }) => { if (active) setDetails(data) })
      .catch((error: unknown) => {
        if (active) setStatus(error instanceof Error ? error.message : 'This consent link is invalid or expired.')
      })
    return () => { active = false }
  }, [token])
  const submit=async(choice:boolean)=>{if(!details)return;setBusy(true);try{const {data}=await api.post('/v1/guest-analysis/consent',{token,accepted:choice});setStatus(choice?`You authorized the listed profiles for case ${data.case_code}. You may return to the counsellor.`:'You declined. The saved handles were deleted and no analysis will be run.');if(!choice)setDetails(null);window.history.replaceState({},'',window.location.pathname); }catch(e){setStatus(e instanceof Error?e.message:'Unable to record your decision.')}finally{setBusy(false)}}
  return <main className="min-h-screen bg-slate-50 p-5"><section className="mx-auto mt-12 max-w-xl rounded-2xl border bg-white p-7 shadow-sm"><p className="text-xs font-bold uppercase tracking-widest text-teal-700">MindGuard guest analysis</p><h1 className="mt-2 text-2xl font-bold">Review consent</h1>{!token?<p className="mt-4 rounded-lg bg-slate-100 p-3 text-sm text-slate-700">This consent link is missing or invalid.</p>:details?<><p className="mt-2 text-sm text-slate-600">Pseudonymous case <strong>{details.case_code}</strong>. This one-time decision link expires {new Date(details.consent_expires_at).toLocaleString()}.</p><div className="mt-5 rounded-xl border border-teal-100 bg-teal-50 p-4"><h2 className="font-semibold text-teal-950">Exact public accounts proposed</h2><ul className="mt-2 space-y-2 text-sm text-teal-950">{details.accounts.map(account=><li key={account.platform} className="flex flex-wrap justify-between gap-2"><span><strong className="capitalize">{account.platform}</strong> · {account.handle}</span><span className="text-xs">ownership not technically verified</span></li>)}</ul></div><ul className="mt-5 space-y-3 text-sm text-slate-700"><li>Only the exact public profiles above will be retrieved for this decision. No other handle can be substituted without fresh consent.</li><li>Your authorization does not create a MindGuard account. A counsellor may retain this pseudonymous case until {new Date(details.retention_expires_at).toLocaleDateString()}, or delete it earlier if requested.</li><li>MindGuard provides decision support, not a diagnosis or emergency service. A counsellor attestation or your consent does not technically verify account ownership.</li></ul><label className="mt-6 flex gap-3 text-sm"><input type="checkbox" checked={accepted} onChange={e=>setAccepted(e.target.checked)} className="mt-1"/><span>I reviewed these exact accounts and voluntarily authorize this analysis.</span></label><div className="mt-5 grid gap-3 sm:grid-cols-2"><button disabled={!accepted||busy} onClick={()=>void submit(true)} className="min-h-12 rounded-xl bg-teal-700 p-3 font-bold text-white disabled:opacity-50">{busy?'Saving…':'Accept consent'}</button><button disabled={busy} onClick={()=>void submit(false)} className="min-h-12 rounded-xl border border-rose-300 p-3 font-bold text-rose-800 disabled:opacity-50">Decline and delete handles</button></div></>:<p className="mt-4 rounded-lg bg-slate-100 p-3 text-sm text-slate-700">{status||'Loading the exact accounts covered by this request…'}</p>}{status&&details&&<p role="status" className="mt-4 rounded-lg bg-slate-100 p-3 text-sm">{status}</p>}</section></main>
}

import Plot from '../../lib/plotly'

export type Insights = {
  state: 'AVAILABLE'|'INSUFFICIENT_DATA'|'NOT_ENTITLED'|'WORKPLACE_INACTIVE'|'NO_DATA'
  minimum_cohort: number
  privacy_message: string
  period: string | null
  overview: {wellbeing_indicator:number;scale:string;contributors:string;checkins:string;trend_direction:string;change_from_previous_period:number|null}|null
  themes: Array<{key:string;label:string;average:number;scale:string}>
  risk_distribution: {state:string;message:string}
  trends: Array<{period:string;state:string;averages?:Record<string,number>;wellbeing_indicator?:number;contributors?:string;checkins?:string}>
  comparison: {state:string;current_period?:string;previous_period?:string;changes?:Record<string,number>|null}
  recommendations: Array<{title:string;detail:string}>
}

const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm'
const chartSeries = [
  {key:'wellbeing_indicator',label:'Overall wellbeing'},
  {key:'mood',label:'Mood'},
  {key:'stress',label:'Stress manageability'},
  {key:'support_access',label:'Perceived support'},
]

export default function WorkplaceInsightsDashboard({data,loading,error,onRetry}:{data:Insights|null;loading:boolean;error:string;onRetry:()=>void}) {
  const periods=data?.trends||[]
  const availablePeriods=periods.filter(period=>period.state==='AVAILABLE')
  const stateLabel=data?.state==='INSUFFICIENT_DATA'?'More participation needed':data?.state==='NOT_ENTITLED'?'Not included in plan':data?.state==='WORKPLACE_INACTIVE'?'Workplace inactive':data?.state==='NO_DATA'?'No completed-period data':'Protected insights'
  return <section className={card} aria-labelledby="workplace-insights-title">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-bold uppercase tracking-wider text-emerald-700">Workplace Insights</p><h2 id="workplace-insights-title" className="mt-1 text-xl font-semibold">Organizational wellbeing</h2><p className="mt-1 text-sm text-slate-600">Aggregated patterns from completed months, shown only when privacy thresholds are met.</p></div>
      {loading&&!data?<span role="status" className="animate-pulse rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500">Loading insights…</span>:data&&<span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">{stateLabel}</span>}
    </header>
    {error&&<div role="alert" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"><span>Insights could not be loaded. Check workplace access and try again.</span><button className="font-semibold underline focus-visible:outline focus-visible:outline-2" onClick={onRetry}>Retry</button></div>}
    {loading&&!data&&!error&&<div className="mt-5 grid animate-pulse gap-3 sm:grid-cols-3" aria-hidden="true"><div className="h-24 rounded-xl bg-slate-100"/><div className="h-24 rounded-xl bg-slate-100"/><div className="h-24 rounded-xl bg-slate-100"/></div>}
    {data&&data.state!=='AVAILABLE'&&<p role="status" className={`mt-4 rounded-xl p-4 text-sm ${data.state==='INSUFFICIENT_DATA'?'border border-amber-200 bg-amber-50 text-amber-950':'bg-slate-50 text-slate-700'}`}>{data.privacy_message}</p>}
    {data?.state==='AVAILABLE'&&data.overview&&<>
      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <article className="rounded-xl border border-emerald-100 bg-emerald-50/70 p-4"><p className="text-xs font-semibold uppercase tracking-wide text-emerald-800">Wellbeing indicator</p><p className="mt-2 text-3xl font-bold text-slate-900">{data.overview.wellbeing_indicator}<span className="text-base font-medium text-slate-500"> / 5</span></p><p className="mt-1 text-xs text-slate-600">{data.period} · higher is more positive</p></article>
        <article className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Contributing participants</p><p className="mt-2 text-2xl font-bold">{data.overview.contributors}</p><p className="mt-1 text-xs text-slate-600">Coarsened minimum only</p></article>
        <article className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Check-in activity</p><p className="mt-2 text-2xl font-bold">{data.overview.checkins}</p><p className="mt-1 text-xs text-slate-600">Coarsened minimum only</p></article>
        <article className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Period movement</p><p className="mt-2 text-xl font-bold capitalize">{data.overview.trend_direction}</p><p className="mt-1 text-xs text-slate-600">Compared with the prior completed month</p></article>
      </div>
      <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(17rem,1fr)]">
        <article className="min-w-0 rounded-xl border border-slate-200 p-4"><h3 className="font-semibold">Wellbeing trend</h3><p className="mt-1 text-xs text-slate-500">Each month is checked independently. Withheld periods appear as gaps, never as zero.</p>{availablePeriods.length?<Plot data={chartSeries.map(series=>({type:'scatter' as const,mode:'lines+markers' as const,name:series.label,x:periods.map(period=>period.period),y:periods.map(period=>period.state!=='AVAILABLE'?null:series.key==='wellbeing_indicator'?period.wellbeing_indicator??null:period.averages?.[series.key]??null),connectgaps:false}))} layout={{height:330,margin:{l:45,r:15,t:20,b:48},yaxis:{range:[1,5],title:{text:'Indicator (1–5)'}},xaxis:{title:{text:'Completed month'}},legend:{orientation:'h'},paper_bgcolor:'transparent',plot_bgcolor:'#fff'}} config={{responsive:true,displaylogo:false}} className="w-full"/>:<p className="mt-4 rounded-lg bg-slate-50 p-4 text-sm text-slate-600">No completed month currently meets the privacy threshold.</p>}
          <div className="mt-3 flex flex-wrap gap-2" aria-label="Monthly privacy availability">{periods.map(period=><span key={period.period} className={`rounded-full px-3 py-1 text-xs ${period.state==='AVAILABLE'?'bg-emerald-50 text-emerald-800':'bg-slate-100 text-slate-600'}`}>{period.period}: {period.state==='AVAILABLE'?'available':period.state==='NO_DATA'?'no data':'hidden for privacy'}</span>)}</div>
          <details className="mt-3"><summary className="cursor-pointer text-sm font-semibold text-emerald-800 focus-visible:outline focus-visible:outline-2">View chart values in a table</summary><div className="mt-2 overflow-x-auto"><table className="w-full min-w-[28rem] text-left text-sm"><caption className="sr-only">Aggregated monthly workplace insights</caption><thead><tr className="border-b text-xs uppercase text-slate-500"><th className="p-2">Month</th>{chartSeries.map(series=><th key={series.key} className="p-2">{series.label}</th>)}</tr></thead><tbody>{periods.map(period=><tr key={period.period} className="border-b"><th className="p-2 font-medium">{period.period}</th>{chartSeries.map(series=><td key={series.key} className="p-2">{period.state==='AVAILABLE'?(series.key==='wellbeing_indicator'?period.wellbeing_indicator:period.averages?.[series.key])?.toFixed(1):'Unavailable'}</td>)}</tr>)}</tbody></table></div></details>
        </article>
        <article className="rounded-xl border border-slate-200 p-4"><h3 className="font-semibold">Wellbeing themes</h3><p className="mt-1 text-xs text-slate-500">Broad self-reported dimensions only; average response on a 1–5 scale.</p><div className="mt-3 space-y-3">{data.themes.map(theme=><div key={theme.key} className="rounded-lg bg-slate-50 p-3"><div className="flex items-center justify-between gap-3"><span className="text-sm font-medium">{theme.label}</span><strong>{theme.average.toFixed(1)} / 5</strong></div><div className="mt-2 h-2 rounded-full bg-slate-200"><div className="h-2 rounded-full bg-emerald-600" style={{width:`${(theme.average/5)*100}%`}}/></div></div>)}</div></article>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <article className="rounded-xl border border-slate-200 p-4"><h3 className="font-semibold">Period comparison</h3>{data.comparison.state==='AVAILABLE'&&data.comparison.changes?<><p className="mt-1 text-xs text-slate-500">{data.comparison.current_period} compared with {data.comparison.previous_period}; both periods meet the privacy threshold.</p><div className="mt-3 grid gap-2 sm:grid-cols-3">{data.themes.map(theme=>{const delta=data.comparison.changes?.[theme.key]??0;return <div key={theme.key} className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-600">{theme.label}</p><p className="mt-1 text-lg font-semibold">{delta>0?'+':''}{delta.toFixed(1)} <span className="text-xs font-normal">points</span></p></div>})}</div></>:<p role="status" className="mt-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Comparison is unavailable because both periods must independently meet the privacy threshold.</p>}</article>
        {data.recommendations.length>0&&<article className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-4"><h3 className="font-semibold">Organization-wide considerations</h3><p className="mt-1 text-xs text-slate-600">Ideas from protected aggregates, not individual or clinical guidance.</p><ul className="mt-3 space-y-2">{data.recommendations.map(item=><li key={item.title} className="rounded-lg bg-white p-3"><p className="text-sm font-semibold">{item.title}</p><p className="mt-1 text-sm text-slate-600">{item.detail}</p></li>)}</ul></article>}
      </div>
      <p className="mt-4 border-t pt-3 text-xs leading-relaxed text-slate-500">{data.privacy_message} No participation lists, worker records, support activity, or provider details are included.</p>
    </>}
  </section>
}

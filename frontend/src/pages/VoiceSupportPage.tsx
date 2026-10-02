import { useEffect, useRef, useState } from 'react'
import api from '../api/client'
import { useUiStore, type PageKey } from '../store/uiStore'

type Availability={enabled:boolean;review_gate_ready:boolean;configuration_ready:boolean;configuration_blockers:string[];care_recipient_available:boolean;care_recipient_type:string;role_type:string;workplace_checkin_available:boolean;is_minor:boolean;language:string;stores_audio:boolean;stores_transcripts:boolean;server_side_controls_ready:boolean;summary_retention_days:number}
type Session={id:string;exercise?:string;summary?:string;safety_outcome:string;alert_delivery_status?:string;created_at:string}
type CareAlert={id:string;subject_user_id:string;subject_name:string;status:string;safety_outcome:string;alert_delivery_status?:string;alert_acknowledged_at?:string;created_at:string;updated_at:string}
type ConversationPhase='connecting'|'listening'|'thinking'|'speaking'|'paused'
type AppointmentOption={id:string;starts_at:string;ends_at?:string;status:string;title?:string;provider_name:string;mode:string}
type ProviderOption={id:string;name:string;title?:string|null}
type SupportSummary={state:string;provider_name?:string|null;relationship?:string;cases?:Array<{case_id:string;status:string;created_at:string}>}
type VoiceActionResponse={result:string;message?:string;pending_action_id?:string;action?:string;stage?:string;sensitivity?:string;expires_at?:string;confirmation_prompt?:string;support?:SupportSummary;appointments?:AppointmentOption[];providers?:ProviderOption[];preparation_prompts?:string[];appointment?:AppointmentOption;navigation_target?:string;route_id?:string;case_id?:string;already_active?:boolean}
type PendingAction={id:string;action:string;sensitivity:string;prompt:string;stage?:string}

const confirmationPrompt=(action:string,roleType?:string)=>action==='propose_workplace_checkin'?'Would you like to save these answers as a private workplace check-in?':action==='propose_human_support'&&roleType==='workplace_employee'?'Would you like to request this provider and share your latest workplace check-in?':action==='propose_human_support'?'Would you like to continue with this support request?':action==='propose_summary_share'?'Would you like to share only this saved note with your provider?':'Would you like to save this note privately?'
const confirmationSensitivity=(action:string,roleType?:string)=>action==='propose_summary_share'||(action==='propose_human_support'&&roleType==='workplace_employee')?'SHARE_REQUIRED':'CONFIRM_REQUIRED'

export default function VoiceSupportPage(){
  const [availability,setAvailability]=useState<Availability|null>(null)
  const [history,setHistory]=useState<Session[]>([])
  const [accepted,setAccepted]=useState(false)
  const [exercise,setExercise]=useState('general_support')
  const [state,setState]=useState<'idle'|'connecting'|'connected'|'ending'|'error'>('idle')
  const [phase,setPhase]=useState<ConversationPhase>('connecting')
  const [muted,setMuted]=useState(false)
  const [message,setMessage]=useState('')
  const [urgent,setUrgent]=useState(false)
  const [transcript,setTranscript]=useState<string[]>([])
  const [privateSummary,setPrivateSummary]=useState('')
  const [careAlerts,setCareAlerts]=useState<CareAlert[]>([])
  const [textMode,setTextMode]=useState(false)
  const [textStep,setTextStep]=useState(0)
  const [pendingAction,setPendingAction]=useState<PendingAction|null>(null)
  const [actionMessage,setActionMessage]=useState('')
  const [supportInfo,setSupportInfo]=useState<SupportSummary|null>(null)
  const [shareCaseId,setShareCaseId]=useState('')
  const [appointments,setAppointments]=useState<AppointmentOption[]>([])
  const [providers,setProviders]=useState<ProviderOption[]>([])
  const [providerId,setProviderId]=useState('')
  const [shareLatestCheckin,setShareLatestCheckin]=useState(false)
  const [checkin,setCheckin]=useState({mood:3,stress:3,support_access:3})
  const [prepAppointment,setPrepAppointment]=useState('')
  const [prepPrompts,setPrepPrompts]=useState<string[]>([])
  const [prepNotes,setPrepNotes]=useState('')
  const setPage=useUiStore(s=>s.setPage)
  const pcRef=useRef<RTCPeerConnection|null>(null)
  const dcRef=useRef<RTCDataChannel|null>(null)
  const streamRef=useRef<MediaStream|null>(null)
  const sessionRef=useRef<string>('')
  const audioRef=useRef<HTMLAudioElement|null>(null)
  const statusTimerRef=useRef<number|null>(null)
  const lastNavigationEventRef=useRef('')

  const refresh=async()=>{const [a,h]=await Promise.all([api.get('/v1/voice/availability'),api.get('/v1/voice/sessions')]);setAvailability(a.data);setHistory(h.data);try{setCareAlerts((await api.get('/v1/voice/alerts')).data)}catch{setCareAlerts([])}}
  useEffect(()=>{void Promise.resolve().then(refresh).catch(()=>setMessage('Voice support status is temporarily unavailable.'));return()=>{const id=sessionRef.current;if(id)void api.post(`/v1/voice/sessions/${id}/close`,{}).catch(()=>{});if(statusTimerRef.current!==null)window.clearInterval(statusTimerRef.current);streamRef.current?.getTracks().forEach(t=>t.stop());pcRef.current?.close()}},[])

  const requestHumanHelp=async()=>{
    if(!sessionRef.current)return
    try{const {data}=await api.post(`/v1/voice/sessions/${sessionRef.current}/request-help`);setUrgent(true);setMessage(data.message)}catch{setUrgent(true);setMessage('Call Kenya emergency services on 999, 112, or 911, contact a trusted person, or go to the nearest health facility now.')}
  }
  const start=async()=>{
    if(!accepted)return
    setState('connecting');setMessage('Requesting microphone access…');setUrgent(false)
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:true});streamRef.current=stream
      const {data}=await api.post('/v1/voice/sessions',{accepted_notice:true,exercise})
      sessionRef.current=data.session_id
      setPhase('connecting')
      statusTimerRef.current=window.setInterval(async()=>{
        const currentId=sessionRef.current
        if(!currentId)return
        try{
          const {data:sessionState}=await api.get(`/v1/voice/sessions/${currentId}/state`)
          if(sessionState.pending_action?.id){const action=sessionState.pending_action.action;setPendingAction(current=>current?.id===sessionState.pending_action.id?current:{id:sessionState.pending_action.id,action,sensitivity:sessionState.pending_action.sensitivity||confirmationSensitivity(action,availability?.role_type),prompt:sessionState.pending_action.confirmation_prompt||confirmationPrompt(action,availability?.role_type)});setActionMessage('A MindGuard request is waiting for your confirmation.')}else setPendingAction(null)
          if(sessionState.navigation_event?.id&&sessionState.navigation_event.id!==lastNavigationEventRef.current){const pages:Partial<Record<string,PageKey>>={appointments:'appointments',communications:'communications',feedback:'feedback',workplace:'workplace','workplace-checkins':'workplace-checkins','workplace-support':'workplace-support'};const page=pages[sessionState.navigation_event.route_id];lastNavigationEventRef.current=sessionState.navigation_event.id;if(page)setPage(page)}
          if(sessionState.safety_state==='distress'||sessionState.safety_state==='heightened_concern'||sessionState.safety_state==='potential_immediate_danger'||sessionState.safety_state==='user_requested_help'){
            setUrgent(sessionState.safety_state==='potential_immediate_danger'||sessionState.safety_state==='user_requested_help')
            if(sessionState.safety_state==='potential_immediate_danger'||sessionState.safety_state==='user_requested_help')setMessage(sessionState.alert_delivery_status==='delivered'?'A safety concern was detected and an in-app alert was sent to your authorized care professional. If you are in immediate danger, call 999, 112, or 911.':'A safety concern was detected. No care professional was available to notify; call 999, 112, or 911 or go to the nearest health facility if you are in immediate danger.')
            else setMessage('It sounds like this may be especially difficult. You can pause, continue, or request support from a person.')
          }
          if(['ending','completed','failed','expired'].includes(sessionState.status)){
            if(statusTimerRef.current!==null)window.clearInterval(statusTimerRef.current)
            statusTimerRef.current=null
            streamRef.current?.getTracks().forEach(t=>t.stop());pcRef.current?.close();dcRef.current=null;pcRef.current=null;streamRef.current=null;sessionRef.current='';setPendingAction(null);setPrivateSummary('');setPrepNotes('');setPrepPrompts([])
            setState(sessionState.status==='failed'?'error':'idle')
            if(sessionState.status==='failed')setMessage('The voice connection ended unexpectedly. Your microphone audio and live transcript were not stored by MindGuard. You can try again or use the text alternative.')
            else if(sessionState.status==='expired')setMessage('This voice session reached its time limit and has ended.')
          }
        }catch{setMessage('Connection status is temporarily unavailable. Ending locally remains available.')}
      },2000)
      const pc=new RTCPeerConnection();pcRef.current=pc
      const audio=document.createElement('audio');audio.autoplay=true;audioRef.current=audio
      pc.ontrack=e=>{audio.srcObject=e.streams[0]}
      pc.onconnectionstatechange=()=>{if(pc.connectionState==='failed'||pc.connectionState==='closed'){setMessage('The voice connection was interrupted. Your microphone audio was not stored by MindGuard.');if(sessionRef.current)void api.post(`/v1/voice/sessions/${sessionRef.current}/close`,{}).catch(()=>{});setState('error')}}
      stream.getTracks().forEach(track=>pc.addTrack(track,stream))
      const dc=pc.createDataChannel('oai-events');dcRef.current=dc
      dc.addEventListener('open',()=>{setState('connected');setPhase('listening');setMessage(data.care_recipient_available?'Connected. Your authorized care professional can receive an urgent safety alert if the server determines one is needed.':'Connected. No care professional is currently linked; emergency resources remain available.')})
      dc.addEventListener('message',event=>{
        try{const payload=JSON.parse(event.data);if(payload.type==='input_audio_buffer.speech_started'){setPhase('listening')}else if(payload.type==='response.created'){setPhase('thinking')}else if(payload.type==='response.output_audio.delta'||payload.type==='response.output_audio_transcript.delta'){setPhase('speaking')}else if(payload.type==='response.done'){setPhase(muted?'paused':'listening');const calls=payload.response?.output?.some((item:{type?:string})=>item.type==='function_call');setActionMessage(calls?'Checking your MindGuard request…':'')}else if(payload.type==='conversation.item.input_audio_transcription.completed'&&payload.transcript){setTranscript(items=>[...items,`You: ${String(payload.transcript).slice(0,4000)}`].slice(-8))}else if((payload.type==='response.output_audio_transcript.done'||payload.type==='response.output_audio_transcript.delta')&&payload.transcript){setTranscript(items=>[...items,`MindGuard AI: ${String(payload.transcript).slice(0,4000)}`].slice(-8))}}catch{/* ignore malformed provider events */}
      })
      dc.addEventListener('close',()=>{setState(current=>current==='ending'?'idle':'error');setMessage('The voice connection ended. Your audio was not stored by MindGuard.')})
      const offer=await pc.createOffer();await pc.setLocalDescription(offer)
      const {data:answer}=await api.post(`/v1/voice/sessions/${data.session_id}/connect`,{sdp:offer.sdp})
      await pc.setRemoteDescription({type:'answer',sdp:answer.answer_sdp})
    }catch(e){const id=sessionRef.current;if(id){await api.post(`/v1/voice/sessions/${id}/close`,{}).catch(()=>{});sessionRef.current=''}if(statusTimerRef.current!==null)window.clearInterval(statusTimerRef.current);statusTimerRef.current=null;streamRef.current?.getTracks().forEach(t=>t.stop());pcRef.current?.close();pcRef.current=null;dcRef.current=null;streamRef.current=null;setState('error');setMessage(e instanceof DOMException&&e.name==='NotAllowedError'?'Microphone permission was denied. You can use the text-based alternative, urgent-help options, or crisis resources instead.':e instanceof Error?e.message:'Voice support could not start.')}
  }
  const end=async()=>{
    const id=sessionRef.current;if(!id)return
    setState('ending')
    if(statusTimerRef.current!==null)window.clearInterval(statusTimerRef.current);statusTimerRef.current=null
    try{await api.post(`/v1/voice/sessions/${id}/close`,{exercise});await refresh()}catch{/* session can still close locally */}
    streamRef.current?.getTracks().forEach(t=>t.stop());pcRef.current?.close();dcRef.current=null;pcRef.current=null;streamRef.current=null;sessionRef.current='';setPendingAction(null)
    setTranscript([])
    setPrivateSummary('');setPrepNotes('');setPrepPrompts([]);setPendingAction(null)
    setState('idle');setPhase('listening');setMessage('Session ended. MindGuard did not store microphone audio or live transcripts.')
  }
  const toggleMute=()=>{const next=!muted;streamRef.current?.getAudioTracks().forEach(t=>{t.enabled=!next});setMuted(next);setPhase(next?'paused':'listening')}
  const interrupt=()=>{if(dcRef.current?.readyState==='open')dcRef.current.send(JSON.stringify({type:'response.cancel'}));setPhase('listening')}
  const acknowledge=async(id:string)=>{try{await api.post(`/v1/voice/alerts/${id}/acknowledge`);setCareAlerts(items=>items.map(item=>item.id===id?{...item,alert_delivery_status:'acknowledged'}:item))}catch{setMessage('Unable to acknowledge this care alert.')}}
  const runAction=async(action:string,payload:Record<string,unknown>={}):Promise<VoiceActionResponse|null>=>{
    if(!sessionRef.current){setActionMessage('Start a voice session before using MindGuard actions.');return null}
    setActionMessage('Checking your request…')
    try{
      const {data}=await api.post<VoiceActionResponse>(`/v1/voice/sessions/${sessionRef.current}/actions`,{action,payload})
      if(data.result==='CONFIRMATION_REQUIRED'&&data.pending_action_id){setPendingAction({id:data.pending_action_id,action:data.action||action,sensitivity:data.sensitivity||'CONFIRM_REQUIRED',prompt:data.confirmation_prompt||confirmationPrompt(data.action||action),stage:data.stage})}
      else if(data.result!=='SUCCESS'){setActionMessage(data.message||'I could not complete that action. Your conversation can continue.')}
      else{setActionMessage(data.message||(action==='get_my_upcoming_appointments'&&data.appointments?.length===0?'You have no upcoming appointments right now.':action==='get_my_current_support'&&data.support?.state==='none'?'No active support relationship is linked to this account.':'Done.'));if(data.support)setSupportInfo(data.support);if(data.appointments)setAppointments(data.appointments);if(data.providers)setProviders(data.providers);if(data.preparation_prompts)setPrepPrompts(data.preparation_prompts)}
      return data
    }catch{setActionMessage('I could not complete that action right now. Your conversation can continue.');return null}
  }
  const confirmAction=async(confirmed:boolean)=>{
    if(!sessionRef.current||!pendingAction)return
    try{const {data}=await api.post<VoiceActionResponse>(`/v1/voice/sessions/${sessionRef.current}/actions/${pendingAction.id}/confirm`,{confirmed});if(data.result==='CONFIRMATION_REQUIRED'&&data.pending_action_id){setPendingAction({id:data.pending_action_id,action:data.action||pendingAction.action,sensitivity:data.sensitivity||pendingAction.sensitivity,prompt:data.confirmation_prompt||pendingAction.prompt,stage:data.stage});setActionMessage('Check-in sharing consent recorded. Please review the final support request.');return}setPendingAction(null);setActionMessage(data.message|| (data.result==='SUCCESS'?'Done.':'I could not complete that action.'));if(data.result==='SUCCESS'&&pendingAction.action==='propose_private_summary'){setPrivateSummary('');await refresh()}if(data.result==='SUCCESS'&&pendingAction.action==='propose_human_support')await runAction('get_my_current_support');if(data.result!=='SUCCESS')setActionMessage(data.message||'I could not complete that action. Your conversation can continue.')}
    catch{setPendingAction(null);setActionMessage('I could not confirm that action. Nothing should be assumed to have changed.')}
  }
  const openDestination=async(target:string)=>{
    const response=await runAction('navigate',{target})
    const pages:Partial<Record<string,PageKey>>={appointments:'appointments',communications:'communications',feedback:'feedback',workplace:'workplace', 'workplace-checkins':'workplace-checkins','workplace-support':'workplace-support'}
    const page=response?.result==='SUCCESS'&&response.route_id?pages[response.route_id]:undefined
    if(page)setPage(page)
  }
  const prepareAppointment=async()=>{
    if(!prepAppointment)return
    const response=await runAction('prepare_for_appointment',{appointment_id:prepAppointment})
    if(response?.result==='SUCCESS'&&response.appointment){setPrepPrompts(response.preparation_prompts||[]);setPrepNotes(`Preparing for ${response.appointment.title||'my appointment'} on ${new Date(response.appointment.starts_at).toLocaleString()}\n\n`)}
  }
  const savePrepAsNote=()=>{setPrivateSummary(prepNotes.trim());setActionMessage('Your preparation remains a draft. Review it below and choose Save privately if you want to keep it.')}
  const available=availability?.enabled&&availability?.review_gate_ready&&availability?.configuration_ready&&availability?.server_side_controls_ready
  const configurationBlockers=availability?.configuration_blockers||[]
  const textPrompts=['Pause and feel both feet supported by the floor.','Name five things you can see around you.','Notice four things you can feel, such as your clothing or the chair.','Listen for three sounds, near or far.','Take one comfortable breath and choose a person or small next step that could support you.']

  return <main className="mx-auto max-w-5xl space-y-6 p-5 md:p-8"><header><p className="text-xs font-bold uppercase tracking-[.16em] text-teal-700">Immediate grounding support</p><h1 className="mt-1 text-3xl font-bold">Voice companion</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">Speak with an English-language AI grounding companion for paced breathing, orientation, and calm next steps. Microphone audio is streamed to OpenAI Realtime to provide the conversation; MindGuard does not store raw audio or live transcripts. It is not a counsellor, diagnosis, or emergency service.</p></header>
    {!available&&<section className="rounded-2xl border border-amber-200 bg-amber-50 p-5"><h2 className="font-bold text-amber-950">Voice support is not active yet</h2><p className="mt-2 text-sm text-amber-900">This feature stays unavailable until clinical, child-safeguarding, privacy, and accessibility reviews are recorded and secure provider configuration is complete.</p>{configurationBlockers.length>0&&<ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-amber-950">{configurationBlockers.map(item=><li key={item}>{item}</li>)}</ul>}</section>}
    <section className="grid gap-6 lg:grid-cols-[1.2fr_.8fr]">
      <div className="rounded-2xl border bg-white p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className={`flex h-14 w-14 items-center justify-center rounded-full ${state==='connected'&&!muted?'bg-teal-100 text-teal-800':'bg-slate-100 text-slate-500'}`}><i className="ti ti-microphone text-2xl"/></div>
          <div><h2 className="font-bold">{state==='connected'?(muted?'Microphone paused':phase==='listening'?'Listening':phase==='thinking'?'Thinking':phase==='speaking'?'Speaking':'Voice support active'):state==='idle'?'Start when you are ready':state==='error'?'Connection needs attention':state==='ending'?'Ending session':'Connecting'}</h2><p role="status" aria-live="polite" className="text-sm text-slate-500">{state==='connected'?(muted?'paused':phase):state}</p></div>
        </div>
        <label className="mt-5 block text-sm font-semibold">Optional conversation focus<select disabled={state==='connected'} value={exercise} onChange={e=>setExercise(e.target.value)} className="mt-2 min-h-11 w-full rounded-xl border p-3"><option value="general_support">Open conversation</option><option value="grounding">5-4-3-2-1 grounding</option><option value="breathing">Paced breathing</option><option value="orientation">Present-moment orientation</option><option value="supportive_conversation">Supportive conversation</option></select></label>
        <label className="mt-4 flex items-start gap-3 text-sm text-slate-700"><input type="checkbox" checked={accepted} disabled={state==='connected'} onChange={e=>setAccepted(e.target.checked)} className="mt-1"/><span>I understand microphone audio is streamed to OpenAI Realtime. Short transcript excerpts are also processed by OpenAI safety checks; MindGuard does not store raw audio or live transcripts. This is an AI support tool, not professional or emergency care. My optional private note may be retained for {availability?.summary_retention_days||30} days.</span></label>
        <div className="mt-5 flex flex-wrap gap-3">
          {state==='connected'?<><button onClick={toggleMute} aria-label={muted?'Unmute microphone':'Mute microphone'} className="rounded-xl border border-slate-300 px-5 py-3 font-bold">{muted?'Unmute':'Mute'}</button>{(phase==='speaking'||phase==='thinking')&&<button onClick={interrupt} className="rounded-xl border border-teal-700 px-5 py-3 font-bold text-teal-800">Stop speaking</button>}<button onClick={()=>void end()} className="rounded-xl bg-slate-900 px-5 py-3 font-bold text-white">End session</button></>:<button disabled={!available||!accepted||state==='connecting'||state==='ending'} onClick={()=>void start()} className="rounded-xl bg-teal-700 px-6 py-3 font-bold text-white disabled:opacity-50">{state==='connecting'?'Connecting…':'Start voice support'}</button>}
          <button onClick={()=>void requestHumanHelp()} disabled={state!=='connected'} className="rounded-xl bg-rose-700 px-5 py-3 font-bold text-white disabled:opacity-50">Request human help</button>
        </div>
        {state==='connected'&&<div aria-live="polite" className="mt-4 max-h-36 overflow-y-auto rounded-xl bg-slate-50 p-3 text-sm text-slate-700">{transcript.length?transcript.map((line,i)=><p key={`${i}-${line}`} className="mb-1">{line}</p>):<p className="text-slate-500">Live captions are temporary and discarded when the session ends.</p>}</div>}
        {message&&<p role="status" className={`mt-5 rounded-xl p-4 text-sm ${urgent?'border border-rose-300 bg-rose-50 text-rose-950':'bg-slate-50 text-slate-700'}`}>{message}</p>}
      </div>
      <aside className="space-y-4"><section className="rounded-2xl border border-rose-200 bg-rose-50 p-5"><h2 className="font-bold text-rose-950">Immediate danger</h2><p className="mt-2 text-sm text-rose-900">Call Kenya emergency services or go to the nearest health facility. MindGuard cannot guarantee an emergency response.</p><div className="mt-4 flex flex-wrap gap-2"><a href="tel:999" className="rounded-lg bg-rose-800 px-4 py-2 font-bold text-white">Call 999</a><a href="tel:112" className="rounded-lg bg-rose-800 px-4 py-2 font-bold text-white">Call 112</a><a href="tel:911" className="rounded-lg bg-rose-800 px-4 py-2 font-bold text-white">Call 911</a>{availability?.is_minor&&<a href="tel:116" className="rounded-lg border border-rose-800 px-4 py-2 font-bold text-rose-900">Child Helpline 116</a>}</div></section><section className="rounded-2xl border bg-white p-5"><h2 className="font-bold">Privacy status</h2><ul className="mt-3 space-y-2 text-sm text-slate-600"><li>Audio stored by MindGuard: no</li><li>Transcript stored by MindGuard: no</li><li>Realtime audio provider: OpenAI</li><li>Transient server safety check: OpenAI moderation</li><li>Language: English</li><li>Care recipient: {availability?.care_recipient_available?availability.care_recipient_type.replaceAll('_',' '):'none linked'}</li><li>Private note retention: {availability?.summary_retention_days||30} days</li></ul></section></aside>
    </section>
    {state==='connected'&&<section className="space-y-5 rounded-2xl border border-teal-100 bg-white p-5 shadow-sm" aria-labelledby="voice-actions-title">
      <div><p className="text-xs font-bold uppercase tracking-wider text-teal-700">Optional · always your choice</p><h2 id="voice-actions-title" className="mt-1 text-xl font-bold">MindGuard actions</h2><p className="mt-1 text-sm text-slate-600">The conversation cannot run actions by itself. MindGuard checks access, and anything saved or shared waits for your separate confirmation.</p></div>
      <div className="flex flex-wrap gap-2">
        <button onClick={()=>void runAction('get_my_current_support')} className="rounded-lg border px-3 py-2 text-sm font-semibold">Check my support</button>
        <button onClick={()=>void runAction('get_my_upcoming_appointments')} className="rounded-lg border px-3 py-2 text-sm font-semibold">Check appointments</button>
        <button onClick={()=>void openDestination('appointments')} className="rounded-lg border px-3 py-2 text-sm font-semibold">Open appointments</button>
        <button onClick={()=>void openDestination('support')} className="rounded-lg border px-3 py-2 text-sm font-semibold">Open support</button>
        <button onClick={()=>void openDestination('checkins')} className="rounded-lg border px-3 py-2 text-sm font-semibold">Open check-ins</button>
        {availability?.role_type==='workplace_employee'&&<button onClick={()=>void openDestination('workplace_space')} className="rounded-lg border px-3 py-2 text-sm font-semibold">Open workplace space</button>}
      </div>
      {supportInfo&&<div className="rounded-xl bg-slate-50 p-4 text-sm"><p className="font-semibold">Your support: {supportInfo.state==='active'?'active request':supportInfo.state==='connected'?'assigned counsellor available':'no active support relationship'}</p>{supportInfo.provider_name&&<p className="mt-1">{supportInfo.provider_name}{supportInfo.relationship?` · ${supportInfo.relationship.replaceAll('_',' ')}`:''}</p>}{(supportInfo.cases||[]).map(item=><p key={item.case_id} className="mt-1">Request {item.status.replaceAll('_',' ')} · {new Date(item.created_at).toLocaleDateString()}</p>)}</div>}
      {appointments.length>0&&<div className="space-y-2 rounded-xl bg-slate-50 p-4 text-sm"><p className="font-semibold">Your upcoming appointments</p>{appointments.map(item=><article key={item.id} className="rounded-lg bg-white p-3"><p>{new Date(item.starts_at).toLocaleString()} · {item.provider_name}</p><p className="mt-1 text-slate-600">{item.title||'Support appointment'} · {item.status.toLowerCase().replaceAll('_',' ')}</p></article>)}</div>}
      {appointments.length>0&&<div className="rounded-xl border p-4"><h3 className="font-semibold">Prepare for an appointment</h3><div className="mt-2 flex flex-wrap gap-2"><select aria-label="Choose an appointment" value={prepAppointment} onChange={event=>setPrepAppointment(event.target.value)} className="min-h-10 rounded-lg border px-3"><option value="">Choose an upcoming appointment</option>{appointments.map(item=><option key={item.id} value={item.id}>{new Date(item.starts_at).toLocaleString()} · {item.provider_name}</option>)}</select><button onClick={()=>void prepareAppointment()} disabled={!prepAppointment} className="rounded-lg border px-3 py-2 font-semibold disabled:opacity-50">Start preparation</button></div>{prepPrompts.length>0&&<><ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-600">{prepPrompts.map(prompt=><li key={prompt}>{prompt}</li>)}</ul><textarea aria-label="Private appointment preparation draft" maxLength={2000} value={prepNotes} onChange={event=>setPrepNotes(event.target.value)} className="mt-3 min-h-28 w-full rounded-lg border p-3" placeholder="Write what you would like to remember. This stays on this page until you choose to save it."/><button onClick={savePrepAsNote} disabled={!prepNotes.trim()} className="mt-2 rounded-lg border px-3 py-2 text-sm font-semibold disabled:opacity-50">Review draft as private note</button></>}</div>}
      {availability?.workplace_checkin_available&&<div className="rounded-xl border p-4"><h3 className="font-semibold">Private workplace check-in</h3><p className="mt-1 text-sm text-slate-600">Uses MindGuard’s existing workplace check-in questions. Answers are not saved until you confirm.</p><div className="mt-3 grid gap-3 sm:grid-cols-3">{([['mood','How are you feeling?'],['stress','How manageable does stress feel?'],['support_access','How supported do you feel?']] as const).map(([key,label])=><label key={key} className="text-sm font-medium">{label}<select className="mt-1 block min-h-10 w-full rounded-lg border px-2" value={checkin[key]} onChange={event=>setCheckin(current=>({...current,[key]:Number(event.target.value)}))}>{[1,2,3,4,5].map(value=><option key={value} value={value}>{value} / 5</option>)}</select></label>)}</div><button onClick={()=>void runAction('propose_workplace_checkin',checkin)} className="mt-3 rounded-lg border px-3 py-2 text-sm font-semibold">Review check-in</button></div>}
      <div className="rounded-xl border p-4"><h3 className="font-semibold">Request human support</h3>{availability?.role_type==='workplace_employee'?<><p className="mt-1 text-sm text-slate-600">Choose an eligible provider. Workplace requests use the existing workflow, which requires you to choose whether to share your latest check-in.</p><div className="mt-3 flex flex-wrap gap-2"><button onClick={async()=>{const response=await runAction('get_my_available_providers');if(response?.result==='PROVIDER_UNAVAILABLE')setActionMessage(response.message||'No provider is currently available.')}} className="rounded-lg border px-3 py-2 text-sm font-semibold">Find providers</button><select aria-label="Choose a support provider" value={providerId} onChange={event=>setProviderId(event.target.value)} className="min-h-10 rounded-lg border px-3"><option value="">Choose a provider</option>{providers.map(provider=><option key={provider.id} value={provider.id}>{provider.name}{provider.title?` · ${provider.title}`:''}</option>)}</select></div><label className="mt-3 flex items-start gap-2 text-sm"><input type="checkbox" checked={shareLatestCheckin} onChange={event=>setShareLatestCheckin(event.target.checked)} className="mt-1"/><span>I choose to share my latest workplace check-in with this provider as part of the support request. My employer will not receive it.</span></label><button onClick={()=>void runAction('propose_human_support',{provider_id:providerId,share_latest_checkin:shareLatestCheckin})} disabled={!providerId||!shareLatestCheckin} className="mt-3 rounded-lg bg-teal-700 px-3 py-2 text-sm font-bold text-white disabled:opacity-50">Review support request</button></>:<><p className="mt-1 text-sm text-slate-600">This sends a short request to your already assigned counsellor. It does not include your voice transcript or private note.</p><button onClick={()=>void runAction('propose_human_support')} disabled={!availability?.care_recipient_available} className="mt-3 rounded-lg border px-3 py-2 text-sm font-semibold disabled:opacity-50">Review request to my counsellor</button>{!availability?.care_recipient_available&&<p className="mt-2 text-sm text-slate-600">No assigned counsellor is currently available through this account.</p>}</>}</div>
      <div className="rounded-xl border p-4"><h3 className="font-semibold">Private note</h3><p className="mt-1 text-sm text-slate-600">Draft a concise note or appointment-preparation summary. It remains private unless you separately choose to share it.</p><textarea aria-label="Private note draft" maxLength={2000} value={privateSummary} onChange={event=>setPrivateSummary(event.target.value)} className="mt-3 min-h-24 w-full rounded-lg border p-3" placeholder="What would you like to remember from this session?"/><button onClick={()=>void runAction('propose_private_summary',{summary:privateSummary})} disabled={!privateSummary.trim()} className="mt-2 rounded-lg border px-3 py-2 text-sm font-semibold disabled:opacity-50">Review and save privately</button>{availability?.role_type==='workplace_employee'&&(supportInfo?.cases||[]).some(item=>item.status==='open'||item.status==='active')&&<div className="mt-4 border-t pt-3"><p className="text-sm font-semibold">Share a saved note with an active provider</p><p className="mt-1 text-sm text-slate-600">Only a saved note is shared, after another explicit confirmation.</p><select aria-label="Choose your active support case" value={shareCaseId} onChange={event=>setShareCaseId(event.target.value)} className="mt-2 min-h-10 rounded-lg border px-3"><option value="">Choose an active support case</option>{(supportInfo?.cases||[]).filter(item=>item.status==='open'||item.status==='active').map(item=><option key={item.case_id} value={item.case_id}>{item.status.replaceAll('_',' ')} · {new Date(item.created_at).toLocaleDateString()}</option>)}</select><button onClick={()=>void runAction('propose_summary_share',{case_id:shareCaseId})} disabled={!shareCaseId} className="ml-2 rounded-lg border px-3 py-2 text-sm font-semibold disabled:opacity-50">Review sharing</button></div>}</div>
      {pendingAction&&<div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-4"><p className="font-semibold">{pendingAction.prompt}</p><p className="mt-1 text-sm text-amber-950">{pendingAction.sensitivity==='SHARE_REQUIRED'?'This shares information with an authorized provider.':'Nothing is saved or sent until you confirm.'}</p><div className="mt-3 flex gap-2"><button onClick={()=>void confirmAction(true)} className="rounded-lg bg-teal-700 px-4 py-2 font-bold text-white">{pendingAction.action==='propose_human_support'&&pendingAction.sensitivity==='SHARE_REQUIRED'?(pendingAction.stage==='final_confirmation'?'Confirm request and sharing':'Allow sharing & continue'):pendingAction.sensitivity==='SHARE_REQUIRED'?'Confirm sharing':'Confirm'}</button><button onClick={()=>void confirmAction(false)} className="rounded-lg border border-slate-400 px-4 py-2 font-semibold">Cancel</button></div></div>}
      {actionMessage&&<p role="status" aria-live="polite" className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{actionMessage}</p>}
    </section>}
    {textMode&&<section className="rounded-2xl border border-teal-100 bg-white p-5 shadow-sm"><h2 className="font-bold">Text based grounding · no microphone</h2><p className="mt-2 text-sm text-slate-600">Move through one prompt at a time. You can pause or stop whenever you need.</p><div className="mt-4 rounded-xl bg-teal-50 p-5 text-lg text-teal-950" aria-live="polite">{textPrompts[textStep]}</div><div className="mt-4 flex gap-3"><button onClick={()=>setTextStep(step=>Math.min(step+1,textPrompts.length-1))} disabled={textStep===textPrompts.length-1} className="rounded-xl bg-teal-700 px-4 py-2 font-bold text-white disabled:opacity-50">Next prompt</button><button onClick={()=>{setTextStep(0);setTextMode(false)}} className="rounded-xl border px-4 py-2 font-semibold">Close text exercise</button></div></section>}
    <button onClick={()=>setTextMode(mode=>!mode)} className="text-sm font-semibold text-teal-800 underline">{textMode?'Hide text alternative':'Use the text based grounding alternative'}</button>
    {careAlerts.length>0&&<section className="rounded-2xl border border-rose-200 bg-white p-5"><h2 className="font-bold text-rose-900">Care alerts assigned to you</h2><p className="mt-1 text-sm text-slate-600">These alerts contain no voice recording or transcript. Contact the person through your approved care workflow.</p><div className="mt-3 space-y-3">{careAlerts.map(alert=><article key={alert.id} className="rounded-xl bg-rose-50 p-4"><div className="flex flex-wrap justify-between gap-3"><p className="font-semibold text-rose-950">Urgent follow-up for {alert.subject_name}</p><time className="text-xs text-slate-500">{new Date(alert.created_at).toLocaleString()}</time></div><p className="mt-1 text-sm text-rose-900">Delivery: {alert.alert_delivery_status||'unknown'}</p>{alert.alert_delivery_status!=='acknowledged'&&<button onClick={()=>void acknowledge(alert.id)} className="mt-3 rounded-lg bg-rose-800 px-3 py-2 text-sm font-bold text-white">Acknowledge alert</button>}</article>)}</div></section>}
    {history.length>0&&<section className="rounded-2xl border bg-white p-5"><h2 className="font-bold">Your recent private notes</h2><div className="mt-3 space-y-3">{history.map(item=><article key={item.id} className="rounded-xl bg-slate-50 p-4"><div className="flex justify-between gap-3"><p className="font-semibold">{item.exercise?.replaceAll('_',' ')||'Support session'}</p><time className="text-xs text-slate-500">{new Date(item.created_at).toLocaleString()}</time></div>{item.summary&&<p className="mt-2 text-sm text-slate-600">{item.summary}</p>}{(item.safety_outcome==='potential_immediate_danger'||item.safety_outcome==='user_requested_help')&&<p className="mt-2 text-xs font-bold text-rose-700">Human follow-up was requested or a safety concern was detected · alert {item.alert_delivery_status||'not available'}</p>}</article>)}</div></section>}
  </main>
}

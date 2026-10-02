import { useEffect, useRef, useState } from 'react'
import api from '../api/client'
import { getToken } from '../lib/tokenStorage'
import { useUiStore, type PageKey } from '../store/uiStore'

type Availability={enabled:boolean;review_gate_ready:boolean;production_review_complete:boolean;non_production_testing:boolean;provider:'openai'|'deepgram'|null;configuration_ready:boolean;configuration_blockers:string[];care_recipient_available:boolean;care_recipient_type:string;role_type:string;workplace_checkin_available:boolean;is_minor:boolean;language:string;stores_audio:boolean;stores_transcripts:boolean;server_side_controls_ready:boolean;summary_retention_days:number}
type Session={id:string;exercise?:string;summary?:string;safety_outcome:string;alert_delivery_status?:string;created_at:string}
type CareAlert={id:string;subject_user_id:string;subject_name:string;status:string;safety_outcome:string;alert_delivery_status?:string;alert_acknowledged_at?:string;created_at:string;updated_at:string}
type ConversationPhase='listening'|'thinking'|'speaking'|'paused'
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
  const [state,setState]=useState<'idle'|'connecting'|'connected'|'reconnecting'|'ending'|'ended'|'error'>('idle')
  const [phase,setPhase]=useState<ConversationPhase>('listening')
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
  const [endingAfterReview,setEndingAfterReview]=useState(false)
  const setPage=useUiStore(s=>s.setPage)
  const pcRef=useRef<RTCPeerConnection|null>(null)
  const dcRef=useRef<RTCDataChannel|null>(null)
  const voiceSocketRef=useRef<WebSocket|null>(null)
  const streamRef=useRef<MediaStream|null>(null)
  const audioContextRef=useRef<AudioContext|null>(null)
  const audioProcessorRef=useRef<ScriptProcessorNode|null>(null)
  const playbackTimeRef=useRef(0)
  const playbackSourcesRef=useRef(new Set<AudioBufferSourceNode>())
  const sessionRef=useRef<string>('')
  const audioRef=useRef<HTMLAudioElement|null>(null)
  const statusTimerRef=useRef<number|null>(null)
  const lastNavigationEventRef=useRef('')
  const endAfterReviewRef=useRef(false)
  const intentionalEndRef=useRef(false)
  const helpPanelRef=useRef<HTMLDetailsElement|null>(null)
  const supportRequestRef=useRef<HTMLDivElement|null>(null)
  const providerSelectRef=useRef<HTMLSelectElement|null>(null)

  const refresh=async()=>{const [a,h]=await Promise.all([api.get('/v1/voice/availability'),api.get('/v1/voice/sessions')]);setAvailability(a.data);setHistory(h.data);try{setCareAlerts((await api.get('/v1/voice/alerts')).data)}catch{setCareAlerts([])}}
  useEffect(()=>{void Promise.resolve().then(refresh).catch(()=>setMessage('Voice support status is temporarily unavailable.'));return()=>{const id=sessionRef.current;if(id)void api.post(`/v1/voice/sessions/${id}/close`,{}).catch(()=>{}).finally(()=>voiceSocketRef.current?.close());else voiceSocketRef.current?.close();if(statusTimerRef.current!==null)window.clearInterval(statusTimerRef.current);streamRef.current?.getTracks().forEach(t=>t.stop());audioProcessorRef.current?.disconnect();void audioContextRef.current?.close();pcRef.current?.close()}},[])

  const stopDeepgramAudio=()=>{audioProcessorRef.current?.disconnect();audioProcessorRef.current=null;for(const source of playbackSourcesRef.current){try{source.stop()}catch{/* The node may already have ended. */}}playbackSourcesRef.current.clear();void audioContextRef.current?.close();audioContextRef.current=null;voiceSocketRef.current?.close();voiceSocketRef.current=null;playbackTimeRef.current=0}
  const connectDeepgram=async(sessionId:string,stream:MediaStream)=>{
    const token=getToken()
    if(!token)throw new Error('Sign in again before starting a voice conversation.')
    const base=import.meta.env.VITE_API_BASE_URL||(import.meta.env.DEV?'http://127.0.0.1:8000/api':`${window.location.origin}/api`)
    const socketUrl=`${base.replace(/^http/,'ws').replace(/\/api\/?$/,'')}/api/v1/voice/sessions/${sessionId}/stream`
    const socket=new WebSocket(socketUrl);socket.binaryType='arraybuffer';voiceSocketRef.current=socket
    let providerReady=false
    const context=new AudioContext();audioContextRef.current=context;await context.resume()
    const source=context.createMediaStreamSource(stream);const processor=context.createScriptProcessor(4096,1,1);audioProcessorRef.current=processor
    const silentGain=context.createGain();silentGain.gain.value=0
    processor.onaudioprocess=event=>{
      if(!providerReady||socket.readyState!==WebSocket.OPEN||stream.getAudioTracks().every(track=>!track.enabled))return
      const input=event.inputBuffer.getChannelData(0);const ratio=context.sampleRate/24000;const outputLength=Math.max(1,Math.floor(input.length/ratio));const pcm=new Int16Array(outputLength)
      for(let index=0;index<outputLength;index++){const position=index*ratio;const left=Math.floor(position);const fraction=position-left;const sample=(input[left]||0)*(1-fraction)+(input[Math.min(left+1,input.length-1)]||0)*fraction;pcm[index]=Math.max(-1,Math.min(1,sample))*32767}
      socket.send(pcm.buffer)
    }
    source.connect(processor);processor.connect(silentGain);silentGain.connect(context.destination)
    await new Promise<void>((resolve,reject)=>{
      const timeout=window.setTimeout(()=>reject(new Error('The secure voice connection could not be established.')),12000)
      socket.onopen=()=>socket.send(JSON.stringify({type:'auth',token}))
      socket.onerror=()=>{window.clearTimeout(timeout);reject(new Error('The secure voice connection could not be established.'))}
      socket.onclose=event=>{window.clearTimeout(timeout);if(!intentionalEndRef.current&&event.code!==1000){setState('error');setMessage('The conversation ended unexpectedly. Your audio and live captions were not stored by MindGuard.')}reject(new Error('The secure voice connection closed.'))}
      socket.onmessage=event=>{
        if(typeof event.data!=='string'){
          const samples=new Int16Array(event.data as ArrayBuffer);const buffer=context.createBuffer(1,samples.length,24000);const channel=buffer.getChannelData(0)
          for(let i=0;i<samples.length;i++)channel[i]=samples[i]/32768
          const player=context.createBufferSource();player.buffer=buffer;player.connect(context.destination);playbackSourcesRef.current.add(player);player.addEventListener('ended',()=>playbackSourcesRef.current.delete(player),{once:true});const playAt=Math.max(context.currentTime+0.02,playbackTimeRef.current);player.start(playAt);playbackTimeRef.current=playAt+buffer.duration;return
        }
        try{const packet=JSON.parse(event.data) as {type:string;role?:string;content?:string;phase?:ConversationPhase}
          if(packet.type==='MindGuardReady'){providerReady=true;window.clearTimeout(timeout);setState('connected');setPhase('listening');setMessage('');resolve()}
          else if(packet.type==='ConversationText'&&packet.content){setTranscript(items=>[...items,`${packet.role==='assistant'?'MindGuard AI':'You'}: ${packet.content?.slice(0,4000)}`].slice(-8))}
          else if(packet.type==='MindGuardPhase'&&packet.phase)setPhase(packet.phase)
          else if(packet.type==='MindGuardUserStartedSpeaking'){for(const source of playbackSourcesRef.current){try{source.stop()}catch{/* The node may already have ended. */}}playbackSourcesRef.current.clear();playbackTimeRef.current=0;setPhase('listening')}
          else if(packet.type==='MindGuardActionPending')setActionMessage('A MindGuard request is waiting for your confirmation.')
          else if(packet.type==='MindGuardUnavailable'){window.clearTimeout(timeout);reject(new Error('Voice Companion is unavailable right now. Please try again later.'))}
        }catch{/* Ignore malformed transport messages. */}
      }
    })
  }

  const requestHumanHelp=async()=>{
    if(!sessionRef.current)return
    try{const {data}=await api.post(`/v1/voice/sessions/${sessionRef.current}/request-help`);setUrgent(true);setMessage(data.message)}catch{setUrgent(true);setMessage('Call Kenya emergency services on 999, 112, or 911, contact a trusted person, or go to the nearest health facility now.')}
  }
  const requestHumanSupport=async()=>{
    if(!sessionRef.current||state!=='connected'||pendingAction)return
    if(availability?.role_type==='workplace_employee'){
      helpPanelRef.current?.setAttribute('open','')
      supportRequestRef.current?.scrollIntoView({behavior:'smooth',block:'center'})
      const response=await runAction('get_my_available_providers')
      if(response?.result==='SUCCESS')window.requestAnimationFrame(()=>providerSelectRef.current?.focus())
      else setActionMessage(response?.message||'No provider is currently available.')
      return
    }
    await runAction('propose_human_support')
  }
  const start=async()=>{
    if(!accepted)return
    intentionalEndRef.current=false
    setState('connecting');setMessage('Requesting microphone access…');setUrgent(false)
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:true});streamRef.current=stream
      const {data}=await api.post('/v1/voice/sessions',{accepted_notice:true})
      sessionRef.current=data.session_id
      statusTimerRef.current=window.setInterval(async()=>{
        const currentId=sessionRef.current
        if(!currentId)return
        try{
          const {data:sessionState}=await api.get(`/v1/voice/sessions/${currentId}/state`)
          if(sessionState.pending_action?.id){const pending=sessionState.pending_action;const action=pending.action;const prompt=pending.confirmation_prompt||confirmationPrompt(action,availability?.role_type);const stage=action==='propose_human_support'&&prompt.toLowerCase().includes('this is the final confirmation')?'final_confirmation':undefined;setPendingAction(current=>({id:pending.id,action,sensitivity:pending.sensitivity||confirmationSensitivity(action,availability?.role_type),prompt,stage:stage||(current&&current.id===pending.id?current.stage:undefined)}));setActionMessage('A MindGuard request is waiting for your confirmation.')}else setPendingAction(null)
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
            setState(sessionState.status==='failed'?'error':'ended')
            setMessage(sessionState.status==='failed'?'The conversation ended unexpectedly. Your audio and live captions were not stored by MindGuard. You can start again when ready.':sessionState.status==='expired'?'The conversation reached its time limit and has ended.':'The conversation has ended.')
          }
        }catch{setMessage('Connection status is temporarily unavailable. Ending locally remains available.')}
      },2000)
      if(data.provider==='deepgram'){
        await connectDeepgram(data.session_id,stream)
        return
      }
      const pc=new RTCPeerConnection();pcRef.current=pc
      const audio=document.createElement('audio');audio.autoplay=true;audioRef.current=audio
      pc.ontrack=e=>{audio.srcObject=e.streams[0]}
      pc.onconnectionstatechange=()=>{if(pc.connectionState==='disconnected'){setState('reconnecting');setMessage('Trying to reconnect. You can end the conversation at any time.')}else if(pc.connectionState==='connected'){setState('connected');setMessage('');setPhase(muted?'paused':'listening')}else if((pc.connectionState==='failed'||pc.connectionState==='closed')&&!intentionalEndRef.current){setMessage('The conversation ended unexpectedly. Your audio and live captions were not stored by MindGuard.');if(sessionRef.current)void api.post(`/v1/voice/sessions/${sessionRef.current}/close`,{}).catch(()=>{});setState('error')}}
      stream.getTracks().forEach(track=>pc.addTrack(track,stream))
      const dc=pc.createDataChannel('oai-events');dcRef.current=dc
      dc.addEventListener('open',()=>{setState('connected');setPhase('listening');setMessage('')})
      dc.addEventListener('message',event=>{
        try{const payload=JSON.parse(event.data);if(payload.type==='input_audio_buffer.speech_started'){setPhase('listening')}else if(payload.type==='response.created'){setPhase('thinking')}else if(payload.type==='response.output_audio.delta'||payload.type==='response.output_audio_transcript.delta'){setPhase('speaking')}else if(payload.type==='response.done'){setPhase(muted?'paused':'listening');const calls=payload.response?.output?.some((item:{type?:string})=>item.type==='function_call');setActionMessage(calls?'Checking your MindGuard request…':'')}else if(payload.type==='conversation.item.input_audio_transcription.completed'&&payload.transcript){setTranscript(items=>[...items,`You: ${String(payload.transcript).slice(0,4000)}`].slice(-8))}else if((payload.type==='response.output_audio_transcript.done'||payload.type==='response.output_audio_transcript.delta')&&payload.transcript){setTranscript(items=>[...items,`MindGuard AI: ${String(payload.transcript).slice(0,4000)}`].slice(-8))}}catch{/* ignore malformed provider events */}
      })
      dc.addEventListener('close',()=>{if(!intentionalEndRef.current){setState('error');setMessage('The conversation ended unexpectedly. Your audio and live captions were not stored by MindGuard.')}})
      const offer=await pc.createOffer();await pc.setLocalDescription(offer)
      const {data:answer}=await api.post(`/v1/voice/sessions/${data.session_id}/connect`,{sdp:offer.sdp})
      await pc.setRemoteDescription({type:'answer',sdp:answer.answer_sdp})
    }catch(e){const id=sessionRef.current;if(id){await api.post(`/v1/voice/sessions/${id}/close`,{}).catch(()=>{});sessionRef.current=''}if(statusTimerRef.current!==null)window.clearInterval(statusTimerRef.current);statusTimerRef.current=null;streamRef.current?.getTracks().forEach(t=>t.stop());stopDeepgramAudio();pcRef.current?.close();pcRef.current=null;dcRef.current=null;streamRef.current=null;setState('error');setMessage(e instanceof DOMException&&e.name==='NotAllowedError'?'Microphone permission was denied. You can change this in your browser settings and try again.':e instanceof Error&&e.message!=='The secure voice connection closed.'?e.message:'Voice Companion is unavailable right now. Please try again later.')}
  }
  const finishEnd=async(completion='Conversation ended. Your audio and live captions were not stored by MindGuard.')=>{
    const id=sessionRef.current
    intentionalEndRef.current=true
    setState('ending')
    if(statusTimerRef.current!==null)window.clearInterval(statusTimerRef.current)
    statusTimerRef.current=null
    if(id)try{await api.post(`/v1/voice/sessions/${id}/close`,{})}catch{/* Session can still close locally. */}
    stopDeepgramAudio()
    streamRef.current?.getTracks().forEach(track=>track.stop())
    pcRef.current?.close();dcRef.current=null;pcRef.current=null;streamRef.current=null;sessionRef.current=''
    setPendingAction(null);setTranscript([]);setPrivateSummary('');setPrepNotes('');setPrepPrompts([])
    endAfterReviewRef.current=false;setEndingAfterReview(false);setState('ended');setPhase('listening');setMessage(completion)
    void refresh().catch(()=>{})
  }
  const end=async()=>{
    if(!sessionRef.current)return
    const existingNoteConfirmation=pendingAction?.action==='propose_private_summary'
    const draft=pendingAction?'':(privateSummary.trim()||prepNotes.trim())
    if(existingNoteConfirmation||draft){
      endAfterReviewRef.current=true;setEndingAfterReview(true);setState('ending')
      if(dcRef.current?.readyState==='open')dcRef.current.send(JSON.stringify({type:'response.cancel'}))
      streamRef.current?.getAudioTracks().forEach(track=>{track.enabled=false})
      setMessage('Conversation complete. Review the private note below before leaving.')
      if(!existingNoteConfirmation){
        setPrivateSummary(draft);setPrepNotes('')
        const result=await runAction('propose_private_summary',{summary:draft})
        if(result?.result!=='CONFIRMATION_REQUIRED')await finishEnd('Conversation ended. The draft was not saved.')
      }
      return
    }
    await finishEnd()
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
    try{const {data}=await api.post<VoiceActionResponse>(`/v1/voice/sessions/${sessionRef.current}/actions/${pendingAction.id}/confirm`,{confirmed});if(data.result==='CONFIRMATION_REQUIRED'&&data.pending_action_id){setPendingAction({id:data.pending_action_id,action:data.action||pendingAction.action,sensitivity:data.sensitivity||pendingAction.sensitivity,prompt:data.confirmation_prompt||pendingAction.prompt,stage:data.stage});setActionMessage('Check-in sharing consent recorded. Please review the final support request.');return}setPendingAction(null);if(endAfterReviewRef.current){await finishEnd(data.result==='SUCCESS'&&confirmed?'Your private note was saved. The conversation has ended.':confirmed?'The conversation ended. The note was not saved.':'The draft was discarded. The conversation has ended.');return}setActionMessage(data.message|| (data.result==='SUCCESS'?'Done.':'I could not complete that action.'));if(data.result==='SUCCESS'&&pendingAction.action==='propose_private_summary'){setPrivateSummary('');await refresh()}if(data.result==='SUCCESS'&&pendingAction.action==='propose_human_support')await runAction('get_my_current_support');if(data.result!=='SUCCESS')setActionMessage(data.message||'I could not complete that action. Your conversation can continue.')}
    catch{if(endAfterReviewRef.current){await finishEnd('Conversation ended. The note was not saved.')}else{setPendingAction(null);setActionMessage('I could not confirm that action. Nothing should be assumed to have changed.')}}
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
  const reviewAccess=Boolean(availability&&(availability.production_review_complete||availability.non_production_testing))
  const available=Boolean(availability?.enabled&&reviewAccess&&availability.configuration_ready&&availability.server_side_controls_ready)
  const active=state==='connected'||state==='reconnecting'||state==='ending'
  const assistantStatus=state==='connected'?(muted?'Paused':phase==='thinking'?'Thinking':phase==='speaking'?'Speaking':'Listening'):state==='reconnecting'?'Reconnecting':state==='ending'?'Ended':state==='ended'?'Ended':state==='connecting'?'Connecting':availability===null?'Checking':!available||state==='error'?'Unavailable':'Ready'
  const stateTone=state==='connected'?'border-teal-200 bg-teal-50 text-teal-900':state==='reconnecting'?'border-amber-200 bg-amber-50 text-amber-900':state==='error'?'border-slate-200 bg-slate-50 text-slate-700':'border-slate-200 bg-slate-50 text-slate-700'
  const focus='focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-700 focus-visible:ring-offset-2'
  const button='min-h-11 rounded-xl px-4 py-2 font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50'
  const textPrompts=['Pause and feel both feet supported by the floor.','Name five things you can see around you.','Notice four things you can feel, such as your clothing or the chair.','Listen for three sounds, near or far.','Take one comfortable breath and choose a person or small next step that could support you.']

  return <main className="mx-auto max-w-4xl space-y-6 px-4 py-6 text-slate-900 sm:px-6 md:py-8">
    <header className="max-w-3xl">
      <p className="text-sm font-semibold text-teal-800">MindGuard wellbeing support</p>
      <h1 className="mt-1 text-3xl font-bold tracking-tight sm:text-4xl">MindGuard Voice Companion</h1>
      <h2 className="mt-5 text-xl font-semibold">Talk about what’s on your mind</h2>
      <p className="mt-2 text-base leading-7 text-slate-700">You can talk naturally. I can help you reflect, guide a private check-in, prepare for an appointment, or help you connect with human support.</p>
    </header>

    {availability===null&&<section className="rounded-2xl border border-slate-200 bg-white p-4 text-sm text-slate-600" role="status" aria-live="polite">Checking Voice Companion availability…</section>}
    {availability!==null&&!available&&<section className="rounded-2xl border border-slate-200 bg-slate-50 p-5" role="status"><h2 className="font-semibold">Voice Companion is unavailable right now</h2><p className="mt-1 text-sm text-slate-600">Please try again later. You can still explore the other ways MindGuard can help below.</p></section>}
    {availability?.non_production_testing&&<p className="text-xs text-amber-800" role="note">Voice testing mode — not approved for production use</p>}

    <section aria-labelledby="conversation-title" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 id="conversation-title" className="text-lg font-bold">Your conversation</h2>
          <p className="mt-1 text-sm text-slate-600">A private, live conversation. You can pause or end it at any time.</p>
        </div>
        <span role="status" aria-live="polite" aria-atomic="true" className={`inline-flex min-h-10 items-center gap-2 rounded-full border px-4 text-sm font-semibold ${stateTone}`}>
          <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${state==='connected'?'bg-teal-700':state==='reconnecting'?'bg-amber-600':'bg-slate-400'}`}/>{assistantStatus}
        </span>
      </div>

      {!active&&state!=='connecting'&&state!=='ended'&&available&&<div className="mt-6 rounded-xl bg-slate-50 p-4 sm:p-5">
        <label className="flex cursor-pointer items-start gap-3 text-sm leading-6 text-slate-700">
          <input type="checkbox" checked={accepted} onChange={event=>setAccepted(event.target.checked)} className={`mt-1 h-4 w-4 accent-teal-700 ${focus}`}/>
          <span>I understand this is an AI support conversation. My live audio and captions are not stored by MindGuard. I choose whether to save a note or check-in, and provider sharing always needs separate consent.</span>
        </label>
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
          <button disabled={!available||!accepted} onClick={()=>void start()} className={`${button} ${focus} w-full bg-emerald-500 px-6 text-slate-950 hover:bg-emerald-600 sm:w-auto`}>{state==='error'?'Try again':'Start conversation'}</button>
          <span className="text-sm text-slate-500">You’ll need microphone access to begin.</span>
        </div>
      </div>}

      {state==='connecting'&&<div role="status" aria-live="polite" className="mt-6 rounded-xl bg-slate-50 p-5 text-sm text-slate-700">Connecting securely. Please allow microphone access if your browser asks.</div>}
      {state==='error'&&message&&<p role="status" aria-live="polite" className="mt-5 rounded-xl bg-slate-50 p-4 text-sm text-slate-700">{message}</p>}
      {state==='ended'&&<div className="mt-6 rounded-xl bg-slate-50 p-5" role="status" aria-live="polite"><h3 className="font-semibold">Conversation complete</h3><p className="mt-1 text-sm leading-6 text-slate-600">{message||'Thank you for taking a moment for yourself. Your audio and live captions were not stored by MindGuard.'}</p><button disabled={!available||!accepted} onClick={()=>void start()} className={`${button} ${focus} mt-4 bg-emerald-500 text-slate-950 hover:bg-emerald-600`}>Start another conversation</button></div>}

      {active&&<div className="mt-6 space-y-5">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div><p className="font-semibold" aria-hidden="true">{assistantStatus}</p><p className="mt-1 text-sm text-slate-600">{state==='ending'?'Your microphone is paused while you review the note.':state==='reconnecting'?'Trying to restore the connection. You may end the conversation.':muted?'Your microphone is paused. Resume whenever you are ready.':'Speak naturally whenever you are ready.'}</p></div>
            <div className="flex flex-wrap gap-2">
              {state!=='ending'&&<button onClick={toggleMute} disabled={state==='reconnecting'} aria-label={muted?'Resume microphone':'Pause microphone'} className={`${button} ${focus} border border-slate-300 bg-white hover:bg-slate-100`}>{muted?'Resume microphone':'Pause microphone'}</button>}
              {(phase==='speaking'||phase==='thinking')&&state==='connected'&&!muted&&<button onClick={interrupt} className={`${button} ${focus} border border-slate-300 bg-white hover:bg-slate-100`}>Interrupt</button>}
              <button onClick={()=>void requestHumanSupport()} disabled={state!=='connected'||Boolean(pendingAction)} className={`${button} ${focus} border border-slate-300 bg-white text-sm hover:bg-slate-100`}>Request human support</button>
              <button onClick={()=>void end()} disabled={state==='ending'} className={`${button} ${focus} border border-slate-300 bg-white text-slate-800 hover:bg-slate-100`}>{endingAfterReview?'Reviewing note…':'End conversation'}</button>
            </div>
          </div>
          <div aria-label="Temporary live captions" aria-live="polite" aria-relevant="additions" className="mt-5 max-h-48 min-h-16 overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 text-sm leading-6 text-slate-700">
            {transcript.length?transcript.map((line,index)=><p key={`${index}-${line}`} className="mb-2 last:mb-0">{line}</p>):<p className="text-slate-500">Temporary captions will appear here while you talk. They disappear when the conversation ends.</p>}
          </div>
        </div>

        {pendingAction&&<section aria-labelledby="voice-confirmation-title" aria-live="polite" className="rounded-xl border border-teal-200 bg-teal-50 p-4 sm:p-5">
          <h3 id="voice-confirmation-title" className="font-semibold">{endingAfterReview?'Your private note':'Please review this request'}</h3>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-800">{pendingAction.prompt}</p>
          <p className="mt-2 text-sm text-slate-600">{pendingAction.sensitivity==='SHARE_REQUIRED'?'Nothing is shared until you give the requested consent and final confirmation.':'Nothing is saved or sent until you confirm.'}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button onClick={()=>void confirmAction(true)} className={`${button} ${focus} bg-emerald-500 text-slate-950 hover:bg-emerald-600`}>{endingAfterReview?'Save privately':pendingAction.action==='propose_private_summary'?'Save privately':pendingAction.action==='propose_workplace_checkin'?'Save check-in':pendingAction.action==='propose_summary_share'?'Share note':pendingAction.action==='propose_human_support'&&pendingAction.stage==='final_confirmation'?'Confirm request and sharing':pendingAction.action==='propose_human_support'&&pendingAction.sensitivity==='SHARE_REQUIRED'?'Allow sharing and continue':'Confirm request'}</button>
            <button onClick={()=>void confirmAction(false)} className={`${button} ${focus} border border-slate-300 bg-white hover:bg-slate-100`}>{endingAfterReview?'Discard note':pendingAction.action==='propose_private_summary'?'Discard':'Cancel'}</button>
          </div>
        </section>}

        {state==='ending'&&endingAfterReview&&<p role="status" aria-live="polite" className="text-sm text-slate-600">Choose Save privately or Discard note to finish.</p>}
        {message&&<p role="status" aria-live="polite" className={`rounded-lg p-3 text-sm ${urgent?'bg-amber-50 text-amber-950':'bg-slate-50 text-slate-700'}`}>{message}</p>}
        {actionMessage&&<p role="status" aria-live="polite" className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{actionMessage}</p>}
      </div>}
    </section>

    <div className="grid gap-4 sm:grid-cols-2">
      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold">Need urgent help?</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600">If you or someone else is in immediate danger, use these reviewed options.</p>
        <details className="mt-3">
          <summary className={`${focus} cursor-pointer rounded-md py-2 text-sm font-semibold text-teal-800 underline`}>See urgent options</summary>
          <div className="mt-3 flex flex-wrap gap-2">
            <a href="tel:999" className={`${button} ${focus} inline-flex items-center border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Call 999</a>
            <a href="tel:112" className={`${button} ${focus} inline-flex items-center border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Call 112</a>
            <a href="tel:911" className={`${button} ${focus} inline-flex items-center border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Call 911</a>
            {availability?.is_minor&&<a href="tel:116" className={`${button} ${focus} inline-flex items-center border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Child Helpline 116</a>}
          </div>
          <p className="mt-3 text-sm text-slate-600">You can also contact someone you trust or go to the nearest health facility.</p>
          <button onClick={()=>void requestHumanHelp()} disabled={!active||state==='ending'} className={`${button} ${focus} mt-3 border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Ask for a human follow-up</button>
        </details>
      </section>
      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold">Your privacy, in brief</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">MindGuard does not store raw audio or live transcripts. Notes and check-ins are saved only after you confirm. Sharing with a provider requires separate consent. Workplace employers do not receive individual voice conversation information.</p>
        <details className="mt-3">
          <summary className={`${focus} cursor-pointer rounded-md py-2 text-sm font-semibold text-teal-800 underline`}>How voice privacy works</summary>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-slate-600">
            <li>Live audio is streamed to the configured voice provider so the conversation can take place. Short transcript excerpts may be processed by MindGuard’s server-side safety monitor; MindGuard does not keep the raw audio or live transcript.</li>
            <li>A private note is stored only after you approve the draft. Saved notes are encrypted and retained for up to {availability?.summary_retention_days||30} days.</li>
            <li>A provider receives information only through an authorized support workflow and only after the consent and confirmation shown to you.</li>
            <li>Your authorized care team may see a follow-up alert only when the existing safety process requires one or you request human support. Alerts do not contain your audio or live transcript.</li>
          </ul>
        </details>
      </section>
    </div>

    <details ref={helpPanelRef} className="rounded-2xl border border-slate-200 bg-white p-5">
      <summary className={`${focus} cursor-pointer text-lg font-semibold`}>Things I can help with</summary>
      <p className="mt-2 text-sm leading-6 text-slate-600">You can ask for these naturally during a conversation, or use the controls below. Saving or sharing always uses the confirmation shown in the conversation.</p>
      {!active&&<p className="mt-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">Start a conversation to use your personal MindGuard actions.</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button disabled={!active||state==='ending'} onClick={()=>void runAction('get_my_current_support')} className={`${button} ${focus} border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Check my support</button>
        <button disabled={!active||state==='ending'} onClick={()=>void runAction('get_my_upcoming_appointments')} className={`${button} ${focus} border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Check appointments</button>
        <button disabled={!active||state==='ending'} onClick={()=>void openDestination('appointments')} className={`${button} ${focus} border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Open appointments</button>
        <button disabled={!active||state==='ending'} onClick={()=>void openDestination('support')} className={`${button} ${focus} border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Open support</button>
        <button disabled={!active||state==='ending'} onClick={()=>void openDestination('checkins')} className={`${button} ${focus} border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Open check-ins</button>
        {availability?.role_type==='workplace_employee'&&<button disabled={!active||state==='ending'} onClick={()=>void openDestination('workplace_space')} className={`${button} ${focus} border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Open workplace space</button>}
      </div>
      {supportInfo&&<div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm"><p className="font-semibold">Your support: {supportInfo.state==='active'?'active request':supportInfo.state==='connected'?'assigned counsellor available':'no active support relationship'}</p>{supportInfo.provider_name&&<p className="mt-1">{supportInfo.provider_name}{supportInfo.relationship?` · ${supportInfo.relationship.replaceAll('_',' ')}`:''}</p>}{(supportInfo.cases||[]).map(item=><p key={item.case_id} className="mt-1">Request {item.status.replaceAll('_',' ')} · {new Date(item.created_at).toLocaleDateString()}</p>)}</div>}
      {appointments.length>0&&<div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm"><p className="font-semibold">Upcoming appointments</p><ul className="mt-2 space-y-2">{appointments.map(item=><li key={item.id}>{new Date(item.starts_at).toLocaleString()} · {item.provider_name}{item.title?` · ${item.title}`:''}</li>)}</ul></div>}
      {appointments.length>0&&<div className="mt-4 rounded-xl border border-slate-200 p-4"><h3 className="font-semibold">Prepare for an appointment</h3><div className="mt-2 flex flex-col gap-2 sm:flex-row"><select aria-label="Choose an appointment" value={prepAppointment} onChange={event=>setPrepAppointment(event.target.value)} className={`${focus} min-h-11 rounded-lg border border-slate-300 px-3`}><option value="">Choose an upcoming appointment</option>{appointments.map(item=><option key={item.id} value={item.id}>{new Date(item.starts_at).toLocaleString()} · {item.provider_name}</option>)}</select><button disabled={!prepAppointment||!active||state==='ending'} onClick={()=>void prepareAppointment()} className={`${button} ${focus} border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Start preparation</button></div>{prepPrompts.length>0&&<><ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-600">{prepPrompts.map(prompt=><li key={prompt}>{prompt}</li>)}</ul><label className="mt-3 block text-sm font-medium">Private preparation draft<textarea aria-label="Private appointment preparation draft" maxLength={2000} value={prepNotes} onChange={event=>setPrepNotes(event.target.value)} className={`${focus} mt-2 min-h-24 w-full rounded-lg border border-slate-300 p-3`} placeholder="Write what you would like to remember."/></label><button disabled={!prepNotes.trim()||!active||state==='ending'} onClick={savePrepAsNote} className={`${button} ${focus} mt-2 border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Use as private note</button></>}</div>}
      {availability?.workplace_checkin_available&&<div className="mt-4 rounded-xl border border-slate-200 p-4"><h3 className="font-semibold">Private workplace check-in</h3><p className="mt-1 text-sm text-slate-600">Uses the existing check-in questions. Nothing is saved until you confirm.</p><div className="mt-3 grid gap-3 sm:grid-cols-3">{([['mood','How are you feeling?'],['stress','How manageable does stress feel?'],['support_access','How supported do you feel?']] as const).map(([key,label])=><label key={key} className="text-sm font-medium">{label}<select disabled={!active||state==='ending'} className={`${focus} mt-1 block min-h-11 w-full rounded-lg border border-slate-300 px-2`} value={checkin[key]} onChange={event=>setCheckin(current=>({...current,[key]:Number(event.target.value)}))}>{[1,2,3,4,5].map(value=><option key={value} value={value}>{value} / 5</option>)}</select></label>)}</div><button disabled={!active||state==='ending'} onClick={()=>void runAction('propose_workplace_checkin',checkin)} className={`${button} ${focus} mt-3 border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Review check-in</button></div>}
      <div ref={supportRequestRef} className="mt-4 rounded-xl border border-slate-200 p-4"><h3 className="font-semibold">Request human support</h3>{availability?.role_type==='workplace_employee'?<><p className="mt-1 text-sm text-slate-600">Choose an eligible provider. The flow asks separately whether you want to share your latest check-in.</p><div className="mt-3 flex flex-col gap-2 sm:flex-row"><button disabled={!active||state==='ending'} onClick={async()=>{const response=await runAction('get_my_available_providers');if(response?.result==='PROVIDER_UNAVAILABLE')setActionMessage(response.message||'No provider is currently available.')}} className={`${button} ${focus} border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Find providers</button><select ref={providerSelectRef} disabled={!active||state==='ending'} aria-label="Choose a support provider" value={providerId} onChange={event=>setProviderId(event.target.value)} className={`${focus} min-h-11 rounded-lg border border-slate-300 px-3`}><option value="">Choose a provider</option>{providers.map(provider=><option key={provider.id} value={provider.id}>{provider.name}{provider.title?` · ${provider.title}`:''}</option>)}</select></div><label className="mt-3 flex items-start gap-2 text-sm"><input type="checkbox" checked={shareLatestCheckin} onChange={event=>setShareLatestCheckin(event.target.checked)} className={`${focus} mt-1 h-4 w-4 accent-teal-700`}/><span>I choose to share my latest workplace check-in with this provider as part of the support request. My employer will not receive it.</span></label><button disabled={!providerId||!shareLatestCheckin||!active||state==='ending'} onClick={()=>void runAction('propose_human_support',{provider_id:providerId,share_latest_checkin:shareLatestCheckin})} className={`${button} ${focus} mt-3 bg-emerald-500 text-sm text-slate-950 hover:bg-emerald-600`}>Review support request</button></>:<><p className="mt-1 text-sm text-slate-600">This sends a short request to your assigned counsellor. It does not include your voice transcript or private note.</p><button disabled={!active||state==='ending'||!availability?.care_recipient_available} onClick={()=>void runAction('propose_human_support')} className={`${button} ${focus} mt-3 border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Review request to my counsellor</button>{!availability?.care_recipient_available&&<p className="mt-2 text-sm text-slate-600">No assigned counsellor is currently available through this account.</p>}</>}</div>
      <div className="mt-4 rounded-xl border border-slate-200 p-4"><h3 className="font-semibold">Private note</h3><p className="mt-1 text-sm text-slate-600">A note stays private unless you separately choose to share it with an authorized provider.</p><label className="mt-3 block text-sm font-medium">Your note<textarea aria-label="Private note draft" maxLength={2000} value={privateSummary} onChange={event=>setPrivateSummary(event.target.value)} className={`${focus} mt-2 min-h-24 w-full rounded-lg border border-slate-300 p-3`} placeholder="What would you like to remember?"/></label><button disabled={!privateSummary.trim()||!active||state==='ending'} onClick={()=>void runAction('propose_private_summary',{summary:privateSummary})} className={`${button} ${focus} mt-2 border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Review note</button>{availability?.role_type==='workplace_employee'&&(supportInfo?.cases||[]).some(item=>item.status==='open'||item.status==='active')&&<div className="mt-4 border-t border-slate-200 pt-3"><p className="text-sm font-semibold">Share a saved note with a provider</p><p className="mt-1 text-sm text-slate-600">Sharing requires a separate confirmation.</p><select disabled={!active||state==='ending'} aria-label="Choose your active support case" value={shareCaseId} onChange={event=>setShareCaseId(event.target.value)} className={`${focus} mt-2 min-h-11 rounded-lg border border-slate-300 px-3`}><option value="">Choose an active support case</option>{(supportInfo?.cases||[]).filter(item=>item.status==='open'||item.status==='active').map(item=><option key={item.case_id} value={item.case_id}>{item.status.replaceAll('_',' ')} · {new Date(item.created_at).toLocaleDateString()}</option>)}</select><button disabled={!shareCaseId||!active||state==='ending'} onClick={()=>void runAction('propose_summary_share',{case_id:shareCaseId})} className={`${button} ${focus} ml-2 mt-2 border border-slate-300 bg-white text-sm hover:bg-slate-50`}>Review sharing</button></div>}</div>
      {textMode&&<div className="mt-4 rounded-xl bg-slate-50 p-4"><h3 className="font-semibold">A short grounding exercise</h3><p className="mt-2 text-base leading-7" aria-live="polite">{textPrompts[textStep]}</p><div className="mt-3 flex flex-wrap gap-2"><button onClick={()=>setTextStep(step=>Math.min(step+1,textPrompts.length-1))} disabled={textStep===textPrompts.length-1} className={`${button} ${focus} bg-teal-700 text-white`}>Next prompt</button><button onClick={()=>{setTextStep(0);setTextMode(false)}} className={`${button} ${focus} border border-slate-300 bg-white`}>Close exercise</button></div></div>}
      <button onClick={()=>setTextMode(mode=>!mode)} className={`${focus} mt-4 text-sm font-semibold text-teal-800 underline`}>{textMode?'Hide grounding exercise':'Try a short grounding exercise'}</button>
    </details>

    {careAlerts.length>0&&<section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="font-semibold">Follow-up alerts assigned to you</h2><p className="mt-1 text-sm text-slate-600">These alerts contain no voice recording or transcript.</p><div className="mt-3 space-y-3">{careAlerts.map(alert=><article key={alert.id} className="rounded-xl bg-slate-50 p-4"><div className="flex flex-wrap justify-between gap-3"><p className="font-semibold">Follow-up for {alert.subject_name}</p><time className="text-xs text-slate-500">{new Date(alert.created_at).toLocaleString()}</time></div><p className="mt-1 text-sm text-slate-600">Status: {alert.alert_delivery_status||'not available'}</p>{alert.alert_delivery_status!=='acknowledged'&&<button onClick={()=>void acknowledge(alert.id)} className={`${button} ${focus} mt-3 border border-slate-300 bg-white text-sm`}>Acknowledge alert</button>}</article>)}</div></section>}
    {history.length>0&&<section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="font-semibold">Your saved private notes</h2><div className="mt-3 space-y-3">{history.map(item=><article key={item.id} className="rounded-xl bg-slate-50 p-4"><div className="flex flex-wrap justify-between gap-2"><p className="font-semibold">Private note</p><time className="text-xs text-slate-500">{new Date(item.created_at).toLocaleString()}</time></div>{item.summary&&<p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{item.summary}</p>}</article>)}</div></section>}
  </main>
}

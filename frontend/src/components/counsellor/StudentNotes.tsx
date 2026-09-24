/* eslint-disable @typescript-eslint/no-explicit-any, react-hooks/set-state-in-effect */
import { useEffect, useState, useRef } from 'react'
import { getNotes, createNote } from '../../api/counsellor'
import type { Note } from '../../types'

interface Props {
  studentId: string
}

function formatTime(d: string) {
  if (!d) return '—'
  const dt = new Date(d)
  const now = new Date()
  const diff = now.getTime() - dt.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function StudentNotes({ studentId }: Props) {
  const [notes, setNotes] = useState<Note[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [body, setBody] = useState('')
  const [shareWithStudent, setShareWithStudent] = useState(false)
  const [studentTitle, setStudentTitle] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getNotes(studentId)
      // newest first
      setNotes([...data].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [studentId])

  useEffect(() => {
    if (adding && textareaRef.current) {
      textareaRef.current.focus()
    }
  }, [adding])

  const handleSubmit = async () => {
    if (!body.trim()) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const note = await createNote(studentId, body.trim(), { share_with_student: shareWithStudent, student_title: studentTitle.trim() || undefined })
      setNotes((prev) => [note, ...prev])
      setBody('')
      setStudentTitle('')
      setShareWithStudent(false)
      setAdding(false)
    } catch (e: any) {
      setSubmitError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-[8px] py-[16px] text-[#6b7280] text-[0.82rem]">
        <div className="w-[18px] h-[18px] border-2 border-[#e5e7eb] border-t-[#0F766E] rounded-full animate-spin flex-shrink-0" />
        Loading notes...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center gap-[6px] py-[10px] text-[#ef4444] text-[0.82rem]">
        <i className="ti ti-alert-circle text-[16px]" />
        {error}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-[10px]">
      {/* Add note area */}
      {adding ? (
        <div className="flex flex-col gap-[8px]">
          <textarea
            ref={textareaRef}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={3}
            placeholder="Write a note..."
            className="w-full rounded-[8px] border border-[#e5e7eb] px-[12px] py-[8px] text-[0.82rem] text-[#1f2937] placeholder-[#9ca3af] resize-none focus:outline-none focus:ring-2 focus:ring-[#0F766E] focus:border-transparent"
          />
          <label className="flex items-start gap-2 rounded-[8px] border border-teal-100 bg-teal-50 px-3 py-2 text-[0.76rem] text-teal-900">
            <input type="checkbox" checked={shareWithStudent} onChange={(e) => setShareWithStudent(e.target.checked)} className="mt-0.5" />
            <span><b>Share a student-safe update</b><br />This sends a notification and shows this note in the student's Support & feedback space. Do not share clinical or safeguarding details.</span>
          </label>
          {shareWithStudent && <input value={studentTitle} onChange={(e) => setStudentTitle(e.target.value)} maxLength={120} placeholder="Student-facing title, e.g. Your next check-in" className="w-full rounded-[8px] border border-[#e5e7eb] px-[12px] py-[8px] text-[0.82rem]" />}
          {submitError && (
            <div className="text-[#ef4444] text-[0.78rem] flex items-center gap-[4px]">
              <i className="ti ti-alert-circle" /> {submitError}
            </div>
          )}
          <div className="flex items-center gap-[8px]">
            <button
              onClick={handleSubmit}
              disabled={submitting || !body.trim()}
              className="flex items-center gap-[6px] px-[12px] py-[6px] bg-[#0F766E] text-white rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#0d5c56] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? (
                <div className="w-[12px] h-[12px] border-2 border-white/40 border-t-white rounded-full animate-spin" />
              ) : (
                <i className="ti ti-send text-[13px]" />
              )}
              {submitting ? 'Saving...' : 'Save note'}
            </button>
            <button
              onClick={() => { setAdding(false); setBody(''); setStudentTitle(''); setShareWithStudent(false); setSubmitError(null) }}
              disabled={submitting}
              className="px-[12px] py-[6px] border border-[#e5e7eb] text-[#6b7280] rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#f9fafb] transition-colors bg-white disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="self-start flex items-center gap-[6px] px-[12px] py-[6px] border border-dashed border-[#0F766E] text-[#0F766E] rounded-[7px] text-[0.78rem] font-semibold cursor-pointer hover:bg-[#f0fdf9] transition-colors bg-transparent"
        >
          <i className="ti ti-plus text-[14px]" />
          Add note
        </button>
      )}

      {/* Notes list */}
      {notes.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-[24px] text-[#9ca3af]">
          <i className="ti ti-notes text-[26px] mb-[6px]" />
          <span className="text-[0.82rem]">No notes yet.</span>
        </div>
      ) : (
        <div className="flex flex-col gap-[8px]">
          {notes.map((note) => (
            <div key={note.id} className="rounded-[8px] border border-[#f1f5f9] bg-[#f8fafc] px-[14px] py-[10px]">
              <div className="flex items-center justify-between mb-[4px]">
                <span className="text-[0.75rem] font-semibold text-[#374151]">
                  {note.author_name || 'Counsellor'}
                </span>
                <span className="text-[0.7rem] text-[#9ca3af]">{formatTime(note.created_at)}</span>
              </div>
              <p className="text-[0.82rem] text-[#1f2937] whitespace-pre-wrap">{note.body}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

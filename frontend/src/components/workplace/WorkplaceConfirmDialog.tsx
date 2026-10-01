import { useEffect, useRef } from 'react'

export default function WorkplaceConfirmDialog({ message, onCancel, onConfirm }: { message: string; onCancel: () => void; onConfirm: () => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { cancelRef.current?.focus() }, [])
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4" onMouseDown={event => { if (event.target === event.currentTarget) onCancel() }}>
    <section role="alertdialog" aria-modal="true" aria-labelledby="workplace-confirm-title" aria-describedby="workplace-confirm-message" className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl">
      <h2 id="workplace-confirm-title" className="text-lg font-bold text-slate-900">Please confirm</h2>
      <p id="workplace-confirm-message" className="mt-2 text-sm leading-relaxed text-slate-700">{message}</p>
      <div className="mt-5 flex flex-col-reverse justify-end gap-2 sm:flex-row"><button ref={cancelRef} type="button" className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-800 hover:bg-slate-50" onClick={onCancel}>Cancel</button><button type="button" className="rounded-xl bg-rose-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-rose-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-800" onClick={onConfirm}>Continue</button></div>
    </section>
  </div>
}

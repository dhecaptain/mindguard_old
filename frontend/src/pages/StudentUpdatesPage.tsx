import StudentFeedbackPanel from '../components/student/StudentFeedbackPanel'

export default function StudentUpdatesPage() {
  return <div className="mx-auto flex w-full max-w-[1000px] flex-col gap-5">
    <header className="rounded-3xl border border-teal-100 bg-gradient-to-br from-teal-800 via-teal-700 to-cyan-700 p-6 text-white shadow-sm md:p-8">
      <p className="text-xs font-bold uppercase tracking-[0.16em] text-teal-100">Your support space</p>
      <h1 className="mt-2 text-2xl font-bold md:text-3xl">Updates shared with you</h1>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-teal-50">This page contains messages your counsellor has intentionally prepared for you. Private case notes, raw social posts, and internal analysis are not shown here.</p>
    </header>
    <StudentFeedbackPanel limit={30} />
  </div>
}

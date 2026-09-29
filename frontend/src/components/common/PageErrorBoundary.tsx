import { Component, type ErrorInfo, type ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { failed: boolean }

export default class PageErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('MindGuard page render failed', error, info)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <section role="alert" className="mx-auto my-8 max-w-xl rounded-2xl border border-red-200 bg-white p-6 text-center shadow-sm">
        <i className="ti ti-alert-triangle text-3xl text-red-600" aria-hidden="true" />
        <h1 className="mt-3 text-xl font-bold text-slate-900">This page could not be displayed</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">Your session and saved analysis data are unchanged. Reload the page to try again.</p>
        <button type="button" onClick={() => window.location.reload()} className="mt-5 min-h-11 rounded-lg bg-teal-800 px-5 text-sm font-semibold text-white hover:bg-teal-900">Reload page</button>
      </section>
    )
  }
}

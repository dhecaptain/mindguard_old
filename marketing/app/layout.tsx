import type { Metadata } from 'next'
import { Inter, Instrument_Serif } from 'next/font/google'
import Link from 'next/link'
import Script from 'next/script'
import Header from '@/components/Header'
import './globals.css'

const inter = Inter({ subsets: ['latin'], display: 'swap', variable: '--font-sans' })
const instrument = Instrument_Serif({
  subsets: ['latin'],
  weight: '400',
  display: 'swap',
  variable: '--font-serif',
})

export const metadata: Metadata = {
  title: 'MindGuard — Privacy-first wellbeing support',
  description:
    'MindGuard supports school wellbeing teams and a voluntary workplace wellbeing pilot with privacy boundaries, human support and protected aggregate reporting.',
  metadataBase: new URL('https://mindguard.ai'),
  openGraph: {
    title: 'MindGuard — Privacy-first wellbeing support',
    description:
      'Privacy-first wellbeing support for schools, universities and voluntary workplace programmes.',
    type: 'website',
  },
}

const FOOTER_COLS: { title: string; links: { href: string; label: string }[] }[] = [
  {
    title: 'Product',
    links: [
      { href: '/product', label: 'Product' },
      { href: '/for-schools', label: 'For schools' },
      { href: '/for-universities', label: 'For universities' },
      { href: '/for-businesses', label: 'For businesses' },
      { href: '/pricing', label: 'Pricing' },
      { href: '/security', label: 'Security' },
    ],
  },
  {
    title: 'Resources',
    links: [
      { href: '/docs', label: 'Documentation' },
      { href: '/docs/roster-csv', label: 'Roster CSV format' },
      { href: '/docs/faq', label: 'FAQ' },
      { href: '/blog', label: 'Blog' },
      { href: '/contact', label: 'Contact' },
    ],
  },
  {
    title: 'Legal',
    links: [
      { href: '/privacy', label: 'Privacy policy' },
      { href: '/terms', label: 'Terms of service' },
      { href: '/dpa', label: 'Data Processing Agreement' },
    ],
  },
]

const PLAUSIBLE_DOMAIN = process.env.NEXT_PUBLIC_PLAUSIBLE_DOMAIN

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${instrument.variable}`}>
      {PLAUSIBLE_DOMAIN && (
        <Script
          defer
          data-domain={PLAUSIBLE_DOMAIN}
          src="https://plausible.io/js/script.js"
          strategy="afterInteractive"
        />
      )}
      <body className={`min-h-screen flex flex-col font-sans antialiased`}>
        <Header />

        <main className="flex-1">{children}</main>

        <footer className="bg-white border-t border-[rgba(23,33,29,0.08)]">
          <div className="mg-section py-16">
            <div className="grid gap-12 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
              <div>
                <Link href="/" className="flex items-center gap-2.5">
                  <span className="flex h-9 w-9 items-center justify-center rounded-full bg-forest text-white">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M12 3c1.6 1.4 3.4 2 5 2 0 5.5-1 9.5-5 12-4-2.5-5-6.5-5-12 1.6 0 3.4-.6 5-2z" />
                    </svg>
                  </span>
                  <span className="text-lg font-semibold text-ink tracking-tight">MindGuard</span>
                </Link>
                <p className="mt-5 text-sm text-ink-soft leading-relaxed max-w-xs">
                  Human-centred mental-health technology for schools and universities. AI detects
                  signals. People provide care.
                </p>
                <div className="mt-5 inline-flex items-center gap-2 rounded-full border border-[rgba(23,74,58,0.18)] bg-forest-50 px-3 py-1.5 text-[0.72rem] font-semibold text-forest-700">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                    <path d="M12 3l7 4v5c0 4.5-3 8-7 9-4-1-7-4.5-7-9V7l7-4z" />
                    <path d="M9 12l2 2 4-4" />
                  </svg>
                  FERPA-conscious · COPPA-aware
                </div>
              </div>

              {FOOTER_COLS.map((col) => (
                <div key={col.title}>
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-soft mb-5">
                    {col.title}
                  </h3>
                  <ul className="flex flex-col gap-3">
                    {col.links.map((l) => (
                      <li key={l.href}>
                        <Link
                          href={l.href}
                          className="text-sm text-ink-soft hover:text-forest transition-colors duration-200"
                        >
                          {l.label}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            <div className="mt-14 pt-8 border-t border-[rgba(23,33,29,0.08)] flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-ink-soft">
              <div>&copy; {new Date().getFullYear()} MindGuard AI Inc. Student wellbeing, consented.</div>
              <div className="flex items-center gap-5">
                <Link href="/privacy" className="hover:text-forest transition-colors">Privacy</Link>
                <Link href="/terms" className="hover:text-forest transition-colors">Terms</Link>
                <Link href="/dpa" className="hover:text-forest transition-colors">DPA</Link>
                <Link href="/contact" className="hover:text-forest transition-colors">Contact</Link>
              </div>
            </div>
          </div>
        </footer>
      </body>
    </html>
  )
}

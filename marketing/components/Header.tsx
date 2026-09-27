'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { ArrowRight, ExternalLink, Menu, X } from 'lucide-react'
import { APP_URL } from '@/lib/app-url'

const NAV_LINKS = [
  { href: '/product', label: 'Product' },
  { href: '/for-schools', label: 'For schools' },
  { href: '/for-universities', label: 'For universities' },
  { href: '/for-businesses', label: 'For businesses' },
  { href: '/pricing', label: 'Pricing' },
  { href: '/security', label: 'Security' },
  { href: '/about', label: 'About' },
]

export default function Header() {
  const pathname = usePathname()
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    setOpen(false)
  }, [pathname])

  return (
    <header
      className={`sticky top-0 z-50 transition-all duration-300 ${
        scrolled
          ? 'bg-white/85 backdrop-blur-md shadow-[0_1px_0_rgba(23,33,29,0.06)]'
          : 'bg-transparent'
      }`}
    >
      <div className="mg-section flex items-center justify-between py-4">
        {/* Brand */}
        <Link href="/" className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-forest text-white">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 3c1.6 1.4 3.4 2 5 2 0 5.5-1 9.5-5 12-4-2.5-5-6.5-5-12 1.6 0 3.4-.6 5-2z" />
            </svg>
          </span>
          <span className="text-lg font-semibold text-ink tracking-tight">MindGuard</span>
        </Link>

        {/* Desktop nav */}
        <nav className="hidden lg:flex items-center gap-7 text-sm font-medium text-ink-soft">
          {NAV_LINKS.map((l) => {
            const isActive = pathname === l.href
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`relative py-1.5 transition-colors duration-200 ${
                  isActive ? 'text-forest font-semibold' : 'hover:text-forest'
                }`}
              >
                {l.label}
              </Link>
            )
          })}
        </nav>

        {/* Actions */}
        <div className="hidden lg:flex items-center gap-2.5">
          <a
            href={APP_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="mg-btn-ghost"
          >
            <span>Launch App</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
          <Link href="/request-demo" className="mg-btn-primary !px-5 !py-2.5 text-sm">
            <span>Request demo</span>
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>

        {/* Mobile toggle */}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="lg:hidden inline-flex items-center justify-center rounded-lg p-2 text-ink hover:bg-forest-50"
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
        >
          {open ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
        </button>
      </div>

      {/* Mobile menu */}
      {open && (
        <div className="lg:hidden border-t border-[rgba(23,33,29,0.08)] bg-white">
          <nav className="mg-section py-4 flex flex-col gap-1">
            {NAV_LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className="rounded-lg px-3 py-2.5 text-sm font-medium text-ink hover:bg-forest-50"
              >
                {l.label}
              </Link>
            ))}
            <div className="mt-3 flex flex-col gap-2.5 border-t border-[rgba(23,33,29,0.08)] pt-4">
              <a
                href={APP_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="mg-btn-secondary justify-center"
              >
                <span>Launch App</span>
                <ExternalLink className="w-4 h-4" />
              </a>
              <Link href="/request-demo" className="mg-btn-primary justify-center">
                <span>Request demo</span>
                <ArrowRight className="w-4 h-4" />
              </Link>
            </div>
          </nav>
        </div>
      )}
    </header>
  )
}

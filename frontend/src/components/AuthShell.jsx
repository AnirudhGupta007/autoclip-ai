import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Scissors, Loader2 } from 'lucide-react'

/** Shared frame for the sign-in / sign-up pages — same obsidian + gold language as the studio. */
export default function AuthShell({ eyebrow, title, accent, subtitle, children, footer }) {
  return (
    <div className="relative flex min-h-screen flex-col bg-obsidian text-platinum">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-1/2 top-[18%] h-[420px] w-[680px] max-w-[140vw] -translate-x-1/2 animate-drift rounded-full bg-[radial-gradient(closest-side,rgba(212,175,122,0.13),transparent)] blur-2xl" />
      </div>

      <header className="relative flex items-center px-6 py-5">
        <Link to="/" className="flex items-center gap-3" aria-label="AutoClip home">
          <span className="grid h-8 w-8 place-items-center rounded-lg border border-gold-700/60 bg-obsidian-800">
            <Scissors size={14} className="text-gold" aria-hidden="true" />
          </span>
          <span className="font-display text-base leading-none tracking-tight">
            AutoClip<span className="text-gold">.</span>
          </span>
        </Link>
      </header>

      <main className="relative flex flex-1 items-center justify-center px-4 pb-16 sm:px-6">
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
          className="w-full max-w-md"
        >
          <p className="mb-4 text-center text-[11px] uppercase tracking-[0.3em] text-gold-600">{eyebrow}</p>
          <h1 className="mb-3 text-center font-display text-display-md text-platinum">
            {title} {accent && <span className="italic text-gold-400">{accent}</span>}
          </h1>
          {subtitle && (
            <p className="mx-auto mb-8 max-w-sm text-center text-sm leading-relaxed text-platinum-muted">
              {subtitle}
            </p>
          )}
          <div className="glass rounded-3xl px-6 py-7 sm:px-8">{children}</div>
          {footer && <div className="mt-6 text-center text-sm text-platinum-dim">{footer}</div>}
        </motion.div>
      </main>
    </div>
  )
}

export function Field({ id, label, hint, ...props }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-[11px] uppercase tracking-[0.18em] text-platinum-dim">
        {label}
      </label>
      <input
        id={id}
        className="w-full rounded-xl border border-white/10 bg-obsidian-900/80 px-3.5 py-2.5 text-sm text-platinum outline-none transition-colors duration-300 ease-lux placeholder:text-platinum-dim/60 focus:border-gold-700/70"
        {...props}
      />
      {hint && <p className="mt-1.5 text-[11px] text-platinum-dim">{hint}</p>}
    </div>
  )
}

export function GoldButton({ busy, children, ...props }) {
  return (
    <button
      {...props}
      disabled={busy || props.disabled}
      className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gold-sheen bg-[length:200%_auto] px-4 py-2.5 text-sm font-semibold text-obsidian transition-all duration-500 ease-lux hover:bg-[position:80%_50%] disabled:cursor-not-allowed disabled:opacity-40"
    >
      {busy && <Loader2 size={15} className="animate-spin" aria-hidden="true" />}
      {children}
    </button>
  )
}

export function GhostButton({ busy, children, ...props }) {
  return (
    <button
      {...props}
      disabled={busy || props.disabled}
      className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/12 px-4 py-2.5 text-sm text-platinum-muted transition-all duration-300 ease-lux hover:border-gold-700/60 hover:text-platinum disabled:cursor-not-allowed disabled:opacity-40"
    >
      {busy && <Loader2 size={15} className="animate-spin" aria-hidden="true" />}
      {children}
    </button>
  )
}

export function FormError({ children }) {
  if (!children) return null
  return (
    <p role="alert" className="rounded-xl border border-oxblood-400/40 bg-oxblood-600/15 px-3.5 py-2.5 text-sm text-oxblood-400">
      {children}
    </p>
  )
}

export function apiError(err, fallback = 'Something went wrong. Please try again.') {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg.replace(/^Value error, /, '')
  if (err?.code === 'ECONNABORTED') return 'The request timed out. Please try again.'
  return fallback
}

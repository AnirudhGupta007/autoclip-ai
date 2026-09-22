import { motion, useReducedMotion } from 'framer-motion'

/**
 * Hero visual: a long-form timeline with a sweeping playhead, and the
 * moments it detects lifting out as vertical clips. Shows the product's
 * actual job — long video in, short verticals out — instead of stating it.
 *
 * Everything animates on transform/opacity only (no layout thrash), and
 * the whole thing goes static under prefers-reduced-motion.
 */

// Deterministic pseudo-waveform: stable across renders, no layout shift.
const BARS = Array.from({ length: 84 }, (_, i) => {
  const a = Math.sin(i * 0.7) * 0.5 + 0.5
  const b = Math.sin(i * 0.23 + 1.4) * 0.5 + 0.5
  const c = Math.sin(i * 1.9 + 0.3) * 0.25 + 0.25
  return Math.max(0.12, Math.min(1, a * 0.5 + b * 0.35 + c * 0.3))
})

// Detected "moments" as fractions along the timeline.
const MOMENTS = [
  { at: 0.18, label: '0:41', score: '9.1' },
  { at: 0.47, label: '7:12', score: '8.6' },
  { at: 0.78, label: '14:03', score: '9.4' },
]

function ClipCard({ moment, index, reduced }) {
  return (
    <motion.figure
      initial={reduced ? false : { opacity: 0, y: 26, rotate: index === 1 ? 0 : index === 0 ? -5 : 5 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.5 + index * 0.16, duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      className="relative w-[84px] sm:w-[104px] shrink-0"
      style={{ rotate: index === 0 ? '-5deg' : index === 2 ? '5deg' : '0deg' }}
    >
      <div className="glass relative aspect-[9/16] overflow-hidden rounded-xl">
        {/* Frame content stand-in — abstract, not a fake screenshot. */}
        <div className="absolute inset-0 bg-gradient-to-br from-obsidian-600 via-obsidian-800 to-obsidian" />
        <div
          className="absolute inset-0 opacity-70"
          style={{
            background:
              index === 1
                ? 'radial-gradient(120% 80% at 50% 20%, rgba(212,175,122,0.3), transparent 62%)'
                : 'radial-gradient(120% 80% at 50% 25%, rgba(123,45,59,0.32), transparent 62%)',
          }}
        />
        {/* Caption bar, mirroring the real burned-in captions. */}
        <div className="absolute inset-x-1.5 bottom-2 space-y-1">
          <div className="h-1.5 rounded-full bg-platinum/70" style={{ width: '82%' }} />
          <div className="h-1.5 rounded-full bg-platinum/45" style={{ width: '56%' }} />
        </div>
        {/* Score chip */}
        <div className="absolute left-1.5 top-1.5 rounded-md bg-obsidian/80 px-1.5 py-0.5 text-[9px] font-medium text-gold nums backdrop-blur-sm">
          {moment.score}
        </div>
      </div>
      <figcaption className="mt-2 text-center text-[10px] tracking-widest text-platinum-dim nums">
        {moment.label}
      </figcaption>
    </motion.figure>
  )
}

export default function ClipSlicer() {
  const reduced = useReducedMotion()

  return (
    <div className="relative w-full" aria-hidden="true">
      {/* ── Source timeline ───────────────────────────────────── */}
      <div className="glass relative overflow-hidden rounded-2xl px-4 py-4 sm:px-6 sm:py-5">
        <div className="mb-3 flex items-center justify-between text-[10px] uppercase tracking-[0.2em] text-platinum-dim">
          <span>Source · 03:12:47</span>
          <span className="hidden sm:inline">90 chunks analysed</span>
        </div>

        {/* Waveform */}
        <div className="relative flex h-16 items-center gap-[3px] sm:h-20">
          {BARS.map((h, i) => {
            const near = MOMENTS.some((m) => Math.abs(i / BARS.length - m.at) < 0.035)
            return (
              <motion.span
                key={i}
                initial={reduced ? false : { scaleY: 0.25, opacity: 0 }}
                animate={{ scaleY: 1, opacity: 1 }}
                transition={{ delay: reduced ? 0 : 0.15 + i * 0.006, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                className={`w-full origin-center rounded-full ${
                  near ? 'bg-gold/80' : 'bg-platinum/15'
                }`}
                style={{ height: `${h * 100}%` }}
              />
            )
          })}

          {/* Playhead sweep */}
          {!reduced && (
            <motion.span
              className="pointer-events-none absolute inset-y-0 left-0 w-px bg-gold shadow-[0_0_18px_4px_rgba(212,175,122,0.5)]"
              initial={{ x: 0 }}
              animate={{ x: ['0%', '100%'] }}
              transition={{ duration: 7, repeat: Infinity, ease: 'linear', delay: 1 }}
              style={{ left: 0, right: 0 }}
            />
          )}

          {/* Moment markers */}
          {MOMENTS.map((m) => (
            <span
              key={m.at}
              className="pointer-events-none absolute -bottom-1 h-1.5 w-1.5 -translate-x-1/2 rounded-full bg-gold"
              style={{ left: `${m.at * 100}%` }}
            />
          ))}
        </div>
      </div>

      {/* ── Extraction beams ──────────────────────────────────── */}
      <div className="relative mx-auto h-10 w-full max-w-md sm:h-12">
        <svg className="absolute inset-0 h-full w-full" viewBox="0 0 300 48" fill="none" preserveAspectRatio="none">
          {[70, 150, 230].map((x, i) => (
            <motion.path
              key={x}
              d={`M ${x} 0 L ${x} 48`}
              stroke="url(#beam)"
              strokeWidth="1"
              initial={reduced ? false : { pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: 1 }}
              transition={{ delay: 0.45 + i * 0.16, duration: 0.6, ease: 'easeOut' }}
            />
          ))}
          <defs>
            <linearGradient id="beam" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#D4AF7A" stopOpacity="0.9" />
              <stop offset="100%" stopColor="#D4AF7A" stopOpacity="0" />
            </linearGradient>
          </defs>
        </svg>
      </div>

      {/* ── Output clips ──────────────────────────────────────── */}
      <div className="flex items-start justify-center gap-4 sm:gap-7">
        {MOMENTS.map((m, i) => (
          <ClipCard key={m.at} moment={m} index={i} reduced={reduced} />
        ))}
      </div>
    </div>
  )
}

import { motion } from 'framer-motion'
import { ArrowUpRight, FlaskConical, Timer, Coins, Target, ScanSearch } from 'lucide-react'
import results from '../../data/results.json'
import { EASE, Section, SectionHead, fadeUp } from './primitives'

/*
 * "Results — measured, not claimed". Numbers come from data/results.json:
 *   { baseline: {...metrics}, current: {...metrics} | null, updated, method_url, subject }
 * `current` is null while the fixed pipeline is being re-measured; every
 * "after" slot then renders as a pending state instead of a fake number.
 */

const pct = (v) => `${Math.round(v * 100)}%`
const usd = (v) => `$${v.toFixed(2)}`
const mins = (s) => `${(s / 60).toFixed(1)} min`

// Rate metrics, higher is better
const RATES = [
  { key: 'hit_at_3', label: 'Hit@3', note: 'Did any delivered clip match one of the human’s top-3 moments for that ask?' },
  { key: 'category_match', label: 'Category match', note: 'Share of clips that land on a human moment carrying the asked tag (funny, tense, …).' },
  { key: 'moment_recall', label: 'Moment recall', note: 'Share of the 35 human-labelled moments the index found at all.' },
  { key: 'transcript_coverage', label: 'Transcript coverage', note: 'Share of source minutes with at least one transcribed word.' },
  { key: 'captions_present', label: 'Captions present', note: 'Clips with visibly burned-in captions (pixel diff vs. the pre-caption render).' },
  { key: 'length_adherence', label: 'Length adherence', note: 'Delivered length within ±10% of what was asked.' },
]

const TILES = [
  { key: 'hit_at_3', label: 'Hit@3', fmt: pct, icon: Target },
  { key: 'moment_recall', label: 'Moment recall', fmt: pct, icon: ScanSearch },
  { key: 'cost_usd_per_video', label: 'Cost / video', fmt: usd, icon: Coins, lower: true },
  { key: 'wall_s_per_video', label: 'Time / video', fmt: mins, icon: Timer, lower: true },
]

function Pending({ className = '' }) {
  return (
    <span className={`chip px-2.5 text-[10px] uppercase tracking-[0.18em] ${className}`}>
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-platinum-muted" />
      Re-measuring
    </span>
  )
}

function Tile({ t, base, cur }) {
  const Icon = t.icon
  const b = base?.[t.key]
  const c = cur?.[t.key]
  const better = c != null && b != null && (t.lower ? c < b : c > b)
  return (
    <motion.div variants={fadeUp} className="surface relative overflow-hidden rounded-2xl p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-[0.24em] text-platinum-dim">{t.label}</p>
        <Icon size={15} className="text-platinum-dim" aria-hidden="true" />
      </div>
      <p className="text-[10px] uppercase tracking-[0.2em] text-platinum-dim">Before</p>
      <p className="mt-1 font-display text-3xl text-platinum nums sm:text-4xl">{b != null ? t.fmt(b) : '—'}</p>
      <div className="mt-5 flex min-h-[28px] items-center justify-between gap-3 border-t border-white/8 pt-4">
        <p className="text-[10px] uppercase tracking-[0.2em] text-platinum-muted">After</p>
        {c != null ? (
          <p className={`font-display text-xl nums ${better ? 'text-gold' : 'text-platinum'}`}>{t.fmt(c)}</p>
        ) : (
          <Pending />
        )}
      </div>
    </motion.div>
  )
}

function Bar({ value, tone, delay }) {
  const w = Math.max(value * 100, value > 0 ? 1.5 : 0)
  return (
    <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-white/[0.05]">
      <motion.div
        initial={{ scaleX: 0 }}
        whileInView={{ scaleX: 1 }}
        viewport={{ once: true, margin: '-40px' }}
        transition={{ duration: 1.1, delay, ease: EASE }}
        style={{ width: `${w}%` }}
        className={`absolute inset-y-0 left-0 origin-left rounded-full ${tone}`}
      />
    </div>
  )
}

function RateRow({ m, base, cur, i }) {
  const b = base?.[m.key]
  const c = cur?.[m.key]
  return (
    <motion.div variants={fadeUp} className="grid gap-3 border-t border-white/8 py-5 md:grid-cols-[minmax(0,15rem)_1fr] md:gap-8">
      <div>
        <p className="font-display text-base text-platinum">{m.label}</p>
        <p className="mt-1 text-xs leading-relaxed text-platinum-dim">{m.note}</p>
      </div>
      <div className="space-y-2.5 self-center">
        <div className="grid grid-cols-[3.5rem_1fr_3rem] items-center gap-3">
          <span className="text-[10px] uppercase tracking-[0.18em] text-platinum-dim">Before</span>
          <Bar value={b ?? 0} tone="bg-white/25" delay={0.05 * i} />
          <span className="text-right font-mono text-xs text-platinum-muted nums">{b != null ? pct(b) : '—'}</span>
        </div>
        <div className="grid grid-cols-[3.5rem_1fr_3rem] items-center gap-3">
          <span className="text-[10px] uppercase tracking-[0.18em] text-platinum-muted">After</span>
          {c != null ? (
            <Bar value={c} tone="bg-platinum" delay={0.2 + 0.05 * i} />
          ) : (
            <div className="shimmer-track h-2.5 w-full rounded-full" aria-label="re-measuring after pipeline fixes" />
          )}
          <span className="text-right font-mono text-xs text-gold nums">{c != null ? pct(c) : '…'}</span>
        </div>
      </div>
    </motion.div>
  )
}

const CAUGHT = [
  ['Transcript covered 3 of 94 minutes', 'Most moments were found without any dialogue, so asks like "funny" or "best one-liner" had almost nothing to go on.'],
  ['Each window was only half-watched', 'A 24-frame cap meant vision saw roughly the first 60 s of every 120 s chunk.'],
  ['Captions never made it onto the clips', 'A pixel diff of the bottom third against the pre-caption render showed no burned-in text on any delivered clip.'],
  ['Stale clips came back with new answers', 'Each new reply re-sent clips from earlier asks alongside the one you just requested.'],
]

export default function Results() {
  const { baseline: base, current: cur, method_url: method, subject, updated } = results
  return (
    <Section id="results" className="scroll-mt-20 py-24 sm:py-30">
      <SectionHead eyebrow="Results" title="Measured," accent="not claimed.">
        End-to-end evaluation through the real chat API on {subject.label}, against{' '}
        {subject.human_moments} human-labelled moments and {subject.queries} ranked queries. The
        first run was bad, and it is published here as it came out. It is the reason the pipeline was rebuilt.
      </SectionHead>

      <motion.div variants={fadeUp} className="mt-8 flex flex-wrap items-center gap-3 text-xs text-platinum-dim">
        <span className="inline-flex items-center gap-2 rounded-full border border-white/10 px-3 py-1.5">
          <FlaskConical size={13} className="text-platinum-muted" aria-hidden="true" />
          Baseline {base?.measured ?? updated}
          {base?.git && <span className="font-mono text-platinum-dim/80">· {base.git}</span>}
        </span>
        {cur ? (
          <span className="rounded-full border border-white/15 px-3 py-1.5 text-platinum">After {cur.measured ?? ''}</span>
        ) : (
          <span className="text-platinum-muted">“After” is being re-measured following the pipeline fixes.</span>
        )}
      </motion.div>

      <div className="mt-10 grid grid-cols-1 gap-4 min-[420px]:grid-cols-2 lg:grid-cols-4">
        {TILES.map((t) => (
          <Tile key={t.key} t={t} base={base} cur={cur} />
        ))}
      </div>

      <motion.div variants={fadeUp} className="mt-14">
        {RATES.map((m, i) => (
          <RateRow key={m.key} m={m} base={base} cur={cur} i={i} />
        ))}
        <div className="border-t border-white/8" />
      </motion.div>

      <div className="mt-16 grid gap-10 lg:grid-cols-[0.8fr_1.2fr]">
        <motion.div variants={fadeUp}>
          <h3 className="font-display text-display-md text-platinum">
            What the eval <span className="italic text-platinum-muted">caught.</span>
          </h3>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-platinum-muted">
            {subject.match_rule.charAt(0).toUpperCase() + subject.match_rule.slice(1)}. Cost is read from the
            provider’s billing delta, not estimated. {subject.private_note || 'Copyrighted eval sources are never published.'}
          </p>
          <a
            href={method}
            target="_blank"
            rel="noreferrer"
            className="group mt-6 inline-flex items-center gap-2 text-sm text-platinum underline decoration-white/30 underline-offset-4 transition-colors duration-300 hover:decoration-platinum"
          >
            Read the method (EVALUATION.md)
            <ArrowUpRight size={15} className="transition-transform duration-300 ease-lux group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden="true" />
          </a>
        </motion.div>
        <ul className="grid gap-x-8 gap-y-6 sm:grid-cols-2">
          {CAUGHT.map(([t, b]) => (
            <motion.li key={t} variants={fadeUp} className="relative pl-5">
              <span aria-hidden="true" className="absolute left-0 top-2 h-1.5 w-1.5 rounded-full bg-platinum-dim" />
              <p className="mb-1.5 text-sm font-medium text-platinum">{t}</p>
              <p className="text-sm leading-relaxed text-platinum-dim">{b}</p>
            </motion.li>
          ))}
        </ul>
      </div>
    </Section>
  )
}

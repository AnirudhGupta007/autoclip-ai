import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowRight, Scissors, Search, Sparkles, Captions, Gauge, Layers,
  Waves, Cpu, Database, Github,
} from 'lucide-react'
import ClipSlicer from '../components/landing/ClipSlicer'

const fadeUp = {
  hidden: { opacity: 0, y: 22 },
  show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: [0.22, 1, 0.36, 1] } },
}

const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
}

function Section({ children, className = '', ...rest }) {
  return (
    <motion.section
      variants={stagger}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: '-80px' }}
      className={`relative mx-auto w-full max-w-6xl px-6 ${className}`}
      {...rest}
    >
      {children}
    </motion.section>
  )
}

function Eyebrow({ children }) {
  return (
    <motion.p
      variants={fadeUp}
      className="mb-5 flex items-center gap-3 text-[11px] uppercase tracking-[0.32em] text-gold-600"
    >
      <span className="h-px w-8 bg-gold-700" />
      {children}
    </motion.p>
  )
}

/* ── Navigation ─────────────────────────────────────────────── */
function Nav() {
  const [solid, setSolid] = useState(false)
  useEffect(() => {
    const onScroll = () => setSolid(window.scrollY > 24)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-all duration-500 ease-lux ${
        solid ? 'glass-strong border-b border-white/5' : 'border-b border-transparent'
      }`}
    >
      <nav className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-6">
        <Link to="/" className="group flex items-center gap-2.5" aria-label="AutoClip home">
          <span className="grid h-8 w-8 place-items-center rounded-lg border border-gold-700/60 bg-obsidian-800">
            <Scissors size={15} className="text-gold" aria-hidden="true" />
          </span>
          <span className="font-display text-lg tracking-tight">
            AutoClip<span className="text-gold">.</span>
          </span>
        </Link>

        <div className="hidden items-center gap-9 text-sm text-platinum-muted md:flex">
          <a href="#how" className="transition-colors duration-200 hover:text-platinum">How it works</a>
          <a href="#craft" className="transition-colors duration-200 hover:text-platinum">Capabilities</a>
          <a href="#engine" className="transition-colors duration-200 hover:text-platinum">Engine</a>
        </div>

        <Link
          to="/studio"
          className="group inline-flex items-center gap-2 rounded-full border border-gold-700/50 bg-gold/10 px-4 py-2 text-sm text-gold-300 transition-all duration-300 ease-lux hover:border-gold-600 hover:bg-gold/15 hover:shadow-gold"
        >
          Open Studio
          <ArrowRight size={14} className="transition-transform duration-300 ease-lux group-hover:translate-x-0.5" aria-hidden="true" />
        </Link>
      </nav>
    </header>
  )
}

/* ── Hero ───────────────────────────────────────────────────── */
function Hero() {
  return (
    <div className="relative isolate overflow-hidden pt-32 pb-20 sm:pt-40 sm:pb-28">
      {/* Ambient light field */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute left-1/2 top-[-12%] h-[520px] w-[820px] -translate-x-1/2 animate-drift rounded-full bg-[radial-gradient(closest-side,rgba(212,175,122,0.17),transparent)] blur-2xl" />
        <div className="absolute right-[6%] top-[28%] h-[380px] w-[380px] animate-drift rounded-full bg-[radial-gradient(closest-side,rgba(123,45,59,0.22),transparent)] blur-2xl" style={{ animationDelay: '-8s' }} />
        <div className="absolute inset-x-0 bottom-0 h-56 bg-obsidian-fade" />
      </div>

      <Section className="text-center">
        <motion.p
          variants={fadeUp}
          className="mx-auto mb-7 inline-flex items-center gap-2.5 rounded-full border border-white/8 bg-white/[0.03] px-4 py-1.5 text-[11px] uppercase tracking-[0.22em] text-platinum-muted backdrop-blur-sm"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-gold" />
          Three hours in. Sixty seconds out.
        </motion.p>

        <motion.h1 variants={fadeUp} className="font-display text-display-xl">
          <span className="block text-platinum">Every film hides</span>
          <span className="block italic text-gold-sheen">a hundred moments.</span>
        </motion.h1>

        <motion.p
          variants={fadeUp}
          className="mx-auto mt-7 max-w-xl text-base leading-relaxed text-platinum-muted sm:text-lg"
        >
          Upload long-form video. Ask in plain language for what you want —
          a length, a format, a feeling. Get finished vertical clips,
          captioned and scored, without touching a timeline.
        </motion.p>

        <motion.div variants={fadeUp} className="mt-10 flex flex-wrap items-center justify-center gap-4">
          <Link
            to="/studio"
            className="group relative inline-flex items-center gap-2.5 overflow-hidden rounded-full bg-gold-sheen bg-[length:200%_auto] px-7 py-3.5 text-sm font-medium text-obsidian transition-all duration-500 ease-lux hover:bg-[position:80%_50%] hover:shadow-gold"
          >
            Start clipping
            <ArrowRight size={16} className="transition-transform duration-300 ease-lux group-hover:translate-x-1" aria-hidden="true" />
          </Link>
          <a
            href="#how"
            className="inline-flex items-center gap-2 rounded-full border border-white/10 px-6 py-3.5 text-sm text-platinum-muted transition-all duration-300 ease-lux hover:border-white/25 hover:text-platinum"
          >
            See how it works
          </a>
        </motion.div>

        {/* Product visual */}
        <motion.div
          variants={fadeUp}
          className="mx-auto mt-20 w-full max-w-3xl"
        >
          <ClipSlicer />
        </motion.div>
      </Section>
    </div>
  )
}

/* ── Format marquee ─────────────────────────────────────────── */
const FORMATS = [
  '9:16 · TikTok', '15s', '9:16 · Reels', '30s', '1:1 · Instagram',
  '45s', '16:9 · YouTube', '60s', '9:16 · Shorts', '20s',
]

function Marquee() {
  return (
    <div className="relative border-y border-white/5 py-5">
      <div className="mask-fade-x flex gap-10 overflow-hidden">
        {[0, 1].map((dup) => (
          <motion.div
            key={dup}
            className="flex shrink-0 gap-10"
            animate={{ x: ['0%', '-100%'] }}
            transition={{ duration: 34, repeat: Infinity, ease: 'linear' }}
            aria-hidden={dup === 1}
          >
            {FORMATS.map((f, i) => (
              <span
                key={`${f}-${i}`}
                className="whitespace-nowrap text-xs uppercase tracking-[0.28em] text-platinum-dim nums"
              >
                {f}
              </span>
            ))}
          </motion.div>
        ))}
      </div>
    </div>
  )
}

/* ── How it works ───────────────────────────────────────────── */
const STEPS = [
  {
    n: '01',
    title: 'It watches the whole thing',
    body: 'The film is split into two-minute windows analysed in parallel — vision, audio and transcript together. A three-hour feature becomes ninety readings, not one summary.',
    icon: Waves,
  },
  {
    n: '02',
    title: 'You ask in your own words',
    body: '“Where he roasts the competitor.” “The quiet emotional beat.” Retrieval runs on meaning against every indexed moment — not a dropdown of five preset styles.',
    icon: Search,
  },
  {
    n: '03',
    title: 'It cuts, frames and captions',
    body: 'Snapped to scene and word boundaries, reframed to your aspect ratio, captions burned in after the crop, scored on six dimensions, and handed back ready to post.',
    icon: Scissors,
  },
]

function HowItWorks() {
  return (
    <Section id="how" className="py-24 sm:py-30">
      <Eyebrow>The process</Eyebrow>
      <motion.h2 variants={fadeUp} className="max-w-2xl font-display text-display-lg text-platinum">
        Not a filter. <span className="italic text-gold-400">A reading.</span>
      </motion.h2>

      <div className="mt-16 grid gap-px overflow-hidden rounded-2xl border border-white/8 bg-white/5 md:grid-cols-3">
        {STEPS.map(({ n, title, body, icon: Icon }) => (
          <motion.article
            key={n}
            variants={fadeUp}
            className="group relative bg-obsidian-900 p-8 transition-colors duration-500 ease-lux hover:bg-obsidian-800"
          >
            <div className="mb-7 flex items-center justify-between">
              <span className="grid h-10 w-10 place-items-center rounded-lg border border-white/8 bg-white/[0.03] transition-colors duration-500 ease-lux group-hover:border-gold-700/60">
                <Icon size={17} className="text-gold" aria-hidden="true" />
              </span>
              <span className="font-display text-3xl text-white/8 nums transition-colors duration-500 group-hover:text-gold/20">
                {n}
              </span>
            </div>
            <h3 className="mb-3 font-display text-xl text-platinum">{title}</h3>
            <p className="text-sm leading-relaxed text-platinum-muted">{body}</p>
          </motion.article>
        ))}
      </div>
    </Section>
  )
}

/* ── Capabilities ───────────────────────────────────────────── */
const CRAFT = [
  { icon: Search, title: 'Semantic retrieval', body: 'Every moment is embedded and indexed. Ask for a feeling and it finds the feeling.' },
  { icon: Layers, title: 'Any format, one pass', body: 'One analysis feeds unlimited cuts — 15s to 90s, vertical, square or wide.' },
  { icon: Captions, title: 'Captions that fit', body: 'Word-timed, burned in after reframing, so nothing gets sliced off at the edge.' },
  { icon: Gauge, title: 'Scored, not guessed', body: 'Hook, emotion, shareability, retention, controversy, novelty — six axes per clip.' },
  { icon: Sparkles, title: 'Agentic, not scripted', body: 'A planner decides what to call and when, then reports only what actually ran.' },
  { icon: Scissors, title: 'Frame-accurate cuts', body: 'Snapped to keyframes, scene changes and word boundaries. No clipped syllables.' },
]

function Craft() {
  return (
    <Section id="craft" className="py-24 sm:py-30">
      <Eyebrow>Capabilities</Eyebrow>
      <motion.h2 variants={fadeUp} className="max-w-2xl font-display text-display-lg text-platinum">
        Details you'd only notice <span className="italic text-gold-400">if they were wrong.</span>
      </motion.h2>

      <div className="mt-16 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {CRAFT.map(({ icon: Icon, title, body }) => (
          <motion.div
            key={title}
            variants={fadeUp}
            className="glass group rounded-2xl p-7 transition-transform duration-500 ease-lux hover:-translate-y-1"
          >
            <Icon size={19} className="mb-5 text-gold" aria-hidden="true" />
            <h3 className="mb-2.5 font-display text-lg text-platinum">{title}</h3>
            <p className="text-sm leading-relaxed text-platinum-muted">{body}</p>
          </motion.div>
        ))}
      </div>
    </Section>
  )
}

/* ── Engine ─────────────────────────────────────────────────── */
const ENGINE = [
  { icon: Cpu, k: 'Orchestration', v: 'Deep agent on LangGraph' },
  { icon: Waves, k: 'Understanding', v: 'Multimodal vision + audio' },
  { icon: Database, k: 'Retrieval', v: 'LlamaIndex over pgvector' },
  { icon: Scissors, k: 'Production', v: 'ffmpeg, stream-copy cuts' },
]

function Engine() {
  return (
    <Section id="engine" className="py-24 sm:py-30">
      <div className="glass overflow-hidden rounded-3xl">
        <div className="grid lg:grid-cols-2">
          <div className="p-10 sm:p-14">
            <Eyebrow>Under the hood</Eyebrow>
            <motion.h2 variants={fadeUp} className="font-display text-display-md text-platinum">
              Built like infrastructure, <span className="italic text-gold-400">not a wrapper.</span>
            </motion.h2>
            <motion.p variants={fadeUp} className="mt-5 max-w-md text-sm leading-relaxed text-platinum-muted">
              Parallel chunk analysis, a durable job checkpointer, semantic
              indexing and a production pipeline that snaps to real frame
              boundaries. Every model call routes through a single provider,
              so cost and latency stay measurable.
            </motion.p>
          </div>

          <div className="grid grid-cols-1 border-t border-white/8 sm:grid-cols-2 lg:border-l lg:border-t-0">
            {ENGINE.map(({ icon: Icon, k, v }, i) => (
              <motion.div
                key={k}
                variants={fadeUp}
                className={`p-8 ${i % 2 === 0 ? 'sm:border-r' : ''} ${i < 2 ? 'border-b' : ''} border-white/8`}
              >
                <Icon size={16} className="mb-4 text-gold-600" aria-hidden="true" />
                <p className="mb-1 text-[10px] uppercase tracking-[0.24em] text-platinum-dim">{k}</p>
                <p className="text-sm text-platinum">{v}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </Section>
  )
}

/* ── Closing CTA ────────────────────────────────────────────── */
function Closing() {
  return (
    <Section className="py-28 text-center sm:py-32">
      <div aria-hidden="true" className="pointer-events-none absolute left-1/2 top-1/2 -z-10 h-[420px] w-[680px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(closest-side,rgba(212,175,122,0.14),transparent)] blur-2xl" />
      <motion.h2 variants={fadeUp} className="mx-auto max-w-3xl font-display text-display-lg text-platinum">
        Give it your longest video.
        <span className="block italic text-gold-sheen">Ask for the best minute.</span>
      </motion.h2>
      <motion.div variants={fadeUp} className="mt-10">
        <Link
          to="/studio"
          className="group inline-flex items-center gap-2.5 rounded-full bg-gold-sheen bg-[length:200%_auto] px-8 py-4 text-sm font-medium text-obsidian transition-all duration-500 ease-lux hover:bg-[position:80%_50%] hover:shadow-gold"
        >
          Open the Studio
          <ArrowRight size={16} className="transition-transform duration-300 ease-lux group-hover:translate-x-1" aria-hidden="true" />
        </Link>
      </motion.div>
    </Section>
  )
}

function Footer() {
  return (
    <footer className="hairline mt-10">
      <div className="mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-4 px-6 py-9 text-xs text-platinum-dim sm:flex-row">
        <p className="flex items-center gap-2">
          <Scissors size={13} className="text-gold-700" aria-hidden="true" />
          AutoClip — conversational video clipping
        </p>
        <a
          href="https://github.com/AnirudhGupta007/autoclip-ai"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 transition-colors duration-200 hover:text-platinum-muted"
        >
          <Github size={13} aria-hidden="true" />
          Source
        </a>
      </div>
    </footer>
  )
}

export default function Landing() {
  return (
    <div className="grain relative min-h-dvh overflow-x-hidden bg-obsidian">
      <Nav />
      <main>
        <Hero />
        <Marquee />
        <HowItWorks />
        <Craft />
        <Engine />
        <Closing />
      </main>
      <Footer />
    </div>
  )
}

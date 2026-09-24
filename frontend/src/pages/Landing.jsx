import { Component, Suspense, lazy, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, useInView, useReducedMotion, useScroll, useTransform } from 'framer-motion'
import {
  ArrowRight, Scissors, Search, Sparkles, Captions, Gauge, Layers,
  Waves, Cpu, Database, Github,
} from 'lucide-react'

// three.js is ~600KB — keep it out of the main bundle
const FilmScene = lazy(() => import('../components/landing/FilmScene'))

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

        <div className="flex items-center gap-3">
          <a
            href="https://github.com/AnirudhGupta007/autoclip-ai"
            target="_blank"
            rel="noreferrer"
            aria-label="Source on GitHub"
            className="grid h-9 w-9 place-items-center rounded-full border border-white/10 text-platinum-muted transition-colors duration-300 hover:border-white/25 hover:text-platinum"
          >
            <Github size={16} aria-hidden="true" />
          </a>
          <Link
            to="/studio"
            className="group inline-flex items-center gap-2 rounded-full border border-gold-700/50 bg-gold/10 px-4 py-2 text-sm text-gold-300 transition-all duration-300 ease-lux hover:border-gold-600 hover:bg-gold/15 hover:shadow-gold"
          >
            Open Studio
            <ArrowRight size={14} className="transition-transform duration-300 ease-lux group-hover:translate-x-0.5" aria-hidden="true" />
          </Link>
        </div>
      </nav>
    </header>
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

/* ── Film journey (scroll-driven 3D) ────────────────────────── */
const SOURCE_SECONDS = 3 * 3600 + 12 * 60 + 47
const PROMPT = 'give me 5 funny clips under 30s for TikTok'

const timecode = (s) =>
  [Math.floor(s / 3600), Math.floor(s / 60) % 60, Math.floor(s) % 60]
    .map((v) => String(v).padStart(2, '0'))
    .join(':')

class SceneBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    // No WebGL → keep the page usable; the chapters still tell the story
    return this.state.failed ? null : this.props.children
  }
}

function Chapter({ progress, range, className = '', children }) {
  const [a, b, c, d] = range
  const opacity = useTransform(progress, [a, b, c, d], [0, 1, 1, 0])
  const y = useTransform(progress, [a, b, c, d], [48, 0, 0, -48])
  const pointerEvents = useTransform(opacity, (v) => (v > 0.5 ? 'auto' : 'none'))
  return (
    <div className={`pointer-events-none absolute z-10 flex ${className}`}>
      <motion.div style={{ opacity, y, pointerEvents }} className="relative">
        <div aria-hidden="true" className="absolute -inset-x-20 -inset-y-16 -z-10 rounded-full bg-[radial-gradient(closest-side,rgba(0,0,0,0.88),rgba(0,0,0,0.5)_60%,transparent)]" />
        {children}
      </motion.div>
    </div>
  )
}

function ChapterText({ step, title, accent }) {
  const Icon = step.icon
  return (
    <>
      <p className="mb-5 flex items-center gap-3 text-[11px] uppercase tracking-[0.32em] text-gold-600">
        <Icon size={14} className="text-gold" aria-hidden="true" />
        {step.n} — {step.title}
      </p>
      <h2 className="font-display text-display-lg text-platinum">
        {title} <span className="block italic text-gold-sheen">{accent}</span>
      </h2>
      <p className="mt-5 max-w-md text-sm leading-relaxed text-platinum-muted sm:text-base">{step.body}</p>
    </>
  )
}

const HEADLINE = ['Every', 'film', 'hides']
const ACCENT = ['a', 'hundred', 'moments.']

function HeroCopy() {
  const word = (delay) => ({
    initial: { opacity: 0, y: '0.6em', filter: 'blur(8px)' },
    animate: { opacity: 1, y: 0, filter: 'blur(0px)' },
    transition: { duration: 0.9, delay, ease: [0.22, 1, 0.36, 1] },
  })
  return (
    <div className="text-center">
      <motion.p
        {...word(0.1)}
        className="mx-auto mb-7 inline-flex items-center gap-2.5 rounded-full border border-white/10 bg-white/[0.04] px-4 py-1.5 text-[11px] uppercase tracking-[0.22em] text-platinum-muted backdrop-blur-sm"
      >
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-gold" />
        Three hours in. Sixty seconds out.
      </motion.p>
      <h1 className="font-display text-display-xl">
        <span className="block text-platinum">
          {HEADLINE.map((w, i) => (
            <motion.span key={w} {...word(0.25 + i * 0.08)} className="mr-[0.22em] inline-block last:mr-0">
              {w}
            </motion.span>
          ))}
        </span>
        <span className="block italic text-gold-400">
          {ACCENT.map((w, i) => (
            <motion.span key={w} {...word(0.55 + i * 0.1)} className="mr-[0.22em] inline-block pr-[0.05em] last:mr-0">
              {w}
            </motion.span>
          ))}
        </span>
      </h1>
      <motion.p
        {...word(0.95)}
        className="mx-auto mt-7 max-w-xl text-base leading-relaxed text-platinum-muted sm:text-lg"
      >
        Upload long-form video. Ask in plain language for what you want —
        a length, a format, a feeling. Get finished vertical clips,
        captioned and scored, without touching a timeline.
      </motion.p>
      <motion.div {...word(1.1)} className="mt-10 flex flex-wrap items-center justify-center gap-4">
        <Link
          to="/studio"
          className="group relative inline-flex items-center gap-2.5 overflow-hidden rounded-full bg-gold-sheen bg-[length:200%_auto] px-7 py-3.5 text-sm font-medium text-obsidian transition-all duration-500 ease-lux hover:bg-[position:80%_50%] hover:shadow-gold"
        >
          Start clipping
          <ArrowRight size={16} className="transition-transform duration-300 ease-lux group-hover:translate-x-1" aria-hidden="true" />
        </Link>
        <a
          href="#how"
          className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-obsidian/40 px-6 py-3.5 text-sm text-platinum-muted backdrop-blur-sm transition-all duration-300 ease-lux hover:border-white/25 hover:text-platinum"
        >
          See how it works
        </a>
      </motion.div>
    </div>
  )
}

function PromptPill({ progress }) {
  const typed = useTransform(progress, [0.4, 0.5], [0, PROMPT.length], { clamp: true })
  const text = useTransform(typed, (n) => PROMPT.slice(0, Math.round(n)))
  return (
    <div className="mt-8 flex max-w-md items-center gap-3 rounded-2xl border border-gold-700/40 bg-obsidian-800/80 px-5 py-4 shadow-gold backdrop-blur-md">
      <Search size={15} className="shrink-0 text-gold" aria-hidden="true" />
      <p className="min-h-[1.25rem] text-sm text-platinum">
        <motion.span>{text}</motion.span>
        <span className="ml-0.5 inline-block h-4 w-px translate-y-0.5 animate-pulse bg-gold" />
      </p>
    </div>
  )
}

function TimeRail({ progress }) {
  const scaleY = useTransform(progress, [0.1, 0.62], [0, 1])
  const tc = useTransform(progress, (p) => timecode(Math.min(1, Math.max(0, (p - 0.1) / 0.52)) * SOURCE_SECONDS))
  return (
    <div className="pointer-events-none absolute bottom-10 right-8 top-24 z-10 hidden flex-col items-end gap-4 md:flex">
      <p className="text-[10px] uppercase tracking-[0.28em] text-platinum-dim">Source</p>
      <div className="relative w-px flex-1 bg-white/10">
        <motion.div style={{ scaleY }} className="absolute inset-0 origin-top bg-gradient-to-b from-gold-700 to-gold" />
      </div>
      <p className="font-mono text-xs text-gold-300 nums">
        <motion.span>{tc}</motion.span>
        <span className="text-platinum-dim"> / {timecode(SOURCE_SECONDS)}</span>
      </p>
    </div>
  )
}

function FilmJourney() {
  const ref = useRef(null)
  const reduced = useReducedMotion()
  const inView = useInView(ref, { margin: '200px 0px' })
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })
  const hint = useTransform(scrollYProgress, [0, 0.05], [1, 0])

  return (
    <section ref={ref} className="relative z-10 h-[560vh] bg-obsidian" aria-label="How AutoClip works">
      {/* Anchor lands on the first chapter, not the top of the section */}
      <span id="how" className="absolute top-[18%]" />

      <div className="sticky top-0 h-dvh overflow-hidden">
        <SceneBoundary>
          <Suspense fallback={null}>
            <FilmScene progress={scrollYProgress} active={inView} reduced={!!reduced} />
          </Suspense>
        </SceneBoundary>

        {/* Lens vignette + fade into the rest of the page */}
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-[5] bg-[radial-gradient(ellipse_at_center,transparent_45%,rgba(0,0,0,0.85))]" />
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-0 z-[5] h-40 bg-obsidian-fade" />

        <Chapter progress={scrollYProgress} range={[-1, 0, 0.06, 0.12]} className="inset-0 items-center justify-center px-6">
          <HeroCopy />
        </Chapter>

        <Chapter progress={scrollYProgress} range={[0.14, 0.18, 0.3, 0.35]} className="inset-y-0 left-6 right-6 items-center sm:left-[8%] sm:right-auto sm:max-w-xl">
          <ChapterText step={STEPS[0]} title="Ninety readings," accent="not one summary." />
        </Chapter>

        <Chapter progress={scrollYProgress} range={[0.36, 0.4, 0.52, 0.57]} className="inset-y-0 left-6 right-6 items-center sm:left-auto sm:right-[10%] sm:max-w-xl">
          <ChapterText step={STEPS[1]} title="Ask for a feeling." accent="It finds the moment." />
          <PromptPill progress={scrollYProgress} />
        </Chapter>

        <Chapter progress={scrollYProgress} range={[0.64, 0.72, 1, 1.1]} className="inset-x-6 top-[9%] justify-center text-center sm:top-[11%]">
          <p className="mb-4 text-[11px] uppercase tracking-[0.32em] text-gold-600">
            {STEPS[2].n} — {STEPS[2].title}
          </p>
          <h2 className="font-display text-display-md text-platinum sm:text-display-lg">
            Cut, reframed, captioned. <span className="italic text-gold-sheen">Ready to post.</span>
          </h2>
        </Chapter>

        <motion.div
          style={{ opacity: hint }}
          className="pointer-events-none absolute bottom-8 left-1/2 z-10 flex -translate-x-1/2 flex-col items-center gap-3 text-[10px] uppercase tracking-[0.3em] text-platinum-dim"
        >
          Scroll to watch
          <span className="relative h-10 w-px overflow-hidden bg-white/10">
            <span className="absolute inset-x-0 top-0 h-4 animate-[scrollcue_1.8s_ease-in-out_infinite] bg-gold" />
          </span>
        </motion.div>

        <TimeRail progress={scrollYProgress} />
      </div>
    </section>
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

/* ── Footer with oversized wordmark ─────────────────────────── */
const FOOTER_COLS = [
  { title: 'Product', links: [['Open Studio', '/studio', true], ['How it works', '#how'], ['Capabilities', '#craft']] },
  { title: 'Engine', links: [['LangGraph agents', '#engine'], ['Semantic retrieval', '#engine'], ['ffmpeg production', '#engine']] },
  { title: 'Source', links: [['GitHub', 'https://github.com/AnirudhGupta007/autoclip-ai']] },
]

function Footer() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start end', 'end end'] })
  const y = useTransform(scrollYProgress, [0, 1], ['45%', '0%'])
  const tracking = useTransform(scrollYProgress, [0, 1], ['0.12em', '-0.03em'])

  return (
    <footer ref={ref} className="hairline relative mt-10 overflow-hidden">
      <div className="mx-auto grid w-full max-w-6xl gap-10 px-6 pt-16 sm:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <p className="flex items-center gap-2 text-sm text-platinum">
            <Scissors size={14} className="text-gold" aria-hidden="true" />
            AutoClip — conversational video clipping
          </p>
          <p className="mt-3 max-w-xs text-xs leading-relaxed text-platinum-dim">
            Long-form in, short-form out. Ask for a length, a format, a feeling.
          </p>
          <p className="mt-3 max-w-xs text-[11px] leading-relaxed text-platinum-dim/80">
            Footage: <em>Tears of Steel</em> and <em>Sintel</em> © Blender Foundation,{' '}
            <a href="https://creativecommons.org/licenses/by/3.0/" target="_blank" rel="noreferrer" className="underline decoration-white/20 underline-offset-2 hover:text-platinum-muted">
              CC BY 3.0
            </a>
          </p>
        </div>
        {FOOTER_COLS.map(({ title, links }) => (
          <div key={title}>
            <p className="mb-4 text-[10px] uppercase tracking-[0.28em] text-platinum-dim">{title}</p>
            <ul className="space-y-2.5 text-sm text-platinum-muted">
              {links.map(([label, href, internal]) => (
                <li key={label}>
                  {internal ? (
                    <Link to={href} className="transition-colors duration-200 hover:text-gold-300">{label}</Link>
                  ) : (
                    <a
                      href={href}
                      {...(href.startsWith('http') ? { target: '_blank', rel: 'noreferrer' } : {})}
                      className="inline-flex items-center gap-1.5 transition-colors duration-200 hover:text-gold-300"
                    >
                      {href.startsWith('http') && <Github size={13} aria-hidden="true" />}
                      {label}
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <motion.p
        aria-hidden="true"
        style={{
          y,
          letterSpacing: tracking,
          backgroundImage: 'linear-gradient(180deg, #EBD6B3 0%, #8C6A3F 55%, rgba(140,106,63,0) 100%)',
          WebkitBackgroundClip: 'text',
          backgroundClip: 'text',
        }}
        className="mt-10 select-none whitespace-nowrap pb-[2vw] text-center font-display text-[21vw] leading-[0.8] text-transparent"
      >
        AutoClip<span className="italic">.</span>
      </motion.p>
    </footer>
  )
}

export default function Landing() {
  return (
    // overflow-x-clip, not -hidden: `hidden` makes this a scroll container and breaks the sticky canvas
    <div className="relative min-h-dvh overflow-x-clip bg-obsidian">
      <Nav />
      <main>
        <FilmJourney />
        <Marquee />
        <Craft />
        <Engine />
        <Closing />
      </main>
      <Footer />
    </div>
  )
}

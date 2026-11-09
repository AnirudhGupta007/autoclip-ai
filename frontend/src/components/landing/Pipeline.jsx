import { useRef, useState } from 'react'
import { AnimatePresence, motion, useScroll, useTransform } from 'framer-motion'
import {
  Upload, AudioLines, Clapperboard, ScanEye, GitMerge, Database, Bot, Gauge, Video, ChevronDown,
} from 'lucide-react'
import { EASE, Section, SectionHead, fadeUp } from './primitives'
import { C, alpha } from '../../theme'

/*
 * "How it works" — the real pipeline, top to bottom. Each step expands to the
 * tech that actually runs and why it was chosen. Facts here mirror
 * backend/src/autoclip (pipeline/graph.py, agent/*, services/*) and README.
 */

const STEPS = [
  {
    icon: Upload,
    title: 'Upload',
    line: 'Drop a podcast or video up to an hour. Audio becomes an audiogram.',
    tech: ['FastAPI', 'background job', 'Redis pub/sub', 'SSE', 'ffmpeg audiogram'],
    what: 'The upload is stored and an analysis job starts in the background. An audio-only file is first turned into an audiogram video (waveform and title on black), so every later step works the same. Each pipeline node publishes progress to Redis; the browser follows it over Server-Sent Events (chunk done, moments found, clip ready).',
    why: 'An hour-long episode takes minutes to analyse. Holding an HTTP request open that long fails, so the agent starts the job, gives an ETA, and picks your request back up when it finishes.',
  },
  {
    icon: AudioLines,
    title: 'Transcription',
    line: 'Audio becomes a timestamped transcript.',
    tech: ['OpenRouter audio', 'Gemini 2.5 Flash-Lite', '3-min segments ×4'],
    what: 'Audio is split into ~3-minute segments and sent in parallel as input_audio parts. The model returns phrase-level timestamps; word times are spread across each phrase.',
    why: 'OpenRouter has no dedicated speech-to-text endpoint, and one provider key for everything matters more here than a separate ASR bill. Approximate word times are good enough for snapping cut points.',
  },
  {
    icon: Clapperboard,
    title: 'Scene detection',
    line: 'ffmpeg finds every hard cut.',
    tech: ['ffmpeg scene filter', 'threshold 0.3'],
    what: 'ffmpeg’s scene-change filter marks shot boundaries across the whole source.',
    why: 'Clips snap to real cuts, so none of them opens on the last half-second of a different shot.',
  },
  {
    icon: ScanEye,
    title: 'Chunk-parallel vision',
    line: 'The episode is split into 2-minute windows, all analysed at once.',
    tech: ['LangGraph Send API', 'fan-out / fan-in', 'Gemini 2.5 Flash-Lite vision', 'structured output'],
    what: 'chunk_planner cuts 120 s windows with 10 s overlap. The Send API fans out one chunk_analyzer per window, each reading sampled frames together with the transcript for that window, and returning up to five typed moments. Audio uploads skip vision and read the transcript alone; static-camera shots get fewer frames. An operator.add reducer fans them back in.',
    why: 'An hour-long episode becomes ~30 independent readings instead of one lossy summary. The windows run concurrently, and if one fails the others still finish.',
    fan: true,
  },
  {
    icon: GitMerge,
    title: 'Fusion + embeddings',
    line: 'Overlaps merged, duplicates dropped, everything embedded.',
    tech: ['BGE-M3 · 1024-d', 'tIoU ≥ 0.5 merge', 'cosine dedupe ≥ 0.92'],
    what: 'global_fusion merges moments that overlap in time, embeds each with BGE-M3 through OpenRouter, removes near-duplicates by cosine similarity, and ranks by convergence.',
    why: 'Overlapping windows see the same moment twice by design. Fusion turns two partial readings into one confident moment.',
  },
  {
    icon: Database,
    title: 'Moment index',
    line: 'Every moment lands in a searchable vector index.',
    tech: ['Postgres + pgvector', 'LlamaIndex', 'RAG'],
    what: 'Moments are saved as rows and as LlamaIndex nodes in pgvector, filtered by video. A request is answered from three candidate lists (vector similarity, category tags, keywords), re-ranked by one LLM call, then filtered so clips don’t overlap.',
    why: 'You pay for analysis once. Every later ask, in any format or length, is a cheap retrieval plus an ffmpeg cut.',
  },
  {
    icon: Bot,
    title: 'Deep agent',
    line: 'An agent reads your request and decides what to call.',
    tech: ['deepagents', 'LangGraph', 'Gemini 2.5 Flash', 'Postgres checkpointer'],
    what: 'The orchestrator plans with five tools and three subagents. Conversation state is checkpointed in Postgres, one thread per video, so “make clip 2 longer” works.',
    why: 'Requests are open-ended: find, explain, produce, edit, or wait on analysis. A hard rule stops it from describing any clip a tool did not return in this turn.',
  },
  {
    icon: Gauge,
    title: 'Scoring',
    line: 'Candidates scored on six axes and titled.',
    tech: ['Qwen3-30B-A3B', 'structured output', '6 weighted dims'],
    what: 'Hook .20 · emotion .20 · retention .20 · shareability .15 · novelty .15 · controversy .10, plus a title, from a small open-weight model.',
    why: 'Scoring is a narrow, structured task. A cheap open model handles it at a fraction of the orchestrator’s per-token price.',
  },
  {
    icon: Video,
    title: 'Production',
    line: 'Cut, reframed, captioned, thumbnailed.',
    tech: ['ffmpeg', 'face-centred reframe', 'ASS captions', '9:16 · 1:1 · 16:9'],
    what: 'Cuts snap to scene and word boundaries. The frame is reframed around detected faces to the requested aspect ratio, then captions are burned in, then a thumbnail is rendered.',
    why: 'Captions go on after the crop, so the reframe never slices them off at the edge.',
  },
]

/* Small animated glyph: one source → N parallel analysers → fusion → index. */
function FanOutGlyph() {
  const lanes = [0, 1, 2, 3, 4, 5]
  return (
    <svg viewBox="0 0 320 210" className="w-full max-w-[340px]" role="img" aria-label="One video split into six windows analysed in parallel, merged by fusion into a vector index">
      <defs>
        <linearGradient id="fan-src" x1="0" x2="1">
          <stop offset="0" stopColor={C.platinumDim} />
          <stop offset="1" stopColor={C.platinum} />
        </linearGradient>
      </defs>
      {/* source timeline split into windows */}
      {lanes.map((i) => (
        <rect key={`w${i}`} x={14 + i * 49} y={14} width={44} height={16} rx={4} fill="url(#fan-src)" opacity={0.35 + (i % 3) * 0.15} />
      ))}
      <text x={14} y={8} className="fill-platinum-dim" fontSize="8" letterSpacing="1.5">SOURCE · 120 s WINDOWS</text>
      {lanes.map((i) => {
        const x = 36 + i * 49
        return (
          <g key={`l${i}`}>
            <path d={`M${x} 32 V78`} stroke="rgba(255,255,255,0.12)" strokeWidth="1" />
            <path d={`M${x} 32 V78`} stroke={C.platinum} strokeWidth="1.4" className="flow-dash" style={{ animationDelay: `${i * 0.18}s` }} />
            <circle cx={x} cy={92} r={12} fill={C.surface800} stroke="rgba(255,255,255,0.25)" />
            <circle cx={x} cy={92} r={3} fill={C.platinum} className="pulse-dot" style={{ animationDelay: `${i * 0.22}s` }} />
            <path d={`M${x} 104 Q${x} 128 160 140`} fill="none" stroke="rgba(255,255,255,0.12)" />
            <path d={`M${x} 104 Q${x} 128 160 140`} fill="none" stroke={C.platinum} strokeWidth="1.2" className="flow-dash" style={{ animationDelay: `${0.6 + i * 0.12}s` }} />
          </g>
        )
      })}
      <text x={14} y={122} className="fill-platinum-dim" fontSize="8" letterSpacing="1.5">SEND × N</text>
      <rect x={118} y={140} width={84} height={22} rx={11} fill={C.surface700} stroke={alpha(C.gold, 0.7)} />
      <text x={160} y={155} textAnchor="middle" fontSize="9" className="fill-gold" fontWeight="600">fusion</text>
      <path d="M160 162 V176" stroke={alpha(C.platinum, 0.6)} strokeWidth="1.2" />
      <ellipse cx={160} cy={181} rx={26} ry={5} fill={C.surface700} stroke="rgba(255,255,255,0.3)" />
      <path d="M134 181 V197 A26 5 0 0 0 186 197 V181" fill={C.surface800} stroke="rgba(255,255,255,0.3)" />
      <text x={196} y={194} fontSize="8" className="fill-platinum-dim" letterSpacing="1.2">PGVECTOR</text>
    </svg>
  )
}

function Step({ step, index, open, onToggle }) {
  const Icon = step.icon
  const id = `pipe-step-${index}`
  return (
    <motion.li variants={fadeUp} className="relative pl-12 sm:pl-16">
      {/* node on the rail */}
      <motion.span
        aria-hidden="true"
        initial={{ backgroundColor: 'rgb(0, 0, 0)', borderColor: 'rgba(255, 255, 255, 0.12)' }}
        whileInView={{ backgroundColor: 'rgb(18, 18, 24)', borderColor: 'rgba(245, 243, 239, 0.45)' }}
        viewport={{ once: true, margin: '0px 0px -40% 0px' }}
        transition={{ duration: 0.5 }}
        className="absolute left-0 top-4 grid h-9 w-9 place-items-center rounded-full border sm:left-1 sm:h-10 sm:w-10"
      >
        <Icon size={15} className="text-platinum" />
      </motion.span>

      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={id}
        className="group w-full rounded-2xl px-4 py-4 text-left transition-colors duration-300 ease-lux hover:bg-white/[0.03] sm:px-5"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="mb-1 font-mono text-[11px] text-platinum-dim nums">{String(index + 1).padStart(2, '0')}</p>
            <h3 className="font-display text-lg text-platinum sm:text-xl">{step.title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-platinum-muted">{step.line}</p>
          </div>
          <ChevronDown
            size={18}
            aria-hidden="true"
            className={`mt-6 shrink-0 text-platinum-dim transition-transform duration-500 ease-lux group-hover:text-platinum ${open ? 'rotate-180 text-gold' : ''}`}
          />
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {step.tech.map((t) => (
            <span key={t} className="rounded-full border border-white/8 bg-white/[0.03] px-2.5 py-1 text-[11px] text-platinum-muted">
              {t}
            </span>
          ))}
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={id}
            key="body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.45, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="grid gap-5 px-4 pb-5 pt-1 sm:grid-cols-2 sm:px-5">
              <div>
                <p className="mb-1.5 text-[10px] uppercase tracking-[0.24em] text-platinum-dim">What runs</p>
                <p className="text-sm leading-relaxed text-platinum-muted">{step.what}</p>
              </div>
              <div>
                <p className="mb-1.5 text-[10px] uppercase tracking-[0.24em] text-platinum-dim">Why</p>
                <p className="text-sm leading-relaxed text-platinum">{step.why}</p>
              </div>
              {step.fan && (
                <div className="sm:col-span-2 lg:hidden">
                  <FanOutGlyph />
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  )
}

function Phase({ children }) {
  return (
    <motion.li variants={fadeUp} className="relative py-3 pl-12 sm:pl-16">
      <span className="chip text-[10px] uppercase tracking-[0.24em]">
        {children}
      </span>
    </motion.li>
  )
}

export default function Pipeline() {
  const [open, setOpen] = useState(3) // the fan-out step is the interesting one
  const listRef = useRef(null)
  const { scrollYProgress } = useScroll({ target: listRef, offset: ['start 75%', 'end 55%'] })
  const fill = useTransform(scrollYProgress, [0, 1], [0, 1])

  const toggle = (i) => setOpen((cur) => (cur === i ? -1 : i))

  return (
    <Section id="pipeline" className="scroll-mt-20 py-24 sm:py-30">
      <div className="grid gap-12 lg:grid-cols-[0.85fr_1.15fr] lg:gap-16">
        <div className="lg:sticky lg:top-28 lg:self-start">
          <SectionHead eyebrow="How it works" title="Nine steps," accent="from upload to post.">
            Analysis runs once per video, in the background. After that, each request is
            a retrieval, a score and an ffmpeg cut, which is why the second ask comes back
            in seconds. Tap a step for what runs and why.
          </SectionHead>
          <motion.div variants={fadeUp} className="mt-10 hidden lg:block">
            <FanOutGlyph />
          </motion.div>
        </div>

        <div className="relative">
          {/* rail + scroll-linked fill */}
          <div aria-hidden="true" className="absolute bottom-6 left-[17px] top-6 w-px bg-white/8 sm:left-[23px]" />
          <motion.div
            aria-hidden="true"
            style={{ scaleY: fill }}
            className="absolute bottom-6 left-[17px] top-6 w-px origin-top bg-gradient-to-b from-white/20 via-platinum-muted to-platinum sm:left-[23px]"
          />
          <motion.ol ref={listRef} variants={{ show: { transition: { staggerChildren: 0.05 } } }} className="relative space-y-1">
            <Phase>Once per video · background job</Phase>
            {STEPS.slice(0, 6).map((s, i) => (
              <Step key={s.title} step={s} index={i} open={open === i} onToggle={() => toggle(i)} />
            ))}
            <Phase>Every request · one chat turn</Phase>
            {STEPS.slice(6).map((s, j) => {
              const i = j + 6
              return <Step key={s.title} step={s} index={i} open={open === i} onToggle={() => toggle(i)} />
            })}
          </motion.ol>
        </div>
      </div>
    </Section>
  )
}

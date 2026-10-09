import { useEffect, useMemo, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { Bot, Compass, Gavel, Wrench, Cog } from 'lucide-react'
import { EASE, Section, SectionHead, fadeUp, useMediaQuery } from './primitives'

/*
 * Orchestrator + 3 subagents + 5 tools, drawn from agent/orchestrator.py and
 * agent/tools.py. Hover / focus / tap a node to trace its edges.
 */

const NODES = {
  orch: {
    kind: 'Orchestrator', title: 'Orchestrator', sub: 'deepagents · Gemini 2.5 Flash', icon: Bot,
    body: 'Plans each turn and either calls a tool directly or hands the work to a subagent. Built with create_deep_agent on LangGraph, with state checkpointed in Postgres per video. One hard rule: it never names a clip, title or score that a tool did not return in this turn.',
  },
  retrieval: {
    kind: 'Subagent', title: 'retrieval-agent', sub: 'finds moments', icon: Compass,
    body: 'Rewrites your request as a semantic query against the moment index. If the first search comes back thin, it rephrases once before giving up.',
  },
  critic: {
    kind: 'Subagent', title: 'critic-agent', sub: 'reviews the batch', icon: Gavel,
    body: 'Reviews a produced batch of clips. If their average score is under 5/10, it tells the orchestrator which clips are weak and why, so it can retry with a different query.',
  },
  production: {
    kind: 'Subagent', title: 'production-agent', sub: 'runs ffmpeg tools', icon: Wrench,
    body: 'Owns the deterministic production calls. It runs them exactly as instructed and never makes up parameters for ffmpeg.',
  },
  ingest: { kind: 'Tool', title: 'ingest_and_analyze_video', icon: Cog, body: 'Starts the analysis pipeline (transcription, scenes, parallel vision, fusion, indexing) as a background job and returns at once with an ETA.' },
  search: { kind: 'Tool', title: 'search_moments', icon: Cog, body: 'Semantic search over one video’s moments in pgvector, using the LlamaIndex retriever.' },
  status: { kind: 'Tool', title: 'get_video_status', icon: Cog, body: 'Reads video, moment and clip state from the database. Usually the first call in a turn.' },
  produce: { kind: 'Tool', title: 'select_and_produce_clips', icon: Cog, body: 'Retrieves matching moments, snaps them to scene cuts and word timings, scores and titles them, then renders 1–10 clips with ffmpeg.' },
  modify: { kind: 'Tool', title: 'modify_clip', icon: Cog, body: 'Re-cuts or re-captions an existing clip. It shares its code path with the clip-edit API route.' },
}

const SUBS = ['retrieval', 'critic', 'production']
const TOOLS = ['ingest', 'search', 'status', 'produce', 'modify']
const SUB_TOOLS = { retrieval: ['search', 'status'], critic: ['status'], production: ['produce', 'modify'] }

const EDGES = [
  ...SUBS.map((s) => ({ id: `orch-${s}`, from: 'orch', to: s, type: 'delegate' })),
  ...SUBS.flatMap((s) => SUB_TOOLS[s].map((t) => ({ id: `${s}-${t}`, from: s, to: t, type: 'uses' }))),
  ...TOOLS.map((t) => ({ id: `orch-${t}`, from: 'orch', to: t, type: 'direct' })),
]

/* Two layouts: wide (tree, top → bottom) and narrow (subagents left, tools right). */
const WIDE = {
  vb: [900, 400],
  box: {
    orch: { x: 450, y: 52, w: 270, h: 60 },
    retrieval: { x: 180, y: 196, w: 200, h: 52 }, critic: { x: 450, y: 196, w: 200, h: 52 }, production: { x: 720, y: 196, w: 200, h: 52 },
    ingest: { x: 90, y: 340, w: 172, h: 42 }, search: { x: 270, y: 340, w: 172, h: 42 }, status: { x: 450, y: 340, w: 172, h: 42 },
    produce: { x: 630, y: 340, w: 172, h: 42 }, modify: { x: 810, y: 340, w: 172, h: 42 },
  },
  path(e, B) {
    const a = B[e.from]
    const b = B[e.to]
    const x1 = a.x
    const y1 = a.y + a.h / 2
    const x2 = b.x
    const y2 = b.y - b.h / 2
    const my = (y1 + y2) / 2
    return `M${x1} ${y1} C${x1} ${my} ${x2} ${my} ${x2} ${y2}`
  },
  toolFont: 10.5,
}

const NARROW = {
  vb: [360, 430],
  box: {
    orch: { x: 180, y: 40, w: 250, h: 56 },
    retrieval: { x: 72, y: 178, w: 128, h: 46 }, critic: { x: 72, y: 263, w: 128, h: 46 }, production: { x: 72, y: 348, w: 128, h: 46 },
    ingest: { x: 266, y: 130, w: 168, h: 34 }, search: { x: 266, y: 188, w: 168, h: 34 }, status: { x: 266, y: 246, w: 168, h: 34 },
    produce: { x: 266, y: 304, w: 168, h: 34 }, modify: { x: 266, y: 362, w: 168, h: 34 },
  },
  path(e, B) {
    const a = B[e.from]
    const b = B[e.to]
    if (e.type === 'delegate') {
      // trunk straight down from the orchestrator; boxes above mask the overlap
      return `M${b.x} ${a.y + a.h / 2} V${b.y - b.h / 2}`
    }
    if (e.type === 'uses') {
      const x1 = a.x + a.w / 2
      const x2 = b.x - b.w / 2
      const mx = (x1 + x2) / 2
      return `M${x1} ${a.y} C${mx} ${a.y} ${mx} ${b.y} ${x2} ${b.y}`
    }
    // direct: orchestrator right edge → bus down the right margin → tool's right edge
    const xr = b.x + b.w / 2
    return `M${a.x + a.w / 2} ${a.y} H${355} V${b.y} H${xr}`
  },
  toolFont: 10,
}

function Node({ id, b, active, dim, onPick, toolFont }) {
  const n = NODES[id]
  const isTool = n.kind === 'Tool'
  const isOrch = id === 'orch'
  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={`${n.kind}: ${n.title}`}
      aria-pressed={active}
      onMouseEnter={() => onPick(id)}
      onFocus={() => onPick(id)}
      onClick={() => onPick(id)}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onPick(id))}
      className="cursor-pointer outline-none"
      style={{ opacity: dim ? 0.5 : 1, transition: 'opacity .4s cubic-bezier(.22,1,.36,1)' }}
    >
      <rect
        x={b.x - b.w / 2}
        y={b.y - b.h / 2}
        width={b.w}
        height={b.h}
        rx={isTool ? b.h / 2 : 14}
        fill={isOrch ? '#191922' : '#121218'}
        stroke={active ? '#D4AF7A' : isOrch ? 'rgba(212,175,122,0.55)' : 'rgba(255,255,255,0.12)'}
        strokeWidth={active ? 1.6 : 1}
        style={{ transition: 'stroke .3s' }}
      />
      {active && (
        <rect x={b.x - b.w / 2 - 4} y={b.y - b.h / 2 - 4} width={b.w + 8} height={b.h + 8} rx={(isTool ? b.h / 2 : 14) + 4} fill="none" stroke="rgba(212,175,122,0.22)" />
      )}
      {isTool ? (
        <text x={b.x} y={b.y + 3.5} textAnchor="middle" fontFamily='"JetBrains Mono", ui-monospace, monospace' fontSize={toolFont} fill={active ? '#EBD6B3' : '#D2CDC4'}>
          {n.title}
        </text>
      ) : (
        <>
          <text x={b.x} y={b.y - (isOrch ? 3 : 2)} textAnchor="middle" fontFamily='"Plus Jakarta Sans", Inter, sans-serif' fontWeight="700" fontSize={isOrch ? 15 : 12.5} fill="#F5F3EF">
            {n.title}
          </text>
          <text x={b.x} y={b.y + (isOrch ? 15 : 13)} textAnchor="middle" fontSize={isOrch ? 10.5 : 9.5} fill={isOrch ? '#D4AF7A' : '#9C978E'}>
            {n.sub}
          </text>
        </>
      )}
    </g>
  )
}

const AUTO = ['orch', 'retrieval', 'produce', 'critic', 'ingest', 'production']

export default function AgentArchitecture() {
  const narrow = useMediaQuery('(max-width: 639px)')
  const reduced = useReducedMotion()
  const L = narrow ? NARROW : WIDE
  const [sel, setSel] = useState('orch')
  const [touched, setTouched] = useState(false)

  // Gentle auto-tour until the visitor interacts
  useEffect(() => {
    if (touched || reduced) return
    let i = 0
    const t = setInterval(() => {
      i = (i + 1) % AUTO.length
      setSel(AUTO[i])
    }, 3200)
    return () => clearInterval(t)
  }, [touched, reduced])

  const pick = (id) => {
    setTouched(true)
    setSel(id)
  }

  const live = useMemo(() => {
    const edges = new Set()
    const nodes = new Set([sel])
    EDGES.forEach((e) => {
      const hit = e.from === sel || e.to === sel
      // Selecting the orchestrator traces delegation, not the faint direct edges
      if (hit && !(sel === 'orch' && e.type === 'direct')) {
        edges.add(e.id)
        nodes.add(e.from)
        nodes.add(e.to)
      }
    })
    return { edges, nodes }
  }, [sel])

  const n = NODES[sel]

  return (
    <Section id="agent" className="scroll-mt-20 py-24 sm:py-30">
      <SectionHead eyebrow="Agent architecture" title="One planner, three specialists," accent="five tools.">
        The chat is a LangGraph deep agent. It decides what to call. The tools do the
        actual work and always behave the same way.
      </SectionHead>

      <div className="mt-12 grid items-start gap-8">
        <motion.div variants={fadeUp} className="relative mx-auto w-full max-w-5xl">
          <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10 rounded-[2rem] bg-[radial-gradient(60%_50%_at_50%_0%,rgba(212,175,122,0.10),transparent)]" />
          <svg
            viewBox={`0 0 ${L.vb[0]} ${L.vb[1]}`}
            className="h-auto w-full"
            role="group"
            aria-label="Agent graph: orchestrator, subagents and tools"
          >
            {/* edges */}
            {EDGES.map((e) => {
              const d = L.path(e, L.box)
              const on = live.edges.has(e.id)
              const base = e.type === 'direct' ? 'rgba(255,255,255,0.07)' : 'rgba(255,255,255,0.14)'
              return (
                <g key={e.id}>
                  <path d={d} fill="none" stroke={base} strokeWidth="1" strokeDasharray={e.type === 'direct' ? '2 5' : undefined} />
                  {on && <path d={d} fill="none" stroke="#D4AF7A" strokeWidth="1.6" className="flow-dash-long" />}
                </g>
              )
            })}
            {/* nodes */}
            {Object.keys(NODES).map((id) => (
              <Node
                key={id}
                id={id}
                b={L.box[id]}
                active={sel === id}
                dim={!live.nodes.has(id)}
                onPick={pick}
                toolFont={L.toolFont}
              />
            ))}
          </svg>
        </motion.div>

        <motion.div variants={fadeUp} className="glass relative mx-auto min-h-[200px] w-full max-w-3xl rounded-3xl p-6 sm:p-7" aria-live="polite">
          <motion.div
              key={sel}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, ease: EASE }}
            >
              <p className="mb-3 text-[10px] uppercase tracking-[0.28em] text-gold-600">{n.kind}</p>
              <h3 className={`mb-3 break-words text-platinum ${n.kind === 'Tool' ? 'font-mono text-base' : 'font-display text-xl'}`}>{n.title}</h3>
              <p className="text-sm leading-relaxed text-platinum-muted">{n.body}</p>
              {SUB_TOOLS[sel] && (
                <div className="mt-4 flex flex-wrap gap-1.5">
                  {SUB_TOOLS[sel].map((t) => (
                    <span key={t} className="rounded-full border border-gold-700/40 bg-gold/[0.06] px-2.5 py-1 font-mono text-[11px] text-gold-300">
                      {NODES[t].title}
                    </span>
                  ))}
                </div>
              )}
            </motion.div>
          <p className="mt-5 border-t border-white/8 pt-4 text-[11px] leading-relaxed text-platinum-dim">
            Hover or tap any node. Solid lines are delegation; dotted lines are the orchestrator calling a tool directly.
          </p>
        </motion.div>
      </div>

      <motion.div variants={fadeUp} className="mt-16">
        <h3 className="mb-6 font-display text-display-md text-platinum">
          Why an agent <span className="italic text-gold-400">and not a fixed script?</span>
        </h3>
        <div className="grid gap-x-10 gap-y-7 md:grid-cols-3">
          {[
            ['Requests are open-ended', '“4 funny clips under 30s.” “What did you find?” “Make clip 2 longer.” Each one needs a different sequence of calls. A script would turn them into a dropdown.'],
            ['The right step depends on state', 'Not analysed yet? Start the job and give an ETA. Already analysed? Retrieve. A weak batch? The critic asks for a retry. The agent reads the state and picks the branch.'],
            ['The agent decides, the tools act', 'Cutting, scoring and indexing are deterministic tools. The model only chooses which ones to call, and a hard rule stops it from reporting a clip a tool did not return.'],
          ].map(([t, b], i) => (
            <div key={t} className="relative pl-5">
              <span aria-hidden="true" className="absolute left-0 top-1 h-[calc(100%-0.25rem)] w-px bg-gradient-to-b from-gold to-transparent" />
              <p className="mb-1 font-mono text-[11px] text-gold-600 nums">0{i + 1}</p>
              <p className="mb-2 font-display text-base text-platinum">{t}</p>
              <p className="text-sm leading-relaxed text-platinum-muted">{b}</p>
            </div>
          ))}
        </div>
      </motion.div>
    </Section>
  )
}

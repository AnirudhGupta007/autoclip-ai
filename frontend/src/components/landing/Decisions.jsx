import { motion } from 'framer-motion'
import { KeyRound, Radio, Waypoints, Server, ShieldCheck } from 'lucide-react'
import { Section, SectionHead, fadeUp } from './primitives'

const CARDS = [
  {
    icon: KeyRound,
    title: 'One provider, a model per call site',
    body: 'Every model call goes through OpenRouter on a single key, embeddings included, and nothing runs locally. Each call site picks its own model: Flash for tool-calling, Flash-Lite for vision and audio, open-weight Qwen for scoring, BGE-M3 for embeddings.',
    trade: 'Trade-off: no dedicated ASR endpoint, so word timings are approximate.',
    span: 'lg:col-span-4',
  },
  {
    icon: Radio,
    title: 'Background jobs + SSE',
    body: 'Analysis runs as a background job. Pipeline nodes publish to Redis and the browser follows them over Server-Sent Events, so the chat never waits on a 20-minute request.',
    trade: 'Trade-off: the job runs inside the API process for now, not on a separate queue worker.',
    span: 'lg:col-span-2',
  },
  {
    icon: Waypoints,
    title: 'RAG over moments, not style enums',
    body: 'Moments are embedded and retrieved by meaning, so a request isn’t limited to a menu of five preset styles. “Where she explains the pricing mistake” is a valid query.',
    trade: 'Trade-off: retrieval is only as good as the moment descriptions vision writes.',
    span: 'lg:col-span-2',
  },
  {
    icon: Server,
    title: 'One 2 GB box, shipped by CI',
    body: 'Postgres + pgvector, Redis, the API and nginx run under docker compose on a single EC2 t3a.small. Each push to master gets built and checked, then GitHub OIDC assumes a role and SSM redeploys the box, with no SSH port open. The demo runs on HTTPS with a Let’s Encrypt certificate issued for its IP address.',
    trade: 'Trade-off: vertical scale only, and one box is a single point of failure.',
    span: 'lg:col-span-4',
  },
  {
    icon: ShieldCheck,
    title: 'Cost guardrails',
    body: 'Agent runs are metered per user per day (per IP for anonymous visitors), with an optional global daily cap across everyone. If the agent fails, the unit is refunded. Cheap models are used wherever reliable tool-calling isn’t needed.',
    trade: 'Trade-off: a strict quota makes the public demo feel small, by design.',
    span: 'lg:col-span-6',
  },
]

export default function Decisions() {
  return (
    <Section id="decisions" className="scroll-mt-20 py-24 sm:py-30">
      <SectionHead eyebrow="Engineering decisions" title="Choices," accent="and what they cost.">
        Each one was picked for a one-person project that has to stay cheap, observable
        and online.
      </SectionHead>
      <div className="mt-14 grid gap-4 lg:grid-cols-6">
        {CARDS.map(({ icon: Icon, title, body, trade, span }) => (
          <motion.article
            key={title}
            variants={fadeUp}
            className={`surface group relative overflow-hidden rounded-3xl p-6 transition-transform duration-500 ease-lux hover:-translate-y-1 sm:p-8 ${span}`}
          >
            <span aria-hidden="true" className="absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-white/30 to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100" />
            <Icon size={19} className="mb-5 text-platinum-muted" aria-hidden="true" />
            <h3 className="mb-2.5 font-display text-lg text-platinum">{title}</h3>
            <p className="text-sm leading-relaxed text-platinum-muted">{body}</p>
            <p className="mt-4 text-xs leading-relaxed text-platinum-dim">{trade}</p>
          </motion.article>
        ))}
      </div>
    </Section>
  )
}

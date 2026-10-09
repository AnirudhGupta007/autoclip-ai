import { motion } from 'framer-motion'
import { Section, fadeUp } from './primitives'

const STACK = [
  ['Models', ['OpenRouter', 'Gemini 2.5 Flash', 'Gemini 2.5 Flash-Lite', 'Qwen3-30B-A3B', 'BGE-M3']],
  ['Agent & RAG', ['LangGraph', 'deepagents', 'LlamaIndex', 'pgvector']],
  ['Backend', ['Python', 'FastAPI', 'SQLAlchemy', 'PostgreSQL', 'Redis', 'SSE']],
  ['Media', ['ffmpeg', 'OpenCV', 'ASS subtitles']],
  ['Frontend', ['React 18', 'Vite', 'Tailwind', 'react-three-fiber', 'framer-motion']],
  ['Infra', ['Docker Compose', 'EC2', 'GitHub Actions', 'AWS OIDC + SSM', 'nginx', 'Let’s Encrypt']],
]

export default function TechStack() {
  return (
    <Section aria-label="Tech stack" className="pb-8 pt-4">
      <motion.div variants={fadeUp} className="hairline pt-10">
        <p className="mb-8 text-[11px] uppercase tracking-[0.32em] text-platinum-dim">Stack</p>
        <dl className="grid gap-x-10 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
          {STACK.map(([k, items]) => (
            <div key={k}>
              <dt className="mb-2.5 text-[10px] uppercase tracking-[0.24em] text-gold-600">{k}</dt>
              <dd className="flex flex-wrap gap-1.5">
                {items.map((t) => (
                  <span
                    key={t}
                    className="rounded-full border border-white/8 bg-white/[0.03] px-3 py-1 text-xs text-platinum-muted transition-colors duration-300 hover:border-gold-700/60 hover:text-platinum"
                  >
                    {t}
                  </span>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </motion.div>
    </Section>
  )
}

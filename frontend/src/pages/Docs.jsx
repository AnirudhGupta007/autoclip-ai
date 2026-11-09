import { Fragment, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowUpRight, Github, Info } from 'lucide-react'
import AppHeader from '../components/AppHeader'
import { SPRING } from '../components/landing/primitives'
import { REPO, SECTIONS } from '../content/docs'

/* Inline text: `code` and [label](url). Nothing else, on purpose. */
function Inline({ text }) {
  const parts = []
  const re = /`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)/g
  let last = 0
  let m
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    if (m[1]) {
      parts.push(
        <code key={m.index} className="rounded-md border border-white/10 bg-obsidian-800 px-1.5 py-0.5 font-mono text-[0.85em] text-platinum">
          {m[1]}
        </code>,
      )
    } else {
      const external = m[3].startsWith('http')
      parts.push(
        <a
          key={m.index}
          href={m[3]}
          {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}
          className="text-platinum underline decoration-white/30 underline-offset-4 transition-colors hover:decoration-gold"
        >
          {m[2]}
        </a>,
      )
    }
    last = re.lastIndex
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts.map((p, i) => <Fragment key={i}>{p}</Fragment>)
}

function Block({ b }) {
  if (b.p) return <p className="text-[15px] leading-7 text-platinum-muted"><Inline text={b.p} /></p>
  if (b.h) return <h3 className="pt-2 font-display text-lg text-platinum">{b.h}</h3>
  if (b.note)
    return (
      <p className="notice text-[14px] leading-6 text-platinum-muted">
        <Info size={15} className="mt-1 shrink-0 text-platinum-dim" aria-hidden="true" />
        <span><Inline text={b.note} /></span>
      </p>
    )
  if (b.ul)
    return (
      <ul className="space-y-2.5">
        {b.ul.map((t, i) => (
          <li key={i} className="relative pl-5 text-[15px] leading-7 text-platinum-muted">
            <span aria-hidden="true" className="absolute left-0 top-[0.7rem] h-1.5 w-1.5 rounded-full bg-platinum-dim" />
            <Inline text={t} />
          </li>
        ))}
      </ul>
    )
  if (b.ol)
    return (
      <ol className="space-y-3">
        {b.ol.map((t, i) => (
          <li key={i} className="grid grid-cols-[2rem_1fr] text-[15px] leading-7 text-platinum-muted">
            <span className="font-mono text-xs leading-7 text-platinum-dim nums">{String(i + 1).padStart(2, '0')}</span>
            <span><Inline text={t} /></span>
          </li>
        ))}
      </ol>
    )
  if (b.dl)
    return (
      <dl className="surface divide-y divide-white/8 overflow-hidden rounded-2xl">
        {b.dl.map(([k, v]) => (
          <div key={k} className="grid gap-1 px-5 py-4 sm:grid-cols-[10rem_1fr] sm:gap-6">
            <dt className="text-sm font-medium text-platinum">{k}</dt>
            <dd className="text-sm leading-6 text-platinum-muted"><Inline text={v} /></dd>
          </div>
        ))}
      </dl>
    )
  if (b.faq)
    return (
      <div className="surface divide-y divide-white/8 overflow-hidden rounded-2xl">
        {b.faq.map(([q, a]) => (
          <details key={q} className="group">
            <summary className="flex min-h-[52px] cursor-pointer list-none items-center justify-between gap-4 px-5 py-3 text-[15px] text-platinum transition-colors hover:bg-white/[0.03] [&::-webkit-details-marker]:hidden">
              {q}
              <span aria-hidden="true" className="text-lg leading-none text-platinum-dim transition-transform duration-300 ease-lux group-open:rotate-45">+</span>
            </summary>
            <p className="px-5 pb-5 text-sm leading-6 text-platinum-muted"><Inline text={a} /></p>
          </details>
        ))}
      </div>
    )
  return null
}

export default function Docs() {
  const { hash } = useLocation()
  const [active, setActive] = useState(SECTIONS[0].id)

  // react-router doesn't scroll to #hash on its own.
  useEffect(() => {
    if (!hash) return
    const el = document.getElementById(hash.slice(1))
    if (el) requestAnimationFrame(() => el.scrollIntoView({ block: 'start' }))
  }, [hash])

  // Highlight the section being read.
  useEffect(() => {
    const els = SECTIONS.map((s) => document.getElementById(s.id)).filter(Boolean)
    const io = new IntersectionObserver(
      (entries) => {
        const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (vis[0]) setActive(vis[0].target.id)
      },
      { rootMargin: '-72px 0px -65% 0px' },
    )
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [])

  return (
    <div className="min-h-screen bg-obsidian text-platinum">
      <AppHeader />

      <div className="mx-auto grid w-full max-w-6xl gap-10 px-4 pb-24 pt-10 sm:px-6 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-16 lg:pt-16">
        <aside className="lg:sticky lg:top-24 lg:self-start">
          <p className="eyebrow mb-3 hidden lg:block">On this page</p>
          <nav aria-label="Docs sections" className="-mx-4 overflow-x-auto px-4 lg:mx-0 lg:overflow-visible lg:px-0">
            <ul className="flex gap-1.5 lg:flex-col lg:gap-0.5">
              {SECTIONS.map((s) => (
                <li key={s.id} className="shrink-0">
                  <a
                    href={`#${s.id}`}
                    aria-current={active === s.id ? 'true' : undefined}
                    className={`relative flex min-h-[36px] items-center whitespace-nowrap rounded-full border px-3.5 text-[13px] transition-colors duration-200 lg:rounded-lg lg:border-0 lg:px-3 ${
                      active === s.id
                        ? 'border-white/15 bg-white/[0.06] text-platinum'
                        : 'border-white/8 text-platinum-dim hover:text-platinum'
                    }`}
                  >
                    {active === s.id && (
                      <motion.span layoutId="docs-toc" transition={SPRING} aria-hidden="true" className="absolute left-0 top-2 hidden h-5 w-[2px] rounded-full bg-gold lg:block" />
                    )}
                    {s.title}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
          <a href={REPO} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm mt-6 hidden lg:inline-flex">
            <Github size={13} aria-hidden="true" /> Source <ArrowUpRight size={12} aria-hidden="true" />
          </a>
        </aside>

        <main className="min-w-0 max-w-3xl">
          <p className="eyebrow mb-3">Docs</p>
          <h1 className="font-display text-display-md text-platinum">
            How AutoClip works, and the <span className="italic text-gold">fine print.</span>
          </h1>
          <p className="mt-4 max-w-2xl text-[15px] leading-7 text-platinum-muted">
            Podcasts &amp; videos up to an hour in, short captioned clips out. Everything below is
            written to match what the code actually does.
          </p>

          {SECTIONS.map((s) => (
            <section key={s.id} id={s.id} className="scroll-mt-24 border-t border-white/8 pt-10 mt-12" aria-labelledby={`${s.id}-h`}>
              <h2 id={`${s.id}-h`} className="mb-5 font-display text-2xl tracking-tight text-platinum">
                <a href={`#${s.id}`} className="hover:text-platinum-muted">{s.title}</a>
              </h2>
              <div className="space-y-5">
                {s.blocks.map((b, i) => (
                  <Block key={i} b={b} />
                ))}
              </div>
            </section>
          ))}
        </main>
      </div>
    </div>
  )
}

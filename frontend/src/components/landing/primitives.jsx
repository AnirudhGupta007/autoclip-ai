import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'

export const EASE = [0.22, 1, 0.36, 1]

export const fadeUp = {
  hidden: { opacity: 0, y: 22 },
  show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE } },
}

export const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
}

export const GITHUB_URL = 'https://github.com/AnirudhGupta007/autoclip-ai'

export function Section({ children, className = '', ...rest }) {
  return (
    <motion.section
      variants={stagger}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: '-80px' }}
      className={`relative mx-auto w-full max-w-6xl px-5 sm:px-6 ${className}`}
      {...rest}
    >
      {children}
    </motion.section>
  )
}

export function Eyebrow({ children }) {
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

export function SectionHead({ eyebrow, title, accent, children, className = '' }) {
  return (
    <div className={className}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <motion.h2 variants={fadeUp} className="max-w-3xl font-display text-display-lg text-platinum">
        {title} {accent && <span className="italic text-gold-400">{accent}</span>}
      </motion.h2>
      {children && (
        <motion.p variants={fadeUp} className="mt-5 max-w-2xl text-sm leading-relaxed text-platinum-muted sm:text-base">
          {children}
        </motion.p>
      )}
    </div>
  )
}

/* Media query that tracks resize / orientation changes. */
export function useMediaQuery(query) {
  const get = () => typeof window !== 'undefined' && window.matchMedia(query).matches
  const [match, setMatch] = useState(get)
  useEffect(() => {
    const mql = window.matchMedia(query)
    const on = () => setMatch(mql.matches)
    on()
    mql.addEventListener('change', on)
    return () => mql.removeEventListener('change', on)
  }, [query])
  return match
}

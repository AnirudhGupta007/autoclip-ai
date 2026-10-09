import { motion } from 'framer-motion'
import { Section, SectionHead, fadeUp } from './primitives'

const LIMITS = [
  {
    title: 'Word timestamps are approximate',
    now: 'Transcription comes from an LLM, which returns phrase-level timing. Words are spread evenly across each phrase, so a cut can land a syllable early or late.',
    next: 'Forced alignment on the transcript to get exact word boundaries.',
  },
  {
    title: 'Vision sees frames, not motion',
    now: 'Each window is read from sampled frames, so a fast gag or a quick action beat can fall between two of them.',
    next: 'Shot-aware sampling that spends frames where scenes change.',
  },
  {
    title: 'It scales up, not out',
    now: 'One 2 GB box runs the database, queue, API and ffmpeg. Two long films analysed at once will contend for it.',
    next: 'Separate ffmpeg and analysis workers behind a real job queue.',
  },
  {
    title: 'One film, one labeller',
    now: 'The eval is a single 98-minute film labelled by one person. It shows the direction of change well, but it is not a benchmark.',
    next: 'More films and genres, and a second labeller to measure agreement.',
  },
]

export default function Limits() {
  return (
    <Section id="limits" className="scroll-mt-20 py-24 sm:py-30">
      <SectionHead eyebrow="Honest limits" title="What it doesn’t do well," accent="yet.">
        The known weak spots, and what would fix each one.
      </SectionHead>
      <div className="mt-12">
        {LIMITS.map((l, i) => (
          <motion.div
            key={l.title}
            variants={fadeUp}
            className="grid gap-3 border-t border-white/8 py-7 md:grid-cols-[3rem_minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1fr)] md:gap-8"
          >
            <p className="font-mono text-xs text-gold-600 nums md:pt-1">0{i + 1}</p>
            <h3 className="font-display text-lg text-platinum">{l.title}</h3>
            <p className="text-sm leading-relaxed text-platinum-muted">{l.now}</p>
            <p className="text-sm leading-relaxed text-platinum">
              <span className="mr-2 text-[10px] uppercase tracking-[0.22em] text-gold-600">Next</span>
              {l.next}
            </p>
          </motion.div>
        ))}
        <div className="border-t border-white/8" />
      </div>
    </Section>
  )
}

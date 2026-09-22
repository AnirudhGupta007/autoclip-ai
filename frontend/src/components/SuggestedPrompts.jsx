import { motion, AnimatePresence } from 'framer-motion'

const PROMPTS = [
  '4 funny clips under 30s for TikTok',
  'The most emotional moment, 1:1',
  'Best 60s for YouTube Shorts',
  'Where the argument gets heated',
]

export default function SuggestedPrompts({ onSelect, visible }) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 6 }}
          transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          className="mb-3 flex flex-wrap gap-2"
        >
          {PROMPTS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onSelect(p)}
              className="rounded-full border border-white/10 bg-white/[0.03] px-3.5 py-1.5 text-xs text-platinum-muted transition-all duration-300 ease-lux hover:border-gold-700/50 hover:text-platinum"
            >
              {p}
            </button>
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

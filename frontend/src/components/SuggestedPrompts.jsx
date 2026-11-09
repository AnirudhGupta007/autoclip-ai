import { motion, AnimatePresence } from 'framer-motion'

const PROMPTS = [
  '4 funny clips under 30s for TikTok',
  'The most emotional moment, 1:1',
  'Best 60s for YouTube Shorts',
  'The best hot take, 45s',
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
              className="btn btn-secondary btn-sm font-normal text-platinum-muted hover:text-platinum"
            >
              {p}
            </button>
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

import { motion, AnimatePresence } from 'framer-motion'
import { Smile, Star, BookOpen, Flame, Zap } from 'lucide-react'

const prompts = [
  { label: '4 funny TikToks', icon: Smile },
  { label: 'Best highlights', icon: Star },
  { label: 'Educational clips', icon: BookOpen },
  { label: 'Motivational moments', icon: Flame },
  { label: 'Most controversial takes', icon: Zap },
]

export default function SuggestedPrompts({ onSelect, visible }) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          className="flex flex-wrap gap-2 mb-3 overflow-hidden"
        >
          {prompts.map((p, i) => (
            <motion.button
              key={p.label}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9 }}
              transition={{ delay: i * 0.08 }}
              onClick={() => onSelect(p.label)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface border border-gray-700 hover:border-primary/50 hover:bg-primary/10 text-sm text-gray-300 hover:text-white transition-all"
            >
              <p.icon size={13} />
              {p.label}
            </motion.button>
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

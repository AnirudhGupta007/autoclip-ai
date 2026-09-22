import { motion } from 'framer-motion'
import { Scissors } from 'lucide-react'
import ClipCard from './ClipCard'

export default function ChatMessage({ msg }) {
  const isBot = msg.role === 'assistant'

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      className={`flex gap-3.5 ${isBot ? '' : 'flex-row-reverse'}`}
    >
      <div
        className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg border ${
          isBot
            ? 'border-gold-700/50 bg-obsidian-800'
            : 'border-white/10 bg-white/[0.04]'
        }`}
        aria-hidden="true"
      >
        {isBot ? (
          <Scissors size={14} className="text-gold" />
        ) : (
          <span className="text-[11px] uppercase tracking-wider text-platinum-dim">You</span>
        )}
      </div>

      <div className={`min-w-0 max-w-[82%] ${isBot ? '' : 'items-end text-right'}`}>
        <div
          className={`inline-block rounded-2xl px-4 py-3 text-left ${
            isBot ? 'glass' : 'border border-gold-700/30 bg-gold/[0.07]'
          }`}
        >
          <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-platinum">
            {msg.text}
          </p>
        </div>

        {msg.clips?.length > 0 && (
          <div className="mt-4 grid grid-cols-2 gap-3 text-left sm:grid-cols-3 lg:grid-cols-4">
            {msg.clips.map((clip, i) => (
              <ClipCard key={clip.id || i} clip={clip} index={i + 1} />
            ))}
          </div>
        )}

        {msg.moment_count > 0 && !msg.clips?.length && (
          <p className="mt-2 text-[11px] uppercase tracking-[0.18em] text-platinum-dim nums">
            {msg.moment_count} moments indexed
          </p>
        )}
      </div>
    </motion.div>
  )
}

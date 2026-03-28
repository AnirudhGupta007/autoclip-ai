import { motion } from 'framer-motion'
import { Bot, User } from 'lucide-react'
import ClipCard from './ClipCard'

export default function ChatMessage({ msg }) {
  const isBot = msg.role === 'assistant'

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex gap-3 ${isBot ? '' : 'flex-row-reverse'}`}
    >
      <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
        isBot ? 'bg-purple-600' : 'bg-gray-600'
      }`}>
        {isBot ? <Bot size={16} /> : <User size={16} />}
      </div>

      <div className={`max-w-[80%] ${isBot ? '' : 'text-right'}`}>
        <div className={`rounded-2xl px-4 py-3 ${
          isBot
            ? 'bg-gray-800/80 border border-gray-700/50 border-l-2 border-l-primary'
            : 'bg-primary/20 border border-purple-500/30'
        }`}>
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.text}</p>
        </div>

        {/* Render clips if present */}
        {msg.clips && msg.clips.length > 0 && (
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
            {msg.clips.map((clip, i) => (
              <ClipCard key={clip.id || i} clip={clip} index={i + 1} />
            ))}
          </div>
        )}

        {msg.moment_count > 0 && !msg.clips && (
          <div className="mt-2 text-xs text-gray-400">
            {msg.moment_count} moments detected across video
          </div>
        )}
      </div>
    </motion.div>
  )
}

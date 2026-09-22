import { motion } from 'framer-motion'
import { Loader2 } from 'lucide-react'

/**
 * Live pipeline progress. Driven by SSE events (chunk_done / moments /
 * clip_ready) so the user sees work happening during long analysis runs
 * instead of an unexplained wait.
 */
export default function ProcessingIndicator({ progress, liveClips = [] }) {
  const chunks = progress?.chunks || 0
  const moments = progress?.momentCount || 0

  const stage =
    liveClips.length > 0
      ? 'Producing clips'
      : moments > 0
        ? 'Ranking moments'
        : chunks > 0
          ? 'Reading the video'
          : 'Thinking'

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex gap-3.5"
    >
      <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-gold-700/50 bg-obsidian-800">
        <Loader2 size={14} className="animate-spin text-gold" aria-hidden="true" />
      </div>

      <div className="glass min-w-[260px] rounded-2xl px-4 py-3" role="status" aria-live="polite">
        <p className="text-[13px] text-platinum">{stage}…</p>

        <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-platinum-dim nums">
          {chunks > 0 && <span>{chunks} chunks analysed</span>}
          {moments > 0 && <span>{moments} moments found</span>}
          {liveClips.length > 0 && <span>{liveClips.length} clips rendered</span>}
        </div>

        {/* Indeterminate shimmer — duration is genuinely unknown. */}
        <div className="mt-3 h-0.5 w-full overflow-hidden rounded-full bg-white/8">
          <motion.div
            className="h-full w-1/3 rounded-full bg-gold-sheen bg-[length:200%_auto]"
            animate={{ x: ['-100%', '300%'] }}
            transition={{ duration: 1.9, repeat: Infinity, ease: 'easeInOut' }}
          />
        </div>
      </div>
    </motion.div>
  )
}

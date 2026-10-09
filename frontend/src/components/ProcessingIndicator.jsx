import { motion } from 'framer-motion'
import { Loader2 } from 'lucide-react'

function fmtEta(seconds) {
  if (seconds == null) return null
  if (seconds < 60) return 'under a minute left'
  return `about ${Math.round(seconds / 60)} min left`
}

/**
 * Live pipeline progress, driven by SSE events.
 *
 * Two modes:
 *  - `analysis` set: background video analysis (determinate bar, stage,
 *    chunks, ETA) — can run for many minutes across chat turns.
 *  - otherwise: an in-flight chat turn (chunk_done / moments / clip_ready),
 *    with an indeterminate shimmer.
 */
export default function ProcessingIndicator({ progress, liveClips = [], analysis = null }) {
  if (analysis) {
    const pct = Math.max(2, Math.min(100, analysis.progress || 0))
    const stage = analysis.stage ? analysis.stage[0].toUpperCase() + analysis.stage.slice(1) : 'Analysing the video'
    const eta = fmtEta(analysis.eta_seconds)
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex gap-3.5"
      >
        <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-gold-700/50 bg-obsidian-800">
          <Loader2 size={14} className="animate-spin text-gold" aria-hidden="true" />
        </div>

        <div className="glass min-w-[260px] max-w-md flex-1 rounded-2xl px-4 py-3" role="status" aria-live="polite">
          <div className="flex items-baseline justify-between gap-4">
            <p className="text-[13px] text-platinum">{stage}…</p>
            <span className="text-[11px] text-gold-300 nums">{Math.round(pct)}%</span>
          </div>

          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-platinum-dim nums">
            {analysis.chunks_total > 0 && (
              <span>
                {analysis.chunks_done || 0} / {analysis.chunks_total} chunks
              </span>
            )}
            {eta && <span>{eta}</span>}
          </div>

          <div
            className="mt-3 h-1 w-full overflow-hidden rounded-full bg-white/8"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(pct)}
          >
            <motion.div
              className="h-full rounded-full bg-gold-sheen bg-[length:200%_auto]"
              initial={false}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.6, ease: 'easeOut' }}
            />
          </div>
          <p className="mt-2 text-[11px] text-platinum-dim">
            You can leave this tab open — your request continues automatically when analysis finishes.
          </p>
        </div>
      </motion.div>
    )
  }

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

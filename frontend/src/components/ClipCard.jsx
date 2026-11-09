import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Play, Download, ChevronDown, Video } from 'lucide-react'
import ScoreRing from './ScoreRing'
import { SPRING_SOFT } from './landing/primitives'

const SCORE_KEYS = ['hook', 'emotion', 'shareability', 'retention', 'controversy', 'novelty']

function formatTime(seconds) {
  if (seconds == null) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function ScoreBar({ label, value = 0 }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-[86px] shrink-0 text-[10px] uppercase tracking-wider text-platinum-dim">
        {label}
      </span>
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/8">
        <motion.div
          className="h-full rounded-full bg-platinum-muted"
          initial={{ width: 0 }}
          animate={{ width: `${(value || 0) * 10}%` }}
          transition={{ duration: 0.7, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>
      <span className="w-6 text-right text-[10px] text-platinum-muted nums">
        {value?.toFixed(1)}
      </span>
    </div>
  )
}

export default function ClipCard({ clip, index }) {
  const [playing, setPlaying] = useState(false)
  const [expanded, setExpanded] = useState(false)

  // Vertical formats get a portrait preview; 16:9 stays landscape.
  const vertical = (clip.frame || '9:16') === '9:16'
  const square = clip.frame === '1:1'
  const aspect = vertical ? 'aspect-[9/16]' : square ? 'aspect-square' : 'aspect-video'

  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...SPRING_SOFT, delay: index * 0.06 }}
      className="surface group overflow-hidden rounded-2xl transition-[border-color,transform] duration-300 ease-lux hover:-translate-y-0.5 hover:border-white/20"
    >
      {/* Preview */}
      <div className={`relative ${aspect} bg-obsidian-900`}>
        {playing && clip.file_url ? (
          <video
            src={clip.file_url}
            controls
            autoPlay
            className="h-full w-full object-contain"
            aria-label={clip.title || `Clip ${index}`}
          />
        ) : (
          <button
            type="button"
            onClick={() => setPlaying(true)}
            className="group/play absolute inset-0 h-full w-full cursor-pointer"
            aria-label={`Play ${clip.title || `clip ${index}`}`}
          >
            {clip.thumbnail_url ? (
              <img
                src={clip.thumbnail_url}
                alt=""
                loading="lazy"
                className="h-full w-full object-cover"
              />
            ) : (
              <span className="grid h-full w-full place-items-center text-platinum-dim">
                <Video size={26} aria-hidden="true" />
              </span>
            )}
            <span className="absolute inset-0 bg-gradient-to-t from-obsidian/90 via-transparent to-obsidian/30" />
            <span className="absolute inset-0 grid place-items-center opacity-0 transition-opacity duration-300 ease-lux group-hover/play:opacity-100">
              <span className="grid h-12 w-12 place-items-center rounded-full bg-gold text-obsidian shadow-elev-2">
                <Play size={16} className="ml-0.5 fill-current" aria-hidden="true" />
              </span>
            </span>
          </button>
        )}

        {/* Rank */}
        <span className="pointer-events-none absolute left-2.5 top-2.5 rounded-md border border-white/10 bg-obsidian/80 px-2 py-0.5 font-display text-xs text-platinum backdrop-blur-sm nums">
          {String(index).padStart(2, '0')}
        </span>

        {/* Score */}
        {clip.overall_score != null && (
          <div className="pointer-events-none absolute right-2.5 top-2.5">
            <ScoreRing score={clip.overall_score} />
          </div>
        )}

        {/* Duration */}
        <span className="pointer-events-none absolute bottom-2.5 right-2.5 rounded-md bg-obsidian/80 px-2 py-0.5 text-[10px] text-platinum backdrop-blur-sm nums">
          {clip.duration?.toFixed(1)}s
        </span>
      </div>

      {/* Meta */}
      <div className="p-4">
        <h4 className="mb-2.5 font-display text-[15px] leading-snug text-platinum">
          {clip.title || `Clip ${index}`}
        </h4>

        <div className="flex flex-wrap items-center gap-1.5">
          <span className="rounded border border-white/15 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-platinum-muted nums">
            {clip.frame || '9:16'}
          </span>
          {clip.style_tags?.slice(0, 2).map((tag) => (
            <span
              key={tag}
              className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-platinum-dim"
            >
              {tag}
            </span>
          ))}
          {clip.start_time != null && (
            <span className="ml-auto text-[10px] text-platinum-dim nums">
              {formatTime(clip.start_time)}–{formatTime(clip.end_time)}
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-3 flex min-h-[32px] w-full items-center justify-between rounded-lg px-1 text-xs text-platinum-dim transition-colors duration-200 hover:text-platinum"
        >
          {expanded ? 'Hide details' : 'Details'}
          <motion.span animate={{ rotate: expanded ? 180 : 0 }} transition={{ duration: 0.25 }}>
            <ChevronDown size={14} aria-hidden="true" />
          </motion.span>
        </button>

        <AnimatePresence initial={false}>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
              className="overflow-hidden"
            >
              <div className="hairline mt-3 space-y-4 pt-4">
                {clip.scores && (
                  <div className="space-y-2">
                    {SCORE_KEYS.map((k) => (
                      <ScoreBar key={k} label={k} value={clip.scores[k]} />
                    ))}
                  </div>
                )}

                {clip.transcript && (
                  <blockquote className="border-l border-white/15 pl-3 text-xs italic leading-relaxed text-platinum-muted">
                    {clip.transcript.slice(0, 180)}
                    {clip.transcript.length > 180 ? '…' : ''}
                  </blockquote>
                )}

                {clip.file_url && (
                  <a
                    href={clip.file_url}
                    download
                    className="btn btn-primary btn-sm w-full rounded-lg"
                  >
                    <Download size={13} aria-hidden="true" />
                    Download clip
                  </a>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.article>
  )
}

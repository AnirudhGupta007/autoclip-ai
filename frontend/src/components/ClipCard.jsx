import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Video, Download, ChevronDown } from 'lucide-react'
import ScoreRing from './ScoreRing'

const scoreLabels = ['hook', 'emotion', 'shareability', 'retention', 'controversy', 'novelty']

function ScoreBar({ label, value }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-gray-400 w-20 capitalize">{label}</span>
      <div className="flex-1 bg-gray-700 rounded-full h-1.5">
        <motion.div
          className="h-1.5 rounded-full bg-gradient-to-r from-primary to-accent"
          initial={{ width: 0 }}
          animate={{ width: `${(value || 0) * 10}%` }}
          transition={{ duration: 0.6, delay: 0.2 }}
        />
      </div>
      <span className="text-[10px] text-gray-400 w-6 text-right">{value?.toFixed(1)}</span>
    </div>
  )
}

export default function ClipCard({ clip, index }) {
  const [showVideo, setShowVideo] = useState(false)
  const [expanded, setExpanded] = useState(false)

  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.9, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ delay: index * 0.1, type: 'spring', stiffness: 200, damping: 20 }}
      whileHover={{ scale: 1.02 }}
      className="bg-gray-800/60 rounded-xl border border-gray-700/50 overflow-hidden hover:border-primary/30 transition-colors"
    >
      {/* Thumbnail / Video */}
      <div
        className="relative aspect-video bg-gray-900 cursor-pointer group"
        onClick={() => setShowVideo(!showVideo)}
      >
        {showVideo && clip.file_url ? (
          <video
            src={clip.file_url}
            controls
            autoPlay
            className="w-full h-full object-contain"
          />
        ) : clip.thumbnail_url ? (
          <>
            <img src={clip.thumbnail_url} alt={clip.title} className="w-full h-full object-cover" />
            <div className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 group-hover:opacity-100 transition-opacity">
              <div className="w-12 h-12 rounded-full bg-white/20 backdrop-blur flex items-center justify-center">
                <Video size={20} />
              </div>
            </div>
          </>
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-500">
            <Video size={32} />
          </div>
        )}

        {/* Duration badge */}
        <span className="absolute bottom-2 right-2 bg-black/70 text-xs px-2 py-0.5 rounded">
          {clip.duration?.toFixed(0)}s
        </span>

        {/* Index badge */}
        <span className="absolute top-2 left-2 bg-purple-600 text-xs px-2 py-0.5 rounded font-bold">
          #{index}
        </span>

        {/* Score ring */}
        {clip.overall_score && (
          <div className="absolute top-2 right-2">
            <ScoreRing score={clip.overall_score} />
          </div>
        )}
      </div>

      {/* Info */}
      <div
        className="p-3 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-medium truncate flex-1">{clip.title || `Clip ${index}`}</h4>
          <motion.div
            animate={{ rotate: expanded ? 180 : 0 }}
            transition={{ duration: 0.2 }}
          >
            <ChevronDown size={14} className="text-gray-400" />
          </motion.div>
        </div>

        <div className="flex items-center gap-1 mt-2 flex-wrap">
          {clip.style_tags?.slice(0, 2).map(tag => (
            <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded bg-purple-600/20 text-purple-300">
              {tag}
            </span>
          ))}
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-600/20 text-cyan-300">
            {clip.frame || '9:16'}
          </span>
        </div>

        {/* Expanded details */}
        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="overflow-hidden"
            >
              <div className="pt-3 mt-3 border-t border-gray-700/50 space-y-3">
                {/* Score breakdown */}
                {clip.scores && (
                  <div className="space-y-1.5">
                    {scoreLabels.map(key => (
                      <ScoreBar key={key} label={key} value={clip.scores[key]} />
                    ))}
                  </div>
                )}

                {/* Transcript preview */}
                {clip.transcript && (
                  <p className="text-xs text-gray-400 italic line-clamp-3">
                    "{clip.transcript.slice(0, 150)}{clip.transcript.length > 150 ? '...' : ''}"
                  </p>
                )}

                {/* Time range */}
                {clip.start_time != null && (
                  <p className="text-[10px] text-gray-500">
                    {formatTime(clip.start_time)} — {formatTime(clip.end_time)}
                  </p>
                )}

                {/* Download button */}
                {clip.file_url && (
                  <a
                    href={clip.file_url}
                    download
                    onClick={e => e.stopPropagation()}
                    className="flex items-center justify-center gap-1.5 w-full px-3 py-2 bg-primary/20 hover:bg-primary/30 text-primary rounded-lg text-xs font-medium transition-colors"
                  >
                    <Download size={13} />
                    Download clip
                  </a>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}

function formatTime(seconds) {
  if (seconds == null) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

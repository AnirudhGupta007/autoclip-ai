import { useState } from 'react'
import { motion } from 'framer-motion'
import { Play, Download, Settings, Star } from 'lucide-react'
import ScoreRadar from './ScoreRadar'

export default function ClipCard({ clip, onPlay, onExport, onEdit }) {
  const [showScores, setShowScores] = useState(false)

  const thumbnailUrl = clip.thumbnail_path
    ? `/outputs/${clip.video_id}/clips/${clip.id}/thumbnail.jpg`
    : null

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      className="bg-card rounded-xl border border-white/5 overflow-hidden hover:border-primary/30 transition-all group"
    >
      {/* Thumbnail */}
      <div
        className="relative aspect-video bg-black cursor-pointer"
        onClick={() => onPlay?.(clip)}
      >
        {thumbnailUrl ? (
          <img
            src={thumbnailUrl}
            alt={clip.title}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-surface">
            <Play className="w-12 h-12 text-muted" />
          </div>
        )}
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-all flex items-center justify-center">
          <Play className="w-12 h-12 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
        </div>
        <div className="absolute top-2 right-2 bg-black/70 px-2 py-0.5 rounded text-xs">
          {formatDuration(clip.duration)}
        </div>
      </div>

      {/* Info */}
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-semibold line-clamp-2">{clip.title || 'Untitled Clip'}</h3>
          {clip.overall_score && (
            <div className="flex items-center gap-1 text-warning flex-shrink-0">
              <Star className="w-3.5 h-3.5 fill-warning" />
              <span className="text-xs font-bold">{clip.overall_score.toFixed(1)}</span>
            </div>
          )}
        </div>

        {clip.transcript && (
          <p className="text-xs text-muted mt-2 line-clamp-2">{clip.transcript}</p>
        )}

        {/* Score radar toggle */}
        {clip.scores && (
          <div className="mt-3">
            <button
              onClick={() => setShowScores(!showScores)}
              className="text-xs text-primary hover:text-accent transition-colors"
            >
              {showScores ? 'Hide scores' : 'View scores'}
            </button>
            {showScores && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                className="flex justify-center mt-2"
              >
                <ScoreRadar scores={clip.scores} size={180} />
              </motion.div>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 mt-3">
          <button
            onClick={() => onExport?.(clip)}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-primary/20 text-primary rounded-lg text-xs font-medium hover:bg-primary/30 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            Export
          </button>
          <button
            onClick={() => onEdit?.(clip)}
            className="flex items-center justify-center px-3 py-2 bg-white/5 text-muted rounded-lg text-xs hover:bg-white/10 hover:text-white transition-colors"
          >
            <Settings className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </motion.div>
  )
}

function formatDuration(seconds) {
  if (!seconds) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

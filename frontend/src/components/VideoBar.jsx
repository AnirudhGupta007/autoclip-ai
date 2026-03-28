import { motion } from 'framer-motion'
import { Film, Clock, Monitor, Upload } from 'lucide-react'

function formatDuration(seconds) {
  if (!seconds) return null
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function VideoBar({ videoName, videoDuration, videoResolution, onNewUpload }) {
  return (
    <motion.div
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="px-6 py-2.5 bg-surface/80 backdrop-blur-sm border-b border-gray-800 flex items-center gap-3"
    >
      <Film size={14} className="text-primary shrink-0" />
      <span className="text-sm text-gray-200 truncate max-w-[200px]">{videoName}</span>

      {videoDuration && (
        <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-primary/20 text-purple-300">
          <Clock size={10} />
          {formatDuration(videoDuration)}
        </span>
      )}

      {videoResolution && (
        <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-accent/20 text-cyan-300">
          <Monitor size={10} />
          {videoResolution}
        </span>
      )}

      <div className="flex-1" />

      <label className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white cursor-pointer transition-colors">
        <Upload size={12} />
        New video
        <input
          type="file"
          accept="video/*"
          className="hidden"
          onChange={e => e.target.files?.[0] && onNewUpload(e.target.files[0])}
        />
      </label>
    </motion.div>
  )
}

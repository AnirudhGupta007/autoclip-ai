import { useRef } from 'react'
import { Film, RotateCcw } from 'lucide-react'

function fmtDuration(s) {
  if (!s) return '—'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    : `${m}:${String(sec).padStart(2, '0')}`
}

export default function VideoBar({ videoName, videoDuration, videoResolution, onNewUpload }) {
  const inputRef = useRef(null)

  return (
    <div className="hairline flex shrink-0 items-center gap-3 px-6 py-3">
      <span className="grid h-8 w-8 place-items-center rounded-lg border border-white/8 bg-white/[0.03]">
        <Film size={14} className="text-gold" aria-hidden="true" />
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] text-platinum">{videoName || 'Untitled'}</p>
        <p className="text-[11px] text-platinum-dim nums">
          {fmtDuration(videoDuration)} · {videoResolution || 'detecting'}
        </p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(e) => e.target.files?.[0] && onNewUpload(e.target.files[0])}
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="inline-flex items-center gap-2 rounded-full border border-white/10 px-3.5 py-1.5 text-xs text-platinum-muted transition-all duration-300 ease-lux hover:border-gold-700/50 hover:text-platinum"
      >
        <RotateCcw size={12} aria-hidden="true" />
        New video
      </button>
    </div>
  )
}

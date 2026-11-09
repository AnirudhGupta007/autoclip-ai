import { useRef } from 'react'
import { Video, Mic, RotateCcw } from 'lucide-react'
import { ACCEPT_ATTR } from './UploadZone'

function fmtDuration(s) {
  if (!s) return '—'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    : `${m}:${String(sec).padStart(2, '0')}`
}

export default function VideoBar({ videoName, videoDuration, videoResolution, mediaKind, onNewUpload }) {
  const inputRef = useRef(null)
  const audio = mediaKind === 'audio'
  const Icon = audio ? Mic : Video

  return (
    <div className="flex shrink-0 items-center gap-3 border-b border-white/8 px-4 py-2.5 sm:px-6">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/8 bg-obsidian-800">
        <Icon size={14} className="text-platinum-muted" aria-hidden="true" />
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] text-platinum">{videoName || 'Untitled'}</p>
        <p className="text-[11px] text-platinum-dim nums">
          {fmtDuration(videoDuration)} · {audio ? 'audio · audiogram clips' : videoResolution || 'detecting'}
        </p>
      </div>

      {onNewUpload && (<>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT_ATTR}
        className="hidden"
        onChange={(e) => e.target.files?.[0] && onNewUpload(e.target.files[0])}
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="btn btn-secondary btn-sm"
      >
        <RotateCcw size={12} aria-hidden="true" />
        New upload
      </button>
      </>)}
    </div>
  )
}

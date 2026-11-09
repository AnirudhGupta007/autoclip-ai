import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { motion } from 'framer-motion'
import { UploadCloud, Loader2 } from 'lucide-react'
import { SPRING_SOFT } from './landing/primitives'

export const MAX_UPLOAD_MB = 300
export const VIDEO_EXT = ['.mp4', '.mov', '.mkv', '.webm']
export const AUDIO_EXT = ['.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac']
// Extensions as well as MIME types: browsers report m4a/flac inconsistently.
export const ACCEPT = { 'video/*': VIDEO_EXT, 'audio/*': AUDIO_EXT }
export const ACCEPT_ATTR = ['video/*', 'audio/*', ...VIDEO_EXT, ...AUDIO_EXT].join(',')

export default function UploadZone({ onUpload, onReject, uploading, uploadProgress }) {
  const onDrop = useCallback(
    (files) => { if (files?.[0]) onUpload(files[0]) },
    [onUpload],
  )

  const onDropRejected = useCallback(
    (rejections) => {
      const code = rejections?.[0]?.errors?.[0]?.code
      onReject?.(
        code === 'file-too-large'
          ? `That file is over ${MAX_UPLOAD_MB} MB. Trim it or export a smaller copy.`
          : 'That file type isn’t supported. Use a video (MP4, MOV, MKV, WEBM) or audio (MP3, M4A, WAV, AAC, OGG, FLAC).',
      )
    },
    [onReject],
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected,
    accept: ACCEPT,
    maxSize: MAX_UPLOAD_MB * 1024 * 1024,
    multiple: false,
    disabled: uploading,
  })

  return (
    <div
      {...getRootProps()}
      className={`surface group relative w-full cursor-pointer overflow-hidden rounded-3xl px-6 py-12 text-center transition-[border-color,background-color] duration-300 ease-lux sm:px-8 sm:py-14 ${
        isDragActive ? '!border-gold bg-obsidian-800' : 'hover:border-white/20'
      } ${uploading ? 'cursor-wait' : ''}`}
    >
      <input {...getInputProps()} aria-label="Upload a podcast or video file" />

      <motion.span
        animate={{ scale: isDragActive ? 1.08 : 1 }}
        transition={SPRING_SOFT}
        className="mx-auto mb-6 grid h-14 w-14 place-items-center rounded-2xl border border-white/10 bg-obsidian-800 shadow-elev-1"
      >
        {uploading ? (
          <Loader2 size={20} className="animate-spin text-platinum" aria-hidden="true" />
        ) : (
          <UploadCloud size={20} className={isDragActive ? 'text-gold' : 'text-platinum'} aria-hidden="true" />
        )}
      </motion.span>

      {uploading ? (
        <>
          <p className="font-display text-xl text-platinum">Uploading…</p>
          <div className="mx-auto mt-5 h-1 w-56 overflow-hidden rounded-full bg-white/8">
            <motion.div
              className="h-full rounded-full bg-gold"
              animate={{ width: `${uploadProgress || 0}%` }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
            />
          </div>
          <p className="mt-2.5 text-xs text-platinum-dim nums">{uploadProgress || 0}%</p>
        </>
      ) : (
        <>
          <p className="font-display text-xl text-platinum">
            {isDragActive ? 'Drop it here' : 'Drop a podcast or video, or click to browse'}
          </p>
          <p className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-platinum-muted">
            Podcasts &amp; videos up to 1 hour, {MAX_UPLOAD_MB} MB max. Audio-only
            episodes come back as captioned audiogram clips.
          </p>
          <p className="mt-5 text-[11px] uppercase tracking-[0.2em] text-platinum-dim">
            MP4 · MOV · MKV · WEBM · MP3 · M4A · WAV · AAC · OGG · FLAC
          </p>
        </>
      )}
    </div>
  )
}

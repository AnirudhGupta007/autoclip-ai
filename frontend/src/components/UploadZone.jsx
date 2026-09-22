import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { motion } from 'framer-motion'
import { UploadCloud, Loader2 } from 'lucide-react'

export default function UploadZone({ onUpload, uploading, uploadProgress }) {
  const onDrop = useCallback(
    (files) => { if (files?.[0]) onUpload(files[0]) },
    [onUpload],
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'video/*': [] },
    multiple: false,
    disabled: uploading,
  })

  return (
    <div
      {...getRootProps()}
      className={`glass group relative w-full cursor-pointer overflow-hidden rounded-3xl px-8 py-14 text-center transition-all duration-500 ease-lux ${
        isDragActive ? 'border-gold-600 shadow-gold' : 'hover:border-gold-700/50'
      } ${uploading ? 'cursor-wait' : ''}`}
    >
      <input {...getInputProps()} aria-label="Upload a video file" />

      <span className="mx-auto mb-6 grid h-14 w-14 place-items-center rounded-2xl border border-gold-700/40 bg-obsidian-800">
        {uploading ? (
          <Loader2 size={20} className="animate-spin text-gold" aria-hidden="true" />
        ) : (
          <UploadCloud size={20} className="text-gold" aria-hidden="true" />
        )}
      </span>

      {uploading ? (
        <>
          <p className="font-display text-xl text-platinum">Uploading…</p>
          <div className="mx-auto mt-5 h-1 w-56 overflow-hidden rounded-full bg-white/8">
            <motion.div
              className="h-full rounded-full bg-gold-sheen bg-[length:200%_auto]"
              animate={{ width: `${uploadProgress || 0}%` }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
            />
          </div>
          <p className="mt-2.5 text-xs text-platinum-dim nums">{uploadProgress || 0}%</p>
        </>
      ) : (
        <>
          <p className="font-display text-xl text-platinum">
            {isDragActive ? 'Drop it here' : 'Drop a video, or click to browse'}
          </p>
          <p className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-platinum-muted">
            Podcasts, interviews, lectures, films. The longer the source, the
            more it has to find.
          </p>
          <p className="mt-5 text-[11px] uppercase tracking-[0.22em] text-platinum-dim">
            MP4 · MOV · MKV · WEBM
          </p>
        </>
      )}
    </div>
  )
}

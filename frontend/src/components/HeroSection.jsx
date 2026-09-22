import { motion } from 'framer-motion'
import UploadZone from './UploadZone'

export default function HeroSection({ onUpload, uploading, uploadProgress }) {
  return (
    <div className="relative flex flex-1 items-center justify-center overflow-y-auto px-6 py-14">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute left-1/2 top-1/4 h-[420px] w-[680px] -translate-x-1/2 animate-drift rounded-full bg-[radial-gradient(closest-side,rgba(212,175,122,0.14),transparent)] blur-2xl" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-xl text-center"
      >
        <p className="mb-5 text-[11px] uppercase tracking-[0.3em] text-gold-600">
          The Studio
        </p>
        <h2 className="mb-4 font-display text-display-md text-platinum">
          Start with the <span className="italic text-gold-400">long cut.</span>
        </h2>
        <p className="mx-auto mb-10 max-w-md text-sm leading-relaxed text-platinum-muted">
          Upload once. Every clip you ask for afterwards reuses the same
          analysis — no re-processing, no waiting twice.
        </p>

        <UploadZone
          onUpload={onUpload}
          uploading={uploading}
          uploadProgress={uploadProgress}
        />
      </motion.div>
    </div>
  )
}

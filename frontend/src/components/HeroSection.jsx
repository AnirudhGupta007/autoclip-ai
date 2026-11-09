import { motion } from 'framer-motion'
import UploadZone from './UploadZone'

export default function HeroSection({ onUpload, onReject, uploading, uploadProgress }) {
  return (
    <div className="relative flex flex-1 items-center justify-center overflow-y-auto px-4 py-14 sm:px-6">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-1/4 h-[420px] w-[680px] max-w-[140vw] -translate-x-1/2 animate-drift rounded-full bg-[radial-gradient(closest-side,rgb(var(--c-platinum)/0.05),transparent)] blur-2xl" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-xl text-center"
      >
        <p className="eyebrow mb-5">The Studio</p>
        <h2 className="mb-4 font-display text-display-md text-platinum">
          Start with the <span className="italic text-gold">full episode.</span>
        </h2>
        <p className="mx-auto mb-10 max-w-md text-sm leading-relaxed text-platinum-muted">
          Upload once. Every clip you ask for afterwards reuses the same
          analysis — no re-processing, no waiting twice.
        </p>

        <UploadZone
          onUpload={onUpload}
          onReject={onReject}
          uploading={uploading}
          uploadProgress={uploadProgress}
        />
      </motion.div>
    </div>
  )
}

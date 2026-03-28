import { motion } from 'framer-motion'
import { Sparkles, Video, MessageSquare } from 'lucide-react'
import UploadZone from './UploadZone'

const features = [
  { label: 'AI-Powered Analysis', icon: Sparkles },
  { label: 'Multi-Modal Detection', icon: Video },
  { label: 'One Conversation', icon: MessageSquare },
]

export default function HeroSection({ onUpload, uploading, uploadProgress }) {
  return (
    <div className="flex-1 flex items-center justify-center px-6">
      <div className="max-w-xl w-full text-center space-y-8">
        {/* Gradient glow background */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[600px] h-[600px] rounded-full bg-gradient-to-br from-primary/20 to-accent/20 blur-[120px] animate-gradient" />
        </div>

        {/* Heading */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="relative space-y-3"
        >
          <h1 className="text-4xl md:text-5xl font-bold bg-gradient-to-r from-white via-purple-200 to-accent bg-clip-text text-transparent leading-tight">
            Turn long videos into viral clips
          </h1>
          <p className="text-gray-400 text-lg">
            Upload a video, describe what you want, and let AI do the rest.
          </p>
        </motion.div>

        {/* Feature pills */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3 }}
          className="flex flex-wrap justify-center gap-3 relative"
        >
          {features.map((f, i) => (
            <motion.div
              key={f.label}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 + i * 0.15 }}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-surface border border-gray-700/50 text-sm text-gray-300"
            >
              <f.icon size={14} className="text-primary" />
              {f.label}
            </motion.div>
          ))}
        </motion.div>

        {/* Upload zone */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6, duration: 0.5 }}
          className="relative"
        >
          <UploadZone
            onUpload={onUpload}
            uploading={uploading}
            uploadProgress={uploadProgress}
          />
        </motion.div>
      </div>
    </div>
  )
}

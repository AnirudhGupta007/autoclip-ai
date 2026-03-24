import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Sparkles, Loader2 } from 'lucide-react'
import DropZone from '../components/DropZone'
import { uploadVideo } from '../services/api'

export default function Home() {
  const navigate = useNavigate()
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [error, setError] = useState(null)

  const handleProcess = async () => {
    if (!file) return
    setUploading(true)
    setError(null)

    try {
      const { data } = await uploadVideo(file, setUploadProgress)
      navigate(`/process/${data.id}`)
    } catch (err) {
      setError(err.response?.data?.detail || 'Upload failed')
      setUploading(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="max-w-3xl mx-auto"
    >
      <div className="text-center mb-8">
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ type: 'spring', stiffness: 200 }}
          className="inline-flex items-center gap-2 px-4 py-1.5 bg-primary/10 rounded-full mb-4"
        >
          <Sparkles className="w-4 h-4 text-primary" />
          <span className="text-sm text-primary font-medium">AI-Powered</span>
        </motion.div>
        <h1 className="text-4xl font-bold mb-3">
          Turn long videos into{' '}
          <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            viral clips
          </span>
        </h1>
        <p className="text-muted">
          Upload a video and let AI find the best moments, add animated captions, and export for every platform.
        </p>
      </div>

      <DropZone onFileSelected={setFile} />

      {file && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-6"
        >
          {uploading ? (
            <div className="space-y-3">
              <div className="h-2 bg-surface rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-gradient-to-r from-primary to-accent"
                  initial={{ width: 0 }}
                  animate={{ width: `${uploadProgress}%` }}
                />
              </div>
              <div className="flex items-center justify-center gap-2 text-sm text-muted">
                <Loader2 className="w-4 h-4 animate-spin" />
                Uploading... {uploadProgress}%
              </div>
            </div>
          ) : (
            <button
              onClick={handleProcess}
              className="w-full py-3 bg-gradient-to-r from-primary to-accent text-white rounded-xl font-medium text-lg hover:opacity-90 transition-opacity"
            >
              Process Video with AI
            </button>
          )}
        </motion.div>
      )}

      {error && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="mt-4 text-center text-sm text-error"
        >
          {error}
        </motion.p>
      )}

      {/* Features */}
      <div className="grid grid-cols-3 gap-4 mt-12">
        {[
          { title: 'Smart Clipping', desc: 'AI finds the most engaging moments' },
          { title: 'Animated Captions', desc: '5 caption styles with word-by-word timing' },
          { title: 'Multi-Format', desc: 'Export for TikTok, Reels, YouTube, Twitter' },
        ].map((f, i) => (
          <motion.div
            key={f.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 + i * 0.1 }}
            className="p-4 bg-card rounded-xl border border-white/5 text-center"
          >
            <h3 className="text-sm font-semibold mb-1">{f.title}</h3>
            <p className="text-xs text-muted">{f.desc}</p>
          </motion.div>
        ))}
      </div>
    </motion.div>
  )
}

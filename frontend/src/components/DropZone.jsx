import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { motion } from 'framer-motion'
import { Upload, Film, X } from 'lucide-react'

export default function DropZone({ onFileSelected }) {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)

  const onDrop = useCallback((accepted) => {
    if (accepted.length > 0) {
      const f = accepted[0]
      setFile(f)
      setPreview(URL.createObjectURL(f))
      onFileSelected(f)
    }
  }, [onFileSelected])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'video/*': ['.mp4', '.mov', '.avi', '.mkv', '.webm'] },
    maxFiles: 1,
    multiple: false,
  })

  const clearFile = () => {
    setFile(null)
    setPreview(null)
    onFileSelected(null)
  }

  if (file && preview) {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="relative bg-card rounded-xl border border-white/10 overflow-hidden"
      >
        <button
          onClick={clearFile}
          className="absolute top-3 right-3 z-10 p-2 bg-black/60 rounded-full hover:bg-error/80 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
        <video
          src={preview}
          controls
          className="w-full max-h-[400px] object-contain bg-black"
        />
        <div className="p-4 flex items-center gap-3">
          <Film className="w-5 h-5 text-primary" />
          <div>
            <p className="text-sm font-medium">{file.name}</p>
            <p className="text-xs text-muted">
              {(file.size / (1024 * 1024)).toFixed(1)} MB
            </p>
          </div>
        </div>
      </motion.div>
    )
  }

  return (
    <div
      {...getRootProps()}
      className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-all ${
        isDragActive
          ? 'border-primary bg-primary/10'
          : 'border-white/10 hover:border-primary/50 hover:bg-white/[0.02]'
      }`}
    >
      <input {...getInputProps()} />
      <motion.div
        animate={isDragActive ? { scale: 1.05 } : { scale: 1 }}
        className="flex flex-col items-center gap-4"
      >
        <div className="w-16 h-16 bg-primary/20 rounded-full flex items-center justify-center">
          <Upload className="w-8 h-8 text-primary" />
        </div>
        <div>
          <p className="text-lg font-medium">
            {isDragActive ? 'Drop your video here' : 'Drag & drop a video'}
          </p>
          <p className="text-sm text-muted mt-1">
            or click to browse — MP4, MOV, AVI, MKV, WebM (max 500MB)
          </p>
        </div>
      </motion.div>
    </div>
  )
}

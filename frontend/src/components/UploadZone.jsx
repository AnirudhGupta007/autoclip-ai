import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { motion } from 'framer-motion'
import { Upload, Loader2 } from 'lucide-react'

export default function UploadZone({ onUpload, uploading, uploadProgress }) {
  const onDrop = useCallback((accepted) => {
    if (accepted?.[0]) onUpload(accepted[0])
  }, [onUpload])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'video/*': ['.mp4', '.mov', '.avi', '.mkv', '.webm'] },
    maxFiles: 1,
    disabled: uploading,
  })

  return (
    <motion.div
      {...getRootProps()}
      animate={{ scale: isDragActive ? 1.02 : 1 }}
      transition={{ type: 'spring', stiffness: 300 }}
      className={`border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all ${
        uploading
          ? 'border-purple-500/50 bg-purple-500/5'
          : isDragActive
            ? 'border-accent bg-accent/5'
            : 'border-gray-600 hover:border-purple-500/50 hover:bg-purple-500/5'
      }`}
    >
      <input {...getInputProps()} />

      {uploading ? (
        <div className="space-y-3">
          <Loader2 className="animate-spin mx-auto text-purple-400" size={28} />
          <p className="text-sm text-gray-400">Uploading... {uploadProgress}%</p>
          <div className="w-full max-w-xs mx-auto bg-gray-700 rounded-full h-2">
            <motion.div
              className="h-2 rounded-full bg-gradient-to-r from-primary to-accent"
              initial={{ width: 0 }}
              animate={{ width: `${uploadProgress}%` }}
              transition={{ ease: 'easeOut' }}
            />
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <motion.div
            animate={{ y: [0, -4, 0] }}
            transition={{ repeat: Infinity, duration: 2, ease: 'easeInOut' }}
          >
            <Upload className="mx-auto text-gray-400" size={32} />
          </motion.div>
          <p className="text-sm text-gray-300">
            {isDragActive ? 'Drop your video here' : 'Drop a video or click to upload'}
          </p>
          <p className="text-xs text-gray-500">MP4, MOV, AVI, MKV, WebM (max 500MB)</p>
        </div>
      )}
    </motion.div>
  )
}

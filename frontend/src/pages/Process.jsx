import { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight } from 'lucide-react'
import ProgressTracker from '../components/ProgressTracker'
import useSSE from '../hooks/useSSE'

export default function Process() {
  const { videoId } = useParams()
  const navigate = useNavigate()
  const sseUrl = `/api/pipeline/process/${videoId}`
  const { stages, currentStage, isComplete, error, result, connect } = useSSE(sseUrl)

  useEffect(() => {
    connect()
  }, [connect])

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="max-w-2xl mx-auto"
    >
      <div className="text-center mb-8">
        <h1 className="text-2xl font-bold mb-2">Processing Your Video</h1>
        <p className="text-sm text-muted">
          AI is analyzing your video and creating viral-ready clips
        </p>
      </div>

      <ProgressTracker
        stages={stages}
        currentStage={currentStage}
        error={error}
      />

      {isComplete && result && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-8 text-center"
        >
          <div className="p-6 bg-success/10 border border-success/30 rounded-xl mb-4">
            <p className="text-success font-medium">
              Processing complete! {result.clips_count} clips generated.
            </p>
          </div>
          <button
            onClick={() => navigate(`/results/${videoId}`)}
            className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-primary to-accent text-white rounded-xl font-medium hover:opacity-90 transition-opacity"
          >
            View Results
            <ArrowRight className="w-4 h-4" />
          </button>
        </motion.div>
      )}

      {error && !isComplete && (
        <div className="mt-6 text-center">
          <button
            onClick={() => navigate('/')}
            className="px-6 py-2 bg-white/10 text-white rounded-lg text-sm hover:bg-white/20 transition-colors"
          >
            Back to Upload
          </button>
        </div>
      )}
    </motion.div>
  )
}

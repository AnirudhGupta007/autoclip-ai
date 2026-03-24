import { motion } from 'framer-motion'
import { Check, Loader2, Circle } from 'lucide-react'

const STAGES = [
  { id: 1, name: 'Transcription', desc: 'Converting speech to text' },
  { id: 2, name: 'Scene Analysis', desc: 'Detecting scene boundaries' },
  { id: 3, name: 'AI Chunking', desc: 'Finding viral segments' },
  { id: 4, name: 'Scoring', desc: 'Rating engagement potential' },
  { id: 5, name: 'Production', desc: 'Cutting & captioning clips' },
]

export default function ProgressTracker({ stages, currentStage, error }) {
  return (
    <div className="space-y-4">
      {STAGES.map((stage) => {
        const data = stages[stage.id]
        const isActive = currentStage === stage.id
        const isComplete = data?.progress === 100 && currentStage > stage.id
        const isPending = !data && currentStage < stage.id

        return (
          <motion.div
            key={stage.id}
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: stage.id * 0.1 }}
            className={`p-4 rounded-xl border transition-all ${
              isActive
                ? 'bg-primary/10 border-primary/30'
                : isComplete
                ? 'bg-success/5 border-success/20'
                : 'bg-card border-white/5'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0">
                {isComplete ? (
                  <div className="w-8 h-8 bg-success/20 rounded-full flex items-center justify-center">
                    <Check className="w-4 h-4 text-success" />
                  </div>
                ) : isActive ? (
                  <div className="w-8 h-8 bg-primary/20 rounded-full flex items-center justify-center">
                    <Loader2 className="w-4 h-4 text-primary animate-spin" />
                  </div>
                ) : (
                  <div className="w-8 h-8 bg-white/5 rounded-full flex items-center justify-center">
                    <Circle className="w-4 h-4 text-muted" />
                  </div>
                )}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium">
                    Stage {stage.id}: {stage.name}
                  </h3>
                  {data && (
                    <span className="text-xs text-muted">{data.progress}%</span>
                  )}
                </div>
                <p className="text-xs text-muted mt-0.5">
                  {data?.message || stage.desc}
                </p>
              </div>
            </div>

            {isActive && data && (
              <div className="mt-3 ml-11">
                <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-gradient-to-r from-primary to-accent rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${data.progress}%` }}
                    transition={{ duration: 0.5 }}
                  />
                </div>
              </div>
            )}
          </motion.div>
        )
      })}

      {error && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="p-4 bg-error/10 border border-error/30 rounded-xl"
        >
          <p className="text-sm text-error">{error}</p>
        </motion.div>
      )}
    </div>
  )
}

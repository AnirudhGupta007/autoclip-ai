import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Scissors, TrendingUp, Film, Bot, Sparkles } from 'lucide-react'

const steps = [
  { label: 'Transcribing audio', icon: Search, duration: 3000 },
  { label: 'Analyzing chunks in parallel', icon: Scissors, duration: 4000 },
  { label: 'Fusing moments', icon: TrendingUp, duration: 2000 },
  { label: 'Producing clips', icon: Film, duration: 5000 },
]

export default function ProcessingIndicator({ progress, liveClips = [] }) {
  const [currentStep, setCurrentStep] = useState(0)

  useEffect(() => {
    if (currentStep >= steps.length - 1) return
    const timer = setTimeout(() => setCurrentStep(p => p + 1), steps[currentStep].duration)
    return () => clearTimeout(timer)
  }, [currentStep])

  // Live signals from SSE override the canned step animation
  const live = progress || {}
  if (live.chunks && currentStep < 1) setCurrentStep(1)
  if (live.momentCount && currentStep < 2) setCurrentStep(2)
  if (liveClips.length && currentStep < 3) setCurrentStep(3)

  const pct = ((currentStep + 1) / steps.length) * 100
  const StepIcon = steps[currentStep].icon

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex gap-3"
    >
      <div className="w-8 h-8 rounded-full bg-purple-600 flex items-center justify-center shrink-0">
        <Bot size={16} />
      </div>

      <div className="bg-gray-800/80 border border-gray-700/50 rounded-2xl px-5 py-4 space-y-3 min-w-[320px]">
        <div className="flex items-center gap-2">
          <AnimatePresence mode="wait">
            <motion.div
              key={currentStep}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.3 }}
              className="flex items-center gap-2"
            >
              <StepIcon size={14} className="text-primary" />
              <span className="text-sm text-gray-300">{steps[currentStep].label}...</span>
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Live counters from SSE */}
        {(live.chunks || live.momentCount || liveClips.length) ? (
          <div className="flex flex-wrap gap-1.5 text-[11px]">
            {live.chunks ? (
              <span className="px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-300">
                {live.chunks} chunk{live.chunks > 1 ? 's' : ''} done
              </span>
            ) : null}
            {live.momentCount ? (
              <span className="px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300">
                {live.momentCount} moments
              </span>
            ) : null}
            {liveClips.length ? (
              <span className="px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 inline-flex items-center gap-1">
                <Sparkles size={10} /> {liveClips.length} clip{liveClips.length > 1 ? 's' : ''}
              </span>
            ) : null}
          </div>
        ) : null}

        {/* Step dots */}
        <div className="flex items-center gap-2">
          {steps.map((_, i) => (
            <div key={i} className="flex items-center gap-2">
              <motion.div
                className={`w-2 h-2 rounded-full ${
                  i <= currentStep ? 'bg-primary' : 'bg-gray-600'
                }`}
                animate={i === currentStep ? { scale: [1, 1.3, 1] } : {}}
                transition={i === currentStep ? { repeat: Infinity, duration: 1 } : {}}
              />
              {i < steps.length - 1 && (
                <div className={`w-6 h-0.5 ${i < currentStep ? 'bg-primary' : 'bg-gray-700'}`} />
              )}
            </div>
          ))}
        </div>

        <div className="w-full bg-gray-700 rounded-full h-1">
          <motion.div
            className="h-1 rounded-full bg-gradient-to-r from-primary to-accent"
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
        </div>
      </div>
    </motion.div>
  )
}

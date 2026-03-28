import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Scissors, TrendingUp, Film, Bot } from 'lucide-react'

const steps = [
  { label: 'Analyzing video', icon: Search, duration: 3000 },
  { label: 'Extracting moments', icon: Scissors, duration: 4000 },
  { label: 'Scoring engagement', icon: TrendingUp, duration: 3000 },
  { label: 'Generating clips', icon: Film, duration: 5000 },
]

export default function ProcessingIndicator() {
  const [currentStep, setCurrentStep] = useState(0)

  useEffect(() => {
    if (currentStep >= steps.length - 1) return
    const timer = setTimeout(() => {
      setCurrentStep(prev => prev + 1)
    }, steps[currentStep].duration)
    return () => clearTimeout(timer)
  }, [currentStep])

  const progress = ((currentStep + 1) / steps.length) * 100
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

      <div className="bg-gray-800/80 border border-gray-700/50 rounded-2xl px-5 py-4 space-y-3 min-w-[280px]">
        {/* Current step label */}
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

        {/* Step dots */}
        <div className="flex items-center gap-2">
          {steps.map((step, i) => (
            <div key={i} className="flex items-center gap-2">
              <motion.div
                className={`w-2 h-2 rounded-full ${
                  i < currentStep
                    ? 'bg-primary'
                    : i === currentStep
                      ? 'bg-primary'
                      : 'bg-gray-600'
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

        {/* Progress bar */}
        <div className="w-full bg-gray-700 rounded-full h-1">
          <motion.div
            className="h-1 rounded-full bg-gradient-to-r from-primary to-accent"
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
        </div>
      </div>
    </motion.div>
  )
}

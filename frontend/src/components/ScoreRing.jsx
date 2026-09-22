import { motion, useReducedMotion } from 'framer-motion'

/**
 * Circular engagement gauge, 0–10. Colour shifts with the score, but the
 * number is always rendered — colour is never the only signal.
 */
export default function ScoreRing({ score = 0, size = 38, stroke = 3 }) {
  const reduced = useReducedMotion()
  const r = (size - stroke) / 2
  const circumference = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(10, score)) / 10

  const tone =
    score >= 7.5 ? '#D4AF7A' : score >= 5 ? '#B8905A' : '#9C4152'

  return (
    <div
      className="relative grid place-items-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Engagement score ${score.toFixed(1)} out of 10`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="rgba(7,7,10,0.72)"
          stroke="rgba(255,255,255,0.10)"
          strokeWidth={stroke}
        />
        <motion.circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke={tone}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={reduced ? false : { strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - pct) }}
          transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <span className="absolute text-[10px] font-medium text-platinum nums">
        {score.toFixed(1)}
      </span>
    </div>
  )
}

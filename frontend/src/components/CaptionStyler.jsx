import { motion } from 'framer-motion'

const STYLES = [
  {
    id: 'bold_pop',
    name: 'Bold Pop',
    desc: 'White text, yellow highlight, scale-up',
    preview: 'Aa',
    colors: ['#FFFFFF', '#FFFF00'],
  },
  {
    id: 'minimal_clean',
    name: 'Minimal Clean',
    desc: 'Thin text, smooth fade',
    preview: 'Aa',
    colors: ['#FFFFFF', '#00CEC9'],
  },
  {
    id: 'karaoke_sweep',
    name: 'Karaoke Sweep',
    desc: 'Color sweep left to right',
    preview: 'Aa',
    colors: ['#808080', '#FFFFFF'],
  },
  {
    id: 'bounce_in',
    name: 'Bounce In',
    desc: 'Words bounce in from below',
    preview: 'Aa',
    colors: ['#FFFFFF', '#6C5CE7'],
  },
  {
    id: 'glow',
    name: 'Glow',
    desc: 'Glowing text with pulse',
    preview: 'Aa',
    colors: ['#FFFFFF', '#00CEC9'],
  },
]

export default function CaptionStyler({ selected, onChange }) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-muted">Caption Style</h3>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
        {STYLES.map((style) => (
          <motion.button
            key={style.id}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => onChange(style.id)}
            className={`p-3 rounded-lg border text-left transition-all ${
              selected === style.id
                ? 'border-primary bg-primary/10'
                : 'border-white/5 bg-card hover:border-white/10'
            }`}
          >
            <div
              className="text-2xl font-bold mb-2"
              style={{
                color: style.colors[0],
                textShadow: `0 0 10px ${style.colors[1]}40`,
              }}
            >
              {style.preview}
            </div>
            <p className="text-xs font-medium">{style.name}</p>
            <p className="text-[10px] text-muted mt-0.5">{style.desc}</p>
          </motion.button>
        ))}
      </div>
    </div>
  )
}

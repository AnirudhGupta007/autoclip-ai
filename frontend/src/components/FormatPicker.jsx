import { motion } from 'framer-motion'
import { Smartphone, Square, Monitor } from 'lucide-react'

const FORMATS = [
  {
    id: '9:16',
    name: 'TikTok / Reels',
    icon: Smartphone,
    desc: '1080x1920',
    aspect: 'aspect-[9/16]',
  },
  {
    id: '1:1',
    name: 'Twitter / IG',
    icon: Square,
    desc: '1080x1080',
    aspect: 'aspect-square',
  },
  {
    id: '16:9',
    name: 'YouTube',
    icon: Monitor,
    desc: '1920x1080',
    aspect: 'aspect-video',
  },
]

export default function FormatPicker({ selected, onChange, onExport, loading }) {
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-muted">Export Format</h3>
      <div className="flex gap-3">
        {FORMATS.map((fmt) => {
          const Icon = fmt.icon
          return (
            <motion.button
              key={fmt.id}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => onChange(fmt.id)}
              className={`flex-1 p-4 rounded-xl border text-center transition-all ${
                selected === fmt.id
                  ? 'border-primary bg-primary/10'
                  : 'border-white/5 bg-card hover:border-white/10'
              }`}
            >
              <Icon className="w-6 h-6 mx-auto mb-2 text-muted" />
              <p className="text-xs font-medium">{fmt.name}</p>
              <p className="text-[10px] text-muted">{fmt.desc}</p>
            </motion.button>
          )
        })}
      </div>
      {selected && (
        <button
          onClick={() => onExport(selected)}
          disabled={loading}
          className="w-full py-2.5 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/80 transition-colors disabled:opacity-50"
        >
          {loading ? 'Exporting...' : `Export as ${selected}`}
        </button>
      )}
    </div>
  )
}

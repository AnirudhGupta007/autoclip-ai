import { useState } from 'react'
import { motion } from 'framer-motion'
import { Search, Music, Play, Pause, Plus, Check } from 'lucide-react'
import { searchMusic } from '../services/api'

export default function MusicSelector({ selectedId, onSelect }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [playing, setPlaying] = useState(null)
  const [audio] = useState(typeof Audio !== 'undefined' ? new Audio() : null)

  const handleSearch = async () => {
    if (!query.trim()) return
    setLoading(true)
    try {
      const { data } = await searchMusic(query)
      setResults(data.results || [])
    } catch {
      setResults([])
    }
    setLoading(false)
  }

  const togglePlay = (track) => {
    if (!audio) return
    if (playing === track.id) {
      audio.pause()
      setPlaying(null)
    } else {
      audio.src = track.preview_url
      audio.play()
      setPlaying(track.id)
      audio.onended = () => setPlaying(null)
    }
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-muted flex items-center gap-2">
        <Music className="w-4 h-4" />
        Background Music
      </h3>

      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Search for music..."
            className="w-full pl-10 pr-4 py-2 bg-surface border border-white/10 rounded-lg text-sm focus:outline-none focus:border-primary"
          />
        </div>
        <button
          onClick={handleSearch}
          disabled={loading}
          className="px-4 py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary/80 disabled:opacity-50"
        >
          {loading ? '...' : 'Search'}
        </button>
      </div>

      {results.length > 0 && (
        <div className="space-y-1 max-h-48 overflow-y-auto">
          {results.map((track) => (
            <motion.div
              key={track.id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className={`flex items-center gap-3 p-2 rounded-lg cursor-pointer transition-colors ${
                selectedId === track.id
                  ? 'bg-primary/10 border border-primary/30'
                  : 'hover:bg-white/5'
              }`}
            >
              <button
                onClick={() => togglePlay(track)}
                className="w-8 h-8 flex items-center justify-center bg-white/5 rounded-full hover:bg-white/10"
              >
                {playing === track.id ? (
                  <Pause className="w-3.5 h-3.5" />
                ) : (
                  <Play className="w-3.5 h-3.5" />
                )}
              </button>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium truncate">{track.title}</p>
                <p className="text-[10px] text-muted">{track.duration}s - {track.photographer}</p>
              </div>
              <button
                onClick={() => onSelect(track)}
                className="p-1.5 rounded-full hover:bg-primary/20"
              >
                {selectedId === track.id ? (
                  <Check className="w-4 h-4 text-primary" />
                ) : (
                  <Plus className="w-4 h-4 text-muted" />
                )}
              </button>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  )
}

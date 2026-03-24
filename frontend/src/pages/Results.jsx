import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Download } from 'lucide-react'
import ClipGrid from '../components/ClipGrid'
import VideoPreview from '../components/VideoPreview'
import CaptionStyler from '../components/CaptionStyler'
import FormatPicker from '../components/FormatPicker'
import MusicSelector from '../components/MusicSelector'
import { getClips, getVideo, updateClip, exportClip, getDownloadUrl } from '../services/api'

export default function Results() {
  const { videoId } = useParams()
  const queryClient = useQueryClient()
  const [selectedClip, setSelectedClip] = useState(null)
  const [exportFormat, setExportFormat] = useState('9:16')
  const [showEditor, setShowEditor] = useState(false)

  const { data: video } = useQuery({
    queryKey: ['video', videoId],
    queryFn: () => getVideo(videoId).then(r => r.data),
  })

  const { data: clips = [], isLoading } = useQuery({
    queryKey: ['clips', videoId],
    queryFn: () => getClips(videoId).then(r => r.data),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => updateClip(id, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['clips', videoId] }),
  })

  const exportMutation = useMutation({
    mutationFn: ({ id, format }) => exportClip(id, format),
  })

  const handlePlay = (clip) => {
    setSelectedClip(clip)
  }

  const handleExport = (clip) => {
    setSelectedClip(clip)
    setShowEditor(true)
  }

  const handleEdit = (clip) => {
    setSelectedClip(clip)
    setShowEditor(true)
  }

  const doExport = async (format) => {
    if (!selectedClip) return
    try {
      await exportMutation.mutateAsync({ id: selectedClip.id, format })
      // Trigger download
      const url = getDownloadUrl(selectedClip.id, format)
      const a = document.createElement('a')
      a.href = url
      a.download = `${selectedClip.title || 'clip'}_${format.replace(':', 'x')}.mp4`
      a.click()
    } catch (err) {
      console.error('Export failed:', err)
    }
  }

  const handleCaptionChange = (style) => {
    if (!selectedClip) return
    updateMutation.mutate({
      id: selectedClip.id,
      data: { caption_style: style },
    })
  }

  const handleMusicSelect = (track) => {
    if (!selectedClip) return
    updateMutation.mutate({
      id: selectedClip.id,
      data: { music_id: track.id, music_url: track.download_url },
    })
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
    >
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Your Clips</h1>
          <p className="text-sm text-muted">
            {video?.filename} — {clips.length} clips generated
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-card rounded-xl border border-white/5 animate-pulse">
              <div className="aspect-video bg-surface" />
              <div className="p-4 space-y-2">
                <div className="h-4 bg-surface rounded w-3/4" />
                <div className="h-3 bg-surface rounded w-1/2" />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <ClipGrid
          clips={clips}
          onPlay={handlePlay}
          onExport={handleExport}
          onEdit={handleEdit}
        />
      )}

      {/* Player Modal */}
      <AnimatePresence>
        {selectedClip && !showEditor && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-6"
            onClick={() => setSelectedClip(null)}
          >
            <motion.div
              initial={{ scale: 0.9 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.9 }}
              className="w-full max-w-3xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex justify-between items-center mb-3">
                <h2 className="text-lg font-semibold">{selectedClip.title}</h2>
                <button onClick={() => setSelectedClip(null)}>
                  <X className="w-5 h-5 text-muted hover:text-white" />
                </button>
              </div>
              <VideoPreview
                url={`/outputs/${selectedClip.video_id}/clips/${selectedClip.id}/final.mp4`}
              />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Editor Panel */}
      <AnimatePresence>
        {showEditor && selectedClip && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-6"
            onClick={() => setShowEditor(false)}
          >
            <motion.div
              initial={{ scale: 0.9, y: 20 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.9, y: 20 }}
              className="w-full max-w-4xl max-h-[90vh] overflow-y-auto bg-surface rounded-2xl p-6"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-lg font-semibold">{selectedClip.title}</h2>
                <button onClick={() => setShowEditor(false)}>
                  <X className="w-5 h-5 text-muted hover:text-white" />
                </button>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div>
                  <VideoPreview
                    url={`/outputs/${selectedClip.video_id}/clips/${selectedClip.id}/final.mp4`}
                  />
                </div>
                <div className="space-y-6">
                  <CaptionStyler
                    selected={selectedClip.caption_style}
                    onChange={handleCaptionChange}
                  />
                  <FormatPicker
                    selected={exportFormat}
                    onChange={setExportFormat}
                    onExport={doExport}
                    loading={exportMutation.isPending}
                  />
                  <MusicSelector
                    selectedId={selectedClip.music_id}
                    onSelect={handleMusicSelect}
                  />
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

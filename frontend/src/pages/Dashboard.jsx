import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Film, Clock, Trash2, ArrowRight, Plus } from 'lucide-react'
import { getVideos, deleteVideo } from '../services/api'

export default function Dashboard() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: videos = [], isLoading } = useQuery({
    queryKey: ['videos'],
    queryFn: () => getVideos().then(r => r.data),
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => deleteVideo(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['videos'] }),
  })

  const handleDelete = (e, id) => {
    e.stopPropagation()
    if (confirm('Delete this video and all its clips?')) {
      deleteMutation.mutate(id)
    }
  }

  const handleClick = (video) => {
    if (video.status === 'completed') {
      navigate(`/results/${video.id}`)
    } else if (video.status === 'processing') {
      navigate(`/process/${video.id}`)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
    >
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-muted">{videos.length} projects</p>
        </div>
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary/80 transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Project
        </button>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-card rounded-xl border border-white/5 p-5 animate-pulse">
              <div className="h-5 bg-surface rounded w-3/4 mb-3" />
              <div className="h-4 bg-surface rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : videos.length === 0 ? (
        <div className="text-center py-20">
          <Film className="w-16 h-16 text-muted mx-auto mb-4" />
          <h2 className="text-lg font-medium mb-2">No projects yet</h2>
          <p className="text-sm text-muted mb-6">Upload a video to get started</p>
          <button
            onClick={() => navigate('/')}
            className="px-6 py-2.5 bg-primary text-white rounded-lg text-sm hover:bg-primary/80"
          >
            Upload Video
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {videos.map((video, i) => (
            <motion.div
              key={video.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              onClick={() => handleClick(video)}
              className="bg-card rounded-xl border border-white/5 p-5 cursor-pointer hover:border-primary/30 transition-all group"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-primary/10 rounded-lg flex items-center justify-center">
                    <Film className="w-5 h-5 text-primary" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold line-clamp-1">{video.filename}</h3>
                    <div className="flex items-center gap-2 mt-1">
                      <StatusBadge status={video.status} />
                      {video.clips_count > 0 && (
                        <span className="text-xs text-muted">{video.clips_count} clips</span>
                      )}
                    </div>
                  </div>
                </div>
                <button
                  onClick={(e) => handleDelete(e, video.id)}
                  className="p-1.5 text-muted hover:text-error rounded transition-colors opacity-0 group-hover:opacity-100"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>

              <div className="flex items-center justify-between mt-4 pt-3 border-t border-white/5">
                <div className="flex items-center gap-1 text-xs text-muted">
                  <Clock className="w-3 h-3" />
                  {video.duration ? `${Math.floor(video.duration / 60)}m ${Math.floor(video.duration % 60)}s` : 'Unknown'}
                </div>
                {video.resolution && (
                  <span className="text-xs text-muted">{video.resolution}</span>
                )}
                <ArrowRight className="w-4 h-4 text-muted group-hover:text-primary transition-colors" />
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </motion.div>
  )
}

function StatusBadge({ status }) {
  const styles = {
    uploaded: 'bg-white/10 text-muted',
    processing: 'bg-warning/10 text-warning',
    completed: 'bg-success/10 text-success',
    failed: 'bg-error/10 text-error',
  }

  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${styles[status] || styles.uploaded}`}>
      {status}
    </span>
  )
}

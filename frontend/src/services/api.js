import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 300000, // 5 min for large uploads
})

// Videos
export const uploadVideo = (file, onProgress) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/videos/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    },
  })
}

export const getVideos = () => api.get('/videos')
export const getVideo = (id) => api.get(`/videos/${id}`)
export const deleteVideo = (id) => api.delete(`/videos/${id}`)

// Clips
export const getClips = (videoId) => api.get('/clips', { params: { video_id: videoId } })
export const getClip = (id) => api.get(`/clips/${id}`)
export const updateClip = (id, data) => api.put(`/clips/${id}`, data)
export const exportClip = (id, format) => api.post(`/clips/${id}/export`, { format })
export const getDownloadUrl = (id, format) => `/api/clips/${id}/download/${format}`

// Music
export const searchMusic = (q, mood) => api.get('/music/search', { params: { q, mood } })

// Chat
export const sendChatMessage = (message, videoId) =>
  api.post('/chat/message', { message, video_id: videoId })

export const getAnalysisStatus = (videoId) =>
  api.get(`/chat/analysis/${videoId}`)

// Server-sent events: live pipeline progress (Phase 3)
export const openPipelineStream = (videoId, handlers = {}) => {
  const es = new EventSource(`/api/chat/stream/${videoId}`)
  const wrap = (h) => (e) => {
    try { h?.(JSON.parse(e.data || '{}'), e) } catch { h?.({}, e) }
  }
  if (handlers.onOpen) es.addEventListener('open', wrap(handlers.onOpen))
  if (handlers.onChunk) es.addEventListener('chunk_done', wrap(handlers.onChunk))
  if (handlers.onMoments) es.addEventListener('moments', wrap(handlers.onMoments))
  if (handlers.onClipReady) es.addEventListener('clip_ready', wrap(handlers.onClipReady))
  if (handlers.onDone) es.addEventListener('done', (e) => {
    try { handlers.onDone(JSON.parse(e.data || '{}')) } catch { handlers.onDone({}) }
    es.close()
  })
  if (handlers.onError) es.onerror = handlers.onError
  return es
}

// Semantic moment search (Phase 2.5)
export const searchMoments = (query, { videoId, limit = 10 } = {}) =>
  api.post('/search', { query, video_id: videoId, limit })

export default api

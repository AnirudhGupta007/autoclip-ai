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

// Pipeline
export const getPipelineStatus = (videoId) => api.get(`/pipeline/status/${videoId}`)

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

export default api

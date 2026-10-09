import axios from 'axios'

// Per-request timeouts: uploads can be large; a chat turn no longer waits on
// video analysis (that runs as a background job), so it can fail fast.
export const UPLOAD_TIMEOUT_MS = 30 * 60 * 1000
export const CHAT_TIMEOUT_MS = 150 * 1000
const DEFAULT_TIMEOUT_MS = 30 * 1000

const api = axios.create({
  baseURL: '/api',
  timeout: DEFAULT_TIMEOUT_MS,
  // Session lives in an httpOnly cookie set by /api/auth/*. Same-origin in
  // production (nginx), so this only matters for cross-origin dev setups.
  withCredentials: true,
})

// Where to send the user to sign in, remembering where they were.
export const loginPath = (next) => {
  const target = next ?? `${window.location.pathname}${window.location.search}`
  return target && target !== '/' && !target.startsWith('/login')
    ? `/login?next=${encodeURIComponent(target)}`
    : '/login'
}

// Any 401 outside /auth/* means the session expired or was revoked: go to
// the login page. (/auth/me 401s are handled by AuthContext — that's just
// "not signed in yet".)
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    const url = err.config?.url || ''
    if (status === 401 && !url.startsWith('/auth/') && !window.location.pathname.startsWith('/login')) {
      window.location.assign(loginPath())
    }
    return Promise.reject(err)
  },
)

// Auth
export const getMe = () => api.get('/auth/me')
export const login = (email, password) => api.post('/auth/login', { email, password })
export const signup = (email, password) => api.post('/auth/signup', { email, password })
export const loginDemo = () => api.post('/auth/demo')
export const logout = () => api.post('/auth/logout')

// Videos
export const uploadVideo = (file, onProgress) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/videos/upload', formData, {
    timeout: UPLOAD_TIMEOUT_MS,
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
export const updateClip = (id, data) => api.put(`/clips/${id}`, data, { timeout: CHAT_TIMEOUT_MS })
export const exportClip = (id, format) =>
  api.post(`/clips/${id}/export`, { format }, { timeout: CHAT_TIMEOUT_MS })
export const getDownloadUrl = (id, format) => `/api/clips/${id}/download/${format}`

// Music
export const searchMusic = (q, mood) => api.get('/music/search', { params: { q, mood } })

// Chat — the conversation thread is scoped server-side to the signed-in
// user + video, so no client id is sent any more.
export const sendChatMessage = (message, videoId) =>
  api.post('/chat/message', { message, video_id: videoId }, { timeout: CHAT_TIMEOUT_MS })

export const getQuota = () => api.get('/chat/quota')

export const getAnalysisStatus = (videoId) =>
  api.get(`/chat/analysis/${videoId}`)

// Server-sent events: live pipeline progress. Event names match
// backend services/events.py. The stream stays open until close() — the
// browser auto-reconnects on network errors and the server re-sends a
// `status` snapshot on every (re)connect.
const SSE_EVENTS = {
  status: 'onStatus',
  analysis_started: 'onAnalysisStarted',
  analysis_progress: 'onAnalysisProgress',
  analysis_done: 'onAnalysisDone',
  analysis_failed: 'onAnalysisFailed',
  chunk_done: 'onChunk',
  moments: 'onMoments',
  clip_ready: 'onClipReady',
  clips_done: 'onClipsDone',
}

export const openPipelineStream = (videoId, handlers = {}) => {
  // Same-origin, so the session cookie is sent; withCredentials covers dev proxies.
  const es = new EventSource(`/api/chat/stream/${videoId}`, { withCredentials: true })
  Object.entries(SSE_EVENTS).forEach(([event, key]) => {
    const h = handlers[key]
    if (!h) return
    es.addEventListener(event, (e) => {
      let data = {}
      try { data = JSON.parse(e.data || '{}') } catch { /* keep {} */ }
      h(data, e)
    })
  })
  if (handlers.onError) es.onerror = handlers.onError
  return es
}

// Semantic moment search (Phase 2.5)
export const searchMoments = (query, { videoId, limit = 10 } = {}) =>
  api.post('/search', { query, video_id: videoId, limit })

export default api

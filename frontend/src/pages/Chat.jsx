import { useState, useRef, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Send, Upload, Video, Download, Loader2, Bot, User, Sparkles } from 'lucide-react'
import { uploadVideo } from '../services/api'
import api from '../services/api'
import ClipCard from '../components/ClipCard'

function ChatMessage({ msg, onDownload }) {
  const isBot = msg.role === 'assistant'

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex gap-3 ${isBot ? '' : 'flex-row-reverse'}`}
    >
      <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
        isBot ? 'bg-purple-600' : 'bg-gray-600'
      }`}>
        {isBot ? <Bot size={16} /> : <User size={16} />}
      </div>

      <div className={`max-w-[80%] ${isBot ? '' : 'text-right'}`}>
        <div className={`rounded-2xl px-4 py-3 ${
          isBot
            ? 'bg-gray-800/80 border border-gray-700/50'
            : 'bg-purple-600/30 border border-purple-500/30'
        }`}>
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.text}</p>
        </div>

        {/* Render clips if present */}
        {msg.clips && msg.clips.length > 0 && (
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
            {msg.clips.map((clip, i) => (
              <ClipPreview key={clip.id || i} clip={clip} index={i + 1} onDownload={onDownload} />
            ))}
          </div>
        )}

        {msg.moment_count > 0 && !msg.clips && (
          <div className="mt-2 text-xs text-gray-400">
            {msg.moment_count} moments detected across video
          </div>
        )}
      </div>
    </motion.div>
  )
}

function ClipPreview({ clip, index, onDownload }) {
  const [showVideo, setShowVideo] = useState(false)

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="bg-gray-800/60 rounded-xl border border-gray-700/50 overflow-hidden"
    >
      {/* Thumbnail / Video */}
      <div
        className="relative aspect-video bg-gray-900 cursor-pointer group"
        onClick={() => setShowVideo(!showVideo)}
      >
        {showVideo && clip.file_url ? (
          <video
            src={clip.file_url}
            controls
            autoPlay
            className="w-full h-full object-contain"
          />
        ) : clip.thumbnail_url ? (
          <>
            <img
              src={clip.thumbnail_url}
              alt={clip.title}
              className="w-full h-full object-cover"
            />
            <div className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 group-hover:opacity-100 transition-opacity">
              <div className="w-12 h-12 rounded-full bg-white/20 backdrop-blur flex items-center justify-center">
                <Video size={20} />
              </div>
            </div>
          </>
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-500">
            <Video size={32} />
          </div>
        )}

        {/* Duration badge */}
        <span className="absolute bottom-2 right-2 bg-black/70 text-xs px-2 py-0.5 rounded">
          {clip.duration?.toFixed(0)}s
        </span>

        {/* Index badge */}
        <span className="absolute top-2 left-2 bg-purple-600 text-xs px-2 py-0.5 rounded font-bold">
          #{index}
        </span>
      </div>

      {/* Info */}
      <div className="p-3">
        <h4 className="text-sm font-medium truncate">{clip.title || `Clip ${index}`}</h4>
        <div className="flex items-center justify-between mt-2">
          <div className="flex gap-1">
            {clip.style_tags?.slice(0, 2).map(tag => (
              <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded bg-purple-600/20 text-purple-300">
                {tag}
              </span>
            ))}
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-600/20 text-cyan-300">
              {clip.frame || '9:16'}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-yellow-400 font-medium">
              {clip.overall_score?.toFixed(1)}/10
            </span>
            {clip.file_url && (
              <a
                href={clip.file_url}
                download
                className="text-gray-400 hover:text-white transition-colors"
                onClick={e => e.stopPropagation()}
              >
                <Download size={14} />
              </a>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  )
}

function UploadZone({ onUpload, uploading, uploadProgress }) {
  const fileRef = useRef()

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    const file = e.dataTransfer?.files?.[0]
    if (file) onUpload(file)
  }, [onUpload])

  const handleDragOver = useCallback((e) => {
    e.preventDefault()
  }, [])

  return (
    <div
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onClick={() => !uploading && fileRef.current?.click()}
      className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
        uploading
          ? 'border-purple-500/50 bg-purple-500/5'
          : 'border-gray-600 hover:border-purple-500/50 hover:bg-purple-500/5'
      }`}
    >
      <input
        ref={fileRef}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={e => e.target.files?.[0] && onUpload(e.target.files[0])}
      />

      {uploading ? (
        <div className="space-y-2">
          <Loader2 className="animate-spin mx-auto text-purple-400" size={24} />
          <p className="text-sm text-gray-400">Uploading... {uploadProgress}%</p>
          <div className="w-full bg-gray-700 rounded-full h-1.5">
            <div
              className="bg-purple-500 h-1.5 rounded-full transition-all"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
        </div>
      ) : (
        <div className="space-y-1">
          <Upload className="mx-auto text-gray-400" size={24} />
          <p className="text-sm text-gray-400">Drop a video or click to upload</p>
          <p className="text-xs text-gray-500">MP4, MOV, AVI, MKV, WebM (max 500MB)</p>
        </div>
      )}
    </div>
  )
}

export default function Chat() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: "Hey! I'm AutoClip AI. Upload a video and tell me what clips you want.\n\nFor example: \"Give me 4 funny TikTok clips under 30 seconds\"",
    }
  ])
  const [input, setInput] = useState('')
  const [videoId, setVideoId] = useState(null)
  const [videoName, setVideoName] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [sending, setSending] = useState(false)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleUpload = async (file) => {
    setUploading(true)
    setUploadProgress(0)

    try {
      const res = await uploadVideo(file, setUploadProgress)
      const video = res.data
      setVideoId(video.id)
      setVideoName(file.name)

      setMessages(prev => [
        ...prev,
        { role: 'user', text: `Uploaded: ${file.name}` },
        {
          role: 'assistant',
          text: `Got it — ${file.name} (${video.duration ? Math.round(video.duration / 60) + ' min' : 'processing'}, ${video.resolution || 'detecting'}). What kind of clips do you want?`,
        }
      ])
    } catch (err) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', text: `Upload failed: ${err.response?.data?.detail || err.message}. Try again.` }
      ])
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || sending) return

    setInput('')
    setMessages(prev => [...prev, { role: 'user', text }])
    setSending(true)

    try {
      const res = await api.post('/chat/message', {
        message: text,
        video_id: videoId,
      })

      const data = res.data
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          text: data.response,
          clips: data.clips,
          intent: data.intent,
          moment_count: data.moment_count,
        }
      ])
    } catch (err) {
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          text: `Something went wrong: ${err.response?.data?.detail || err.message}. Try again.`,
        }
      ])
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-screen bg-[#0a0a0a]">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4 flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-purple-600 to-cyan-500 flex items-center justify-center">
          <Sparkles size={18} />
        </div>
        <div>
          <h1 className="text-lg font-semibold">AutoClip AI</h1>
          <p className="text-xs text-gray-400">
            {videoName ? `Working on: ${videoName}` : 'Multimodal video clipping'}
          </p>
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {/* Upload zone if no video */}
        {!videoId && (
          <div className="max-w-lg mx-auto mt-8">
            <UploadZone
              onUpload={handleUpload}
              uploading={uploading}
              uploadProgress={uploadProgress}
            />
          </div>
        )}

        <AnimatePresence>
          {messages.map((msg, i) => (
            <ChatMessage key={i} msg={msg} />
          ))}
        </AnimatePresence>

        {sending && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex gap-3"
          >
            <div className="w-8 h-8 rounded-full bg-purple-600 flex items-center justify-center">
              <Bot size={16} />
            </div>
            <div className="bg-gray-800/80 border border-gray-700/50 rounded-2xl px-4 py-3">
              <div className="flex gap-1.5">
                <span className="w-2 h-2 rounded-full bg-purple-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 rounded-full bg-purple-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 rounded-full bg-purple-400 animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input bar */}
      <div className="border-t border-gray-800 px-6 py-4">
        <div className="max-w-3xl mx-auto flex gap-3">
          {/* Upload button (small, if video already uploaded) */}
          {videoId && (
            <label className="w-10 h-10 rounded-lg bg-gray-800 hover:bg-gray-700 flex items-center justify-center cursor-pointer transition-colors shrink-0">
              <Upload size={18} className="text-gray-400" />
              <input
                type="file"
                accept="video/*"
                className="hidden"
                onChange={e => e.target.files?.[0] && handleUpload(e.target.files[0])}
              />
            </label>
          )}

          <div className="flex-1 flex items-center bg-gray-800/80 border border-gray-700/50 rounded-xl px-4 focus-within:border-purple-500/50 transition-colors">
            <input
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={videoId ? 'Ask for clips... e.g. "4 funny TikToks under 30s"' : 'Upload a video first...'}
              disabled={!videoId || sending}
              className="flex-1 bg-transparent py-3 text-sm outline-none placeholder-gray-500 disabled:opacity-50"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              className="ml-2 p-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 disabled:opacity-30 disabled:hover:bg-purple-600 transition-colors"
            >
              {sending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Send size={16} />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

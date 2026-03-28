import { useState, useRef, useEffect } from 'react'
import { AnimatePresence } from 'framer-motion'
import { Send, Loader2, Sparkles } from 'lucide-react'
import { uploadVideo, sendChatMessage } from '../services/api'
import HeroSection from '../components/HeroSection'
import VideoBar from '../components/VideoBar'
import ChatMessage from '../components/ChatMessage'
import ProcessingIndicator from '../components/ProcessingIndicator'
import SuggestedPrompts from '../components/SuggestedPrompts'

export default function Chat() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [videoId, setVideoId] = useState(null)
  const [videoName, setVideoName] = useState(null)
  const [videoDuration, setVideoDuration] = useState(null)
  const [videoResolution, setVideoResolution] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [sending, setSending] = useState(false)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  const handleUpload = async (file) => {
    setUploading(true)
    setUploadProgress(0)

    try {
      const res = await uploadVideo(file, setUploadProgress)
      const video = res.data
      setVideoId(video.id)
      setVideoName(file.name)
      setVideoDuration(video.duration)
      setVideoResolution(video.resolution)

      setMessages([
        {
          role: 'assistant',
          text: `Got it — **${file.name}** (${video.duration ? Math.round(video.duration / 60) + ' min' : 'processing'}, ${video.resolution || 'detecting'}). What kind of clips do you want?\n\nTry something like "Give me 4 funny TikTok clips under 30 seconds"`,
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

  const handleSend = async (text) => {
    text = (text || input).trim()
    if (!text || sending) return

    setInput('')
    setMessages(prev => [...prev, { role: 'user', text }])
    setSending(true)

    try {
      const res = await sendChatMessage(text, videoId)
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

  const handlePromptSelect = (prompt) => {
    setInput(prompt)
    setTimeout(() => handleSend(prompt), 50)
  }

  return (
    <div className="flex flex-col h-screen bg-bg">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4 flex items-center gap-3 shrink-0">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-purple-600 to-cyan-500 flex items-center justify-center">
          <Sparkles size={18} />
        </div>
        <div>
          <h1 className="text-lg font-semibold">AutoClip AI</h1>
          <p className="text-xs text-gray-400">Multimodal video clipping</p>
        </div>
      </header>

      {/* Video context bar */}
      {videoId && (
        <VideoBar
          videoName={videoName}
          videoDuration={videoDuration}
          videoResolution={videoResolution}
          onNewUpload={handleUpload}
        />
      )}

      {/* Main content */}
      {!videoId ? (
        <HeroSection
          onUpload={handleUpload}
          uploading={uploading}
          uploadProgress={uploadProgress}
        />
      ) : (
        <>
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
            <AnimatePresence>
              {messages.map((msg, i) => (
                <ChatMessage key={i} msg={msg} />
              ))}
            </AnimatePresence>

            {sending && <ProcessingIndicator />}

            <div ref={messagesEndRef} />
          </div>

          {/* Input bar */}
          <div className="border-t border-gray-800 px-6 py-3 shrink-0">
            <div className="max-w-3xl mx-auto">
              <SuggestedPrompts
                onSelect={handlePromptSelect}
                visible={!sending && messages.length < 3}
              />

              <div className="flex items-center bg-gray-800/80 border border-gray-700/50 rounded-xl px-4 focus-within:border-purple-500/50 transition-colors">
                <input
                  ref={inputRef}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder='Ask for clips... e.g. "4 funny TikToks under 30s"'
                  disabled={sending}
                  className="flex-1 bg-transparent py-3 text-sm outline-none placeholder-gray-500 disabled:opacity-50"
                />
                <button
                  onClick={() => handleSend()}
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
        </>
      )}
    </div>
  )
}

import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { Send, Loader2, Scissors, ArrowLeft, Github } from 'lucide-react'
import { uploadVideo, sendChatMessage, openPipelineStream, getQuota } from '../services/api'

const REPO_URL = 'https://github.com/AnirudhGupta007/autoclip-ai'
import HeroSection from '../components/HeroSection'
import VideoBar from '../components/VideoBar'
import ChatMessage from '../components/ChatMessage'
import ProcessingIndicator from '../components/ProcessingIndicator'
import SuggestedPrompts from '../components/SuggestedPrompts'

/** Human-readable length: seconds under a minute, hours for long films. */
function fmtLength(seconds) {
  if (!seconds) return 'reading duration'
  if (seconds < 60) return `${Math.round(seconds)} seconds`
  if (seconds < 3600) return `${Math.round(seconds / 60)} minutes`
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return m ? `${h}h ${m}m` : `${h}h`
}

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
  const [liveProgress, setLiveProgress] = useState(null)
  const [liveClips, setLiveClips] = useState([])
  const [quota, setQuota] = useState(null) // { limit, remaining }

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const streamRef = useRef(null)

  useEffect(() => {
    getQuota().then((res) => setQuota(res.data)).catch(() => {})
  }, [])

  const outOfQueries = quota?.remaining === 0

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
          text: `${file.name} is in — ${fmtLength(video.duration)}, ${
            video.resolution || 'detecting resolution'
          }.\n\nTell me what you're after. A length, a format, a feeling — "3 funny clips under 30 seconds for TikTok" works, and so does "the part where it gets tense, square".`,
        },
      ])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: `Upload failed: ${err.response?.data?.detail || err.message}`,
        },
      ])
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  const handleSend = async (text) => {
    text = (text || input).trim()
    if (!text || sending || outOfQueries) return

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', text }])
    setSending(true)
    setLiveProgress({ chunks: 0, momentCount: 0 })
    setLiveClips([])

    if (videoId) {
      streamRef.current?.close()
      streamRef.current = openPipelineStream(videoId, {
        onChunk: (data) =>
          setLiveProgress((p) => ({
            ...(p || {}),
            chunks: (p?.chunks || 0) + 1,
            lastChunkMoments: data.moment_count,
          })),
        onMoments: (data) =>
          setLiveProgress((p) => ({
            ...(p || {}),
            momentCount: data.moments?.length || 0,
          })),
        onClipReady: (data) => setLiveClips((prev) => [...prev, data.clip]),
        onDone: () => {},
        onError: () => streamRef.current?.close(),
      })
    }

    try {
      const res = await sendChatMessage(text, videoId)
      const data = res.data
      if (data.queries_remaining != null) {
        setQuota((q) => ({ ...(q || {}), remaining: data.queries_remaining }))
      }
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: data.response,
          clips: data.clips,
          intent: data.intent,
          moment_count: data.moment_count,
        },
      ])
    } catch (err) {
      const limited = err.response?.status === 429
      if (limited) setQuota((q) => ({ ...(q || {}), remaining: 0 }))
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: limited
            ? err.response.data.detail
            : `Something went wrong: ${err.response?.data?.detail || err.message}`,
        },
      ])
    } finally {
      setSending(false)
      setLiveProgress(null)
      setLiveClips([])
      streamRef.current?.close()
      streamRef.current = null
      inputRef.current?.focus()
    }
  }

  useEffect(() => () => streamRef.current?.close(), [])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="relative flex h-dvh flex-col bg-obsidian">
      {/* Header */}
      <header className="hairline flex shrink-0 items-center gap-4 border-t-0 px-6 py-3.5">
        <Link
          to="/"
          className="grid h-8 w-8 place-items-center rounded-lg border border-white/8 text-platinum-muted transition-colors duration-300 hover:border-white/20 hover:text-platinum"
          aria-label="Back to home"
        >
          <ArrowLeft size={14} aria-hidden="true" />
        </Link>

        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg border border-gold-700/60 bg-obsidian-800">
            <Scissors size={14} className="text-gold" aria-hidden="true" />
          </span>
          <div>
            <h1 className="font-display text-base leading-none tracking-tight">
              AutoClip<span className="text-gold">.</span>
            </h1>
            <p className="mt-1 text-[10px] uppercase tracking-[0.2em] text-platinum-dim">
              Studio
            </p>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-3">
          {quota && (
            <span
              className={`rounded-full border px-3 py-1 text-xs nums ${
                outOfQueries ? 'border-oxblood-400/50 text-oxblood-400' : 'border-gold-700/50 text-gold-300'
              }`}
            >
              {quota.remaining} of {quota.limit} queries left today
            </span>
          )}
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="Source on GitHub"
            className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 text-platinum-muted transition-colors duration-300 hover:border-white/25 hover:text-platinum"
          >
            <Github size={15} aria-hidden="true" />
          </a>
        </div>
      </header>

      {videoId && (
        <VideoBar
          videoName={videoName}
          videoDuration={videoDuration}
          videoResolution={videoResolution}
          onNewUpload={handleUpload}
        />
      )}

      {!videoId ? (
        <HeroSection
          onUpload={handleUpload}
          uploading={uploading}
          uploadProgress={uploadProgress}
        />
      ) : (
        <>
          <div className="flex-1 overflow-y-auto px-6 py-6">
            <div className="mx-auto max-w-4xl space-y-6">
              <AnimatePresence initial={false}>
                {messages.map((msg, i) => (
                  <ChatMessage key={i} msg={msg} />
                ))}
              </AnimatePresence>

              {sending && (
                <ProcessingIndicator progress={liveProgress} liveClips={liveClips} />
              )}

              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Composer */}
          <div className="hairline shrink-0 px-6 py-4">
            <div className="mx-auto max-w-4xl">
              <SuggestedPrompts
                onSelect={(p) => { setInput(p); setTimeout(() => handleSend(p), 40) }}
                visible={!sending && !outOfQueries && messages.length < 3}
              />

              <div className="glass flex items-center gap-2 rounded-2xl px-4 py-1.5 transition-colors duration-300 ease-lux focus-within:border-gold-700/60">
                <label htmlFor="composer" className="sr-only">
                  Describe the clips you want
                </label>
                <input
                  id="composer"
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={
                    outOfQueries
                      ? 'Daily limit reached. Come back tomorrow for 2 more queries.'
                      : 'Ask for clips — length, format, feeling…'
                  }
                  disabled={sending || outOfQueries}
                  className="flex-1 bg-transparent py-2.5 text-sm text-platinum outline-none placeholder:text-platinum-dim disabled:opacity-50"
                />
                <button
                  type="button"
                  onClick={() => handleSend()}
                  disabled={!input.trim() || sending || outOfQueries}
                  aria-label="Send request"
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gold-sheen bg-[length:200%_auto] text-obsidian transition-all duration-500 ease-lux hover:bg-[position:80%_50%] disabled:cursor-not-allowed disabled:opacity-25"
                >
                  {sending ? (
                    <Loader2 size={15} className="animate-spin" aria-hidden="true" />
                  ) : (
                    <Send size={15} aria-hidden="true" />
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

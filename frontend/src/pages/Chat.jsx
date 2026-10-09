import { useState, useRef, useEffect, useCallback } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { Send, Loader2, Scissors, ArrowLeft, Github, Library as LibraryIcon } from 'lucide-react'
import {
  uploadVideo,
  sendChatMessage,
  openPipelineStream,
  getQuota,
  getAnalysisStatus,
  getVideo,
  getVideos,
  getClips,
} from '../services/api'
import { useAuth } from '../auth/AuthContext'
import UserMenu from '../components/UserMenu'

const REPO_URL = 'https://github.com/AnirudhGupta007/autoclip-ai'
import HeroSection from '../components/HeroSection'
import VideoBar from '../components/VideoBar'
import ChatMessage from '../components/ChatMessage'
import ProcessingIndicator from '../components/ProcessingIndicator'
import SuggestedPrompts from '../components/SuggestedPrompts'

const ANALYSIS_POLL_MS = 10000

/** Human-readable length: seconds under a minute, hours for long films. */
function fmtLength(seconds) {
  if (!seconds) return 'reading duration'
  if (seconds < 60) return `${Math.round(seconds)} seconds`
  if (seconds < 3600) return `${Math.round(seconds / 60)} minutes`
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return m ? `${h}h ${m}m` : `${h}h`
}

function errorText(err) {
  if (err.code === 'ECONNABORTED') return 'The request timed out. Please try again.'
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  return err.message || 'Unknown error'
}

export default function Chat() {
  const { user, refresh: refreshUser } = useAuth()
  const isDemo = !!user?.is_demo
  const [searchParams, setSearchParams] = useSearchParams()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [videoId, setVideoId] = useState(null)
  const [videoName, setVideoName] = useState(null)
  const [videoDuration, setVideoDuration] = useState(null)
  const [videoResolution, setVideoResolution] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadError, setUploadError] = useState(null)
  const [sending, setSending] = useState(false)
  const [liveProgress, setLiveProgress] = useState(null)
  const [liveClips, setLiveClips] = useState([])
  const [analysis, setAnalysis] = useState(null) // background analysis progress, or null
  const [quota, setQuota] = useState(null) // { limit, remaining }

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const streamRef = useRef(null)
  const sendingRef = useRef(false) // synchronous double-send guard
  const videoIdRef = useRef(null)
  const pendingRef = useRef(null) // request to resume once analysis finishes
  const analysisActiveRef = useRef(false)
  const pollRef = useRef(null)

  useEffect(() => {
    getQuota().then((res) => setQuota(res.data)).catch(() => {})
  }, [])

  const outOfQueries = quota?.remaining === 0
  const unlimited = quota && quota.limit == null

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending, analysis])

  const addAssistant = (text, extra = {}) =>
    setMessages((prev) => [...prev, { role: 'assistant', text, ...extra }])

  // ── SSE stream (one per video, open while analysing or sending) ──
  const closeStream = useCallback(() => {
    streamRef.current?.close()
    streamRef.current = null
  }, [])

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = null
  }, [])

  // Forward refs so stream/poll callbacks always call the latest handlers.
  const handlersRef = useRef({})

  const ensureStream = useCallback((vid) => {
    if (streamRef.current) return
    streamRef.current = openPipelineStream(vid, {
      onStatus: (d) => handlersRef.current.onAnalysisState?.(d),
      onAnalysisStarted: (d) =>
        analysisActiveRef.current &&
        setAnalysis((a) => ({ ...(a || {}), status: 'analyzing', eta_seconds: d.eta_seconds })),
      onAnalysisProgress: (d) =>
        analysisActiveRef.current && setAnalysis((a) => ({ ...(a || {}), ...d, status: 'analyzing' })),
      onAnalysisDone: (d) => handlersRef.current.onAnalysisState?.({ ...d, status: 'analyzed' }),
      onAnalysisFailed: (d) => handlersRef.current.onAnalysisState?.({ ...d, status: 'failed' }),
      onChunk: (data) =>
        setLiveProgress((p) => ({
          ...(p || {}),
          chunks: (p?.chunks || 0) + 1,
          lastChunkMoments: data.moment_count,
        })),
      onMoments: (data) =>
        setLiveProgress((p) => ({ ...(p || {}), momentCount: data.moments?.length || 0 })),
      onClipReady: (data) => setLiveClips((prev) => [...prev, data.clip]),
      // No onError close: EventSource reconnects by itself and the server
      // re-sends a `status` snapshot; polling below covers dead streams.
    })
  }, [])

  const beginAnalysisWatch = useCallback(
    (vid, state) => {
      analysisActiveRef.current = true
      setAnalysis({ ...(state || {}), status: 'analyzing' })
      ensureStream(vid)
      if (!pollRef.current) {
        pollRef.current = setInterval(() => {
          getAnalysisStatus(vid)
            .then((res) => handlersRef.current.onAnalysisState?.(res.data))
            .catch(() => {})
        }, ANALYSIS_POLL_MS)
      }
    },
    [ensureStream],
  )

  const endAnalysisWatch = useCallback(() => {
    analysisActiveRef.current = false
    setAnalysis(null)
    stopPolling()
    if (!sendingRef.current) closeStream()
  }, [stopPolling, closeStream])

  // ── Sending ──
  const runSend = async (text, { auto = false } = {}) => {
    if (sendingRef.current) return
    sendingRef.current = true
    setSending(true)
    setLiveProgress({ chunks: 0, momentCount: 0 })
    setLiveClips([])
    if (!auto) setMessages((prev) => [...prev, { role: 'user', text }])

    const vid = videoIdRef.current
    if (vid) ensureStream(vid)

    try {
      const res = await sendChatMessage(text, vid)
      const data = res.data
      if (data.queries_remaining != null) {
        setQuota((q) => ({ ...(q || {}), remaining: data.queries_remaining }))
      }
      addAssistant(data.response, {
        clips: data.clips,
        intent: data.intent,
        moment_count: data.moment_count,
      })
      if (data.analysis?.status === 'analyzing' && vid) {
        if (data.pending_request) pendingRef.current = text
        beginAnalysisWatch(vid, data.analysis)
      }
    } catch (err) {
      const limited = err.response?.status === 429
      if (limited) setQuota((q) => ({ ...(q || {}), remaining: 0 }))
      addAssistant(limited ? errorText(err) : `Something went wrong: ${errorText(err)}`)
    } finally {
      sendingRef.current = false
      setSending(false)
      setLiveProgress(null)
      setLiveClips([])
      if (!analysisActiveRef.current) closeStream()
      inputRef.current?.focus()
    }
  }

  // Analysis state from SSE (`status`, `analysis_done`, `analysis_failed`)
  // or from polling — whichever arrives first wins; later ones are no-ops.
  handlersRef.current.onAnalysisState = (d) => {
    if (!d || !analysisActiveRef.current) return
    if (d.status === 'analyzing') {
      setAnalysis((a) => ({ ...(a || {}), ...d }))
      return
    }
    if (d.status === 'analyzed') {
      endAnalysisWatch()
      const pending = pendingRef.current
      pendingRef.current = null
      const n = d.moment_count
      addAssistant(
        pending
          ? `Analysis finished${n != null ? ` — ${n} candidate moments` : ''}. Working on your request now.`
          : `Analysis finished${n != null ? ` — ${n} candidate moments` : ''}. What clips do you want?`,
      )
      if (pending) runSend(pending, { auto: true })
    } else if (d.status === 'failed' || d.status === 'not_found') {
      endAnalysisWatch()
      pendingRef.current = null
      addAssistant(d.message || d.error || 'Analysis failed. Send your request again to retry.')
    }
  }

  const handleUpload = async (file) => {
    if (uploading) return
    setUploading(true)
    setUploadProgress(0)
    setUploadError(null)

    try {
      const res = await uploadVideo(file, setUploadProgress)
      const video = res.data
      // New video: drop any watch on the previous one.
      endAnalysisWatch()
      pendingRef.current = null
      closeStream()
      videoIdRef.current = video.id
      setVideoId(video.id)
      setSearchParams({ video: video.id }, { replace: true })
      refreshUser()
      setVideoName(file.name)
      setVideoDuration(video.duration)
      setVideoResolution(video.resolution)

      setMessages([
        {
          role: 'assistant',
          text: `${file.name} is in — ${fmtLength(video.duration)}, ${
            video.resolution || 'detecting resolution'
          }.\n\nTell me what you're after. A length, a format, a feeling — "3 funny clips under 30 seconds for TikTok" works, and so does "the part where it gets tense, square".\n\nThe first request kicks off a one-time analysis of the whole video (roughly ${Math.max(
            1,
            Math.round((45 + 0.2 * (video.duration || 0)) / 60),
          )} min); I'll finish your request automatically when it's done.`,
        },
      ])
    } catch (err) {
      const text = `Upload failed: ${errorText(err)}`
      setUploadError(text)
      // Before the first video exists the chat isn't rendered — the banner
      // below the hero shows the error; with a video, it goes in the thread.
      if (videoIdRef.current) addAssistant(text)
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  // Re-open a video from the Library (/studio?video=<id>): restore its clips
  // and, if it is still being analysed, re-attach to the progress stream.
  const openExisting = useCallback(
    async (vid) => {
      try {
        const [vRes, cRes, aRes] = await Promise.all([
          getVideo(vid),
          getClips(vid),
          getAnalysisStatus(vid).catch(() => ({ data: {} })),
        ])
        const video = vRes.data
        endAnalysisWatch()
        pendingRef.current = null
        closeStream()
        videoIdRef.current = video.id
        setVideoId(video.id)
        setVideoName(video.filename)
        setVideoDuration(video.duration)
        setVideoResolution(video.resolution)
        const clips = cRes.data || []
        const status = aRes.data?.status || video.status
        const intro =
          status === 'analyzed'
            ? `${video.filename} — ${fmtLength(video.duration)}, analysed and ready.`
            : `${video.filename} — ${fmtLength(video.duration)}. The first request will analyse it.`
        setMessages([
          {
            role: 'assistant',
            text: clips.length
              ? `${intro}\n\nHere ${clips.length === 1 ? 'is the clip' : `are the ${clips.length} clips`} made so far. Ask for more, or for changes.`
              : `${intro}\n\nTell me what clips you want — a length, a format, a feeling.`,
            clips: clips.length ? clips : undefined,
          },
        ])
        if (status === 'analyzing') beginAnalysisWatch(video.id, aRes.data)
      } catch (err) {
        if (err.response?.status === 404) {
          setUploadError("That video isn't in your library.")
        } else {
          setUploadError(`Couldn't open the video: ${errorText(err)}`)
        }
      }
    },
    [beginAnalysisWatch, closeStream, endAnalysisWatch],
  )

  const requestedVideo = searchParams.get('video')
  const wantsNew = searchParams.get('new') === '1'
  const autoOpened = useRef(false)

  useEffect(() => {
    if (requestedVideo && requestedVideo !== videoIdRef.current) {
      openExisting(requestedVideo)
    } else if (wantsNew && videoIdRef.current) {
      endAnalysisWatch()
      closeStream()
      pendingRef.current = null
      videoIdRef.current = null
      setVideoId(null)
      setMessages([])
      setSearchParams({}, { replace: true })
    }
  }, [requestedVideo, wantsNew, openExisting, endAnalysisWatch, closeStream, setSearchParams])

  // The demo account can't upload: drop visitors straight into its first
  // analysed video instead of an upload screen they can't use.
  useEffect(() => {
    if (!isDemo || requestedVideo || autoOpened.current) return
    autoOpened.current = true
    getVideos()
      .then((res) => {
        const vids = res.data || []
        const pick = vids.find((v) => v.status === 'analyzed') || vids[0]
        if (pick) setSearchParams({ video: pick.id }, { replace: true })
      })
      .catch(() => {})
  }, [isDemo, requestedVideo, setSearchParams])

  const handleSend = (text) => {
    text = (typeof text === 'string' ? text : input).trim()
    if (!text || sendingRef.current || outOfQueries) return
    setInput('')
    runSend(text)
  }

  useEffect(
    () => () => {
      streamRef.current?.close()
      if (pollRef.current) clearInterval(pollRef.current)
    },
    [],
  )

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
          {quota && !unlimited && (
            <span
              className={`rounded-full border px-3 py-1 text-xs nums ${
                outOfQueries ? 'border-oxblood-400/50 text-oxblood-400' : 'border-gold-700/50 text-gold-300'
              }`}
            >
              {quota.remaining} of {quota.limit} queries left today
            </span>
          )}
          <Link
            to="/library"
            className="hidden items-center gap-1.5 rounded-full border border-white/10 px-3 py-1 text-xs text-platinum-muted transition-colors duration-300 hover:border-gold-700/50 hover:text-platinum sm:inline-flex"
          >
            <LibraryIcon size={12} aria-hidden="true" /> Library
          </Link>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="Source on GitHub"
            className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 text-platinum-muted transition-colors duration-300 hover:border-white/25 hover:text-platinum"
          >
            <Github size={15} aria-hidden="true" />
          </a>
          <UserMenu />
        </div>
      </header>

      {videoId && (
        <VideoBar
          videoName={videoName}
          videoDuration={videoDuration}
          videoResolution={videoResolution}
          onNewUpload={isDemo ? null : handleUpload}
        />
      )}

      {!videoId ? (
        <>
          {isDemo ? (
            <div className="flex flex-1 items-center justify-center px-6 py-14 text-center">
              <div className="max-w-md">
                <p className="mb-4 text-[11px] uppercase tracking-[0.3em] text-gold-600">Demo</p>
                <h2 className="mb-3 font-display text-display-md text-platinum">
                  Pick a film from the <span className="italic text-gold-400">library.</span>
                </h2>
                <p className="mb-8 text-sm leading-relaxed text-platinum-muted">
                  The demo account can explore pre-analysed videos and chat with the agent.
                  Create an account to upload your own.
                </p>
                <div className="flex justify-center gap-3">
                  <Link to="/library" className="rounded-full border border-gold-700/50 px-4 py-2 text-sm text-gold-300 hover:bg-gold-700/15">
                    Open library
                  </Link>
                  <Link to="/signup" className="rounded-full bg-gold-sheen bg-[length:200%_auto] px-4 py-2 text-sm font-semibold text-obsidian">
                    Sign up
                  </Link>
                </div>
              </div>
            </div>
          ) : (
            <HeroSection
              onUpload={handleUpload}
              uploading={uploading}
              uploadProgress={uploadProgress}
            />
          )}
          {uploadError && (
            <div
              role="alert"
              className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-6"
            >
              <p className="pointer-events-auto rounded-xl border border-oxblood-400/50 bg-obsidian-800/95 px-4 py-2.5 text-sm text-oxblood-400 shadow-lg">
                {uploadError}
              </p>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="flex-1 overflow-y-auto px-6 py-6">
            <div className="mx-auto max-w-4xl space-y-6">
              <AnimatePresence initial={false}>
                {messages.map((msg, i) => (
                  <ChatMessage key={i} msg={msg} />
                ))}
              </AnimatePresence>

              {analysis && !sending && <ProcessingIndicator analysis={analysis} />}
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
                onSelect={(p) => handleSend(p)}
                visible={!sending && !analysis && !outOfQueries && messages.length < 3}
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
                      ? `Daily limit reached. Come back tomorrow for ${quota?.limit ?? 'more'} more queries.`
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

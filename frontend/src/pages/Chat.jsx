import { useState, useRef, useEffect, useCallback } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Send, Loader2, PanelLeft, Library as LibraryIcon } from 'lucide-react'
import {
  uploadVideo,
  sendChatMessage,
  openPipelineStream,
  getQuota,
  getAnalysisStatus,
  getVideo,
  getVideos,
  getClips,
  listConversations,
  createConversation,
  getConversationMessages,
  renameConversation,
  deleteConversation,
} from '../services/api'
import { useAuth } from '../auth/AuthContext'
import AppHeader from '../components/AppHeader'
import ChatSidebar from '../components/ChatSidebar'
import { SPRING } from '../components/landing/primitives'
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
  const [sending, setSending] = useState(false)
  const [liveProgress, setLiveProgress] = useState(null)
  const [liveClips, setLiveClips] = useState([])
  const [analysis, setAnalysis] = useState(null) // background analysis progress, or null
  const [quota, setQuota] = useState(null) // { limit, remaining }
  const [mediaKind, setMediaKind] = useState(null) // 'video' | 'audio' | null
  const [conversations, setConversations] = useState(null) // null while loading
  const [convError, setConvError] = useState(false)
  const [conversationId, setConversationId] = useState(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [toast, setToast] = useState(null)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const streamRef = useRef(null)
  const sendingRef = useRef(false) // synchronous double-send guard
  const videoIdRef = useRef(null)
  const pendingRef = useRef(null) // request to resume once analysis finishes
  const analysisActiveRef = useRef(false)
  const pollRef = useRef(null)
  const conversationIdRef = useRef(null)

  useEffect(() => {
    getQuota().then((res) => setQuota(res.data)).catch(() => {})
  }, [])

  // Chat history. Any failure (endpoint missing, server error) degrades to an
  // empty sidebar; the chat itself keeps working without a conversation id.
  const loadConversations = useCallback(() => {
    return listConversations()
      .then((res) => {
        setConversations(Array.isArray(res.data) ? res.data : [])
        setConvError(false)
      })
      .catch(() => {
        setConversations((c) => c || [])
        setConvError(true)
      })
  }, [])

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  const selectConversation = (id) => {
    conversationIdRef.current = id
    setConversationId(id)
  }

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 6000)
    return () => clearTimeout(t)
  }, [toast])

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
    }, conversationIdRef.current)
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

    // First message of a new chat: create its conversation. If that fails the
    // turn still goes through, just without history.
    let cid = conversationIdRef.current
    if (!cid) {
      try {
        const res = await createConversation(vid)
        if (res.data?.id) {
          cid = res.data.id
          selectConversation(cid)
          setConversations((list) => [res.data, ...(list || []).filter((c) => c.id !== cid)])
          setSearchParams({ c: cid }, { replace: true })
        }
      } catch {
        /* history unavailable — carry on */
      }
    }

    if (vid) ensureStream(vid)

    try {
      const res = await sendChatMessage(text, vid, cid)
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
      if (cid) loadConversations() // title + order come from the server
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

  // Before the first video exists the chat isn't rendered, so the toast shows
  // the error; with a video, it goes in the thread.
  const reportUploadError = (text) => {
    if (videoIdRef.current) addAssistant(text)
    else setToast(text)
  }

  const handleUpload = async (file) => {
    if (uploading) return
    setUploading(true)
    setUploadProgress(0)
    setToast(null)

    try {
      const res = await uploadVideo(file, setUploadProgress)
      const video = res.data
      // New video: drop any watch on the previous one.
      endAnalysisWatch()
      pendingRef.current = null
      closeStream()
      videoIdRef.current = video.id
      selectConversation(null) // a new video starts a new chat
      setVideoId(video.id)
      setSearchParams({ video: video.id }, { replace: true })
      refreshUser()
      setMediaKind(video.media_kind || (file.type?.startsWith('audio/') ? 'audio' : 'video'))
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
      reportUploadError(`Upload failed: ${errorText(err)}`)
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  // Re-open a video from the Library (/studio?video=<id>): restore its clips
  // and, if it is still being analysed, re-attach to the progress stream.
  const openExisting = useCallback(
    async (vid, { preset = null } = {}) => {
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
        setMediaKind(video.media_kind || null)
        if (preset) {
          setMessages(preset)
          if ((aRes.data?.status || video.status) === 'analyzing') beginAnalysisWatch(video.id, aRes.data)
          return
        }
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
        if (preset) {
          // The chat outlives its source (deleted or archived): show it anyway.
          videoIdRef.current = null
          setVideoId(null)
          setMessages(preset)
          return
        }
        setToast(
          err.response?.status === 404
            ? "That video isn't in your library."
            : `Couldn't open the video: ${errorText(err)}`,
        )
      }
    },
    [beginAnalysisWatch, closeStream, endAnalysisWatch],
  )

  const resetVideo = useCallback(() => {
    endAnalysisWatch()
    closeStream()
    pendingRef.current = null
    videoIdRef.current = null
    setVideoId(null)
    setVideoName(null)
    setMediaKind(null)
  }, [endAnalysisWatch, closeStream])

  // Open a past chat: its messages, plus its video if it still exists.
  const openConversation = useCallback(
    async (conv) => {
      selectConversation(conv.id)
      setSearchParams({ c: conv.id }, { replace: true })
      let preset
      try {
        const res = await getConversationMessages(conv.id)
        const rows = Array.isArray(res.data) ? res.data : []
        preset = rows.map((m) => ({
          role: m.role === 'user' ? 'user' : 'assistant',
          text: m.content || '',
          clips: m.clips?.length ? m.clips : undefined,
        }))
      } catch {
        preset = [{ role: 'assistant', text: "Couldn't load this chat's messages. Try again in a moment." }]
      }
      if (conversationIdRef.current !== conv.id) return // user moved on
      if (!preset.length) preset = [{ role: 'assistant', text: 'This chat is empty. Ask for some clips.' }]
      if (conv.video_id) {
        if (conv.video_id !== videoIdRef.current) {
          await openExisting(conv.video_id, { preset })
        } else {
          setMessages(preset)
        }
      } else {
        resetVideo()
        setMessages(preset)
      }
    },
    [openExisting, resetVideo, setSearchParams],
  )

  const startNewChat = () => {
    selectConversation(null)
    const vid = videoIdRef.current
    if (vid) {
      // Same video, fresh thread.
      openExisting(vid)
      setSearchParams({ video: vid }, { replace: true })
    } else {
      resetVideo()
      setMessages([])
      setSearchParams({}, { replace: true })
    }
    inputRef.current?.focus()
  }

  const handleRename = async (id, title) => {
    try {
      await renameConversation(id, title)
      setConversations((list) => (list || []).map((c) => (c.id === id ? { ...c, title } : c)))
    } catch (err) {
      setToast(`Couldn't rename the chat: ${errorText(err)}`)
    }
  }

  const handleDelete = async (id) => {
    try {
      await deleteConversation(id)
      setConversations((list) => (list || []).filter((c) => c.id !== id))
      if (conversationIdRef.current === id) startNewChat()
    } catch (err) {
      setToast(`Couldn't delete the chat: ${errorText(err)}`)
    }
  }

  const requestedVideo = searchParams.get('video')
  const requestedConv = searchParams.get('c')
  const wantsNew = searchParams.get('new') === '1'
  const autoOpened = useRef(false)

  useEffect(() => {
    if (requestedConv) {
      if (requestedConv === conversationIdRef.current || conversations === null) return
      const conv = conversations.find((c) => c.id === requestedConv)
      if (conv) openConversation(conv)
      else setSearchParams({}, { replace: true }) // stale or someone else's link
    } else if (requestedVideo && requestedVideo !== videoIdRef.current) {
      selectConversation(null)
      openExisting(requestedVideo)
    } else if (wantsNew) {
      selectConversation(null)
      resetVideo()
      setMessages([])
      setSearchParams({}, { replace: true })
    }
  }, [requestedConv, requestedVideo, wantsNew, conversations, openConversation, openExisting, resetVideo, setSearchParams])

  // The demo account can't upload: drop visitors straight into its first
  // analysed video instead of an upload screen they can't use.
  useEffect(() => {
    if (!isDemo || requestedVideo || requestedConv || autoOpened.current) return
    autoOpened.current = true
    getVideos()
      .then((res) => {
        const vids = res.data || []
        const pick = vids.find((v) => v.status === 'analyzed') || vids[0]
        if (pick) setSearchParams({ video: pick.id }, { replace: true })
      })
      .catch(() => {})
  }, [isDemo, requestedVideo, requestedConv, setSearchParams])

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

  const showThread = !!videoId || messages.length > 0

  const quotaChip =
    quota && !unlimited ? (
      <span
        className={`chip nums ${outOfQueries ? 'border-platinum/40 text-platinum' : ''}`}
        title={`${quota.remaining} of ${quota.limit} queries left today`}
      >
        <span className={outOfQueries ? '' : 'text-gold'}>{quota.remaining}</span>
        <span className="sm:hidden">/{quota.limit}</span>
        <span className="hidden sm:inline">of {quota.limit} left today</span>
      </span>
    ) : null

  return (
    <div className="relative flex h-dvh flex-col bg-obsidian">
      <AppHeader
        leading={
          <button
            type="button"
            className="icon-btn lg:hidden"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open chat history"
          >
            <PanelLeft size={17} aria-hidden="true" />
          </button>
        }
        trailing={quotaChip}
      />

      <div className="flex min-h-0 flex-1">
        <ChatSidebar
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          conversations={conversations}
          error={convError}
          activeId={conversationId}
          readOnly={isDemo}
          onSelect={(c) => c.id !== conversationIdRef.current && openConversation(c)}
          onNew={startNewChat}
          onRename={handleRename}
          onDelete={handleDelete}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          {videoId && (
            <VideoBar
              videoName={videoName}
              videoDuration={videoDuration}
              videoResolution={videoResolution}
              mediaKind={mediaKind}
              onNewUpload={isDemo ? null : handleUpload}
            />
          )}

          {!showThread ? (
            isDemo ? (
              <div className="flex flex-1 items-center justify-center px-6 py-14 text-center">
                <div className="max-w-md">
                  <p className="eyebrow mb-4">Demo</p>
                  <h2 className="mb-3 font-display text-display-md text-platinum">
                    Pick a video from the <span className="italic text-gold">library.</span>
                  </h2>
                  <p className="mb-8 text-sm leading-relaxed text-platinum-muted">
                    The demo account can explore pre-analysed videos and chat with the agent.
                    Create an account to upload your own.
                  </p>
                  <div className="flex justify-center gap-3">
                    <Link to="/library" className="btn btn-secondary">
                      <LibraryIcon size={14} aria-hidden="true" /> Open library
                    </Link>
                    <Link to="/signup" className="btn btn-primary">
                      Sign up
                    </Link>
                  </div>
                </div>
              </div>
            ) : (
              <HeroSection
                onUpload={handleUpload}
                onReject={setToast}
                uploading={uploading}
                uploadProgress={uploadProgress}
              />
            )
          ) : (
            <>
              <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
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
              <div className="shrink-0 px-4 pb-4 pt-2 sm:px-6">
                <div className="mx-auto max-w-4xl">
                  <SuggestedPrompts
                    onSelect={(p) => handleSend(p)}
                    visible={!sending && !analysis && !outOfQueries && messages.length < 3}
                  />

                  <div className="surface-raised flex items-center gap-2 rounded-3xl py-1.5 pl-4 pr-1.5 transition-colors duration-200 ease-lux focus-within:border-white/25">
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
                      className="min-w-0 flex-1 bg-transparent py-2.5 text-sm text-platinum outline-none placeholder:text-platinum-dim disabled:opacity-50"
                    />
                    <button
                      type="button"
                      onClick={() => handleSend()}
                      disabled={!input.trim() || sending || outOfQueries}
                      aria-label="Send request"
                      className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-gold text-obsidian transition-[background-color,transform,opacity] duration-200 ease-lux hover:bg-gold-300 active:scale-95 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-platinum-dim"
                    >
                      {sending ? (
                        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                      ) : (
                        <Send size={16} aria-hidden="true" />
                      )}
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <AnimatePresence>
        {toast && (
          <motion.div
            role="alert"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12 }}
            transition={SPRING}
            className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-6"
          >
            <p className="glass pointer-events-auto rounded-2xl px-4 py-3 text-sm text-platinum shadow-elev-3">
              {toast}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

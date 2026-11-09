import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Video, Mic, Trash2, Loader2, Plus, Play, CircleAlert, Archive } from 'lucide-react'
import { getVideos, deleteVideo, getUsage } from '../services/api'
import { useAuth } from '../auth/AuthContext'
import AppHeader from '../components/AppHeader'
import { apiError } from '../components/AuthShell'
import { SPRING_SOFT } from '../components/landing/primitives'

const STATUS = {
  analyzed: { label: 'Ready', cls: 'border-gold/50 text-gold' },
  analyzing: { label: 'Analysing', cls: 'border-white/15 text-platinum-muted' },
  uploaded: { label: 'Not analysed', cls: 'border-white/10 text-platinum-dim' },
  failed: { label: 'Failed', cls: 'border-platinum/40 text-platinum' },
}

function fmtDuration(s) {
  if (!s) return '—'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    : `${m}:${String(sec).padStart(2, '0')}`
}

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
  } catch {
    return ''
  }
}

export default function Library() {
  const { user, refresh } = useAuth()
  const navigate = useNavigate()
  const [videos, setVideos] = useState(null)
  const [error, setError] = useState(null)
  const [confirming, setConfirming] = useState(null) // video id
  const [deleting, setDeleting] = useState(null)
  const [expiry, setExpiry] = useState({}) // video_id -> usage item (retention dates)

  const load = useCallback(() => {
    getVideos()
      .then((res) => setVideos(res.data))
      .catch((err) => setError(apiError(err, 'Could not load your library.')))
    // Retention dates are optional: no usage endpoint, no dates.
    getUsage()
      .then((res) => {
        const map = {}
        for (const it of res.data?.items || []) map[it.video_id] = it
        setExpiry(map)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const remove = async (id) => {
    setDeleting(id)
    setError(null)
    try {
      await deleteVideo(id)
      setVideos((vs) => vs.filter((v) => v.id !== id))
      refresh()
    } catch (err) {
      setError(apiError(err, 'Could not delete the video.'))
    } finally {
      setDeleting(null)
      setConfirming(null)
    }
  }

  const canDelete = user && !user.is_demo
  const cap = user?.max_videos

  return (
    <div className="flex min-h-screen flex-col bg-obsidian text-platinum">
      <AppHeader />

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-10 sm:px-6">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow mb-2">{user?.is_demo ? 'Demo library' : 'Your library'}</p>
            <h1 className="font-display text-display-md">
              Every <span className="italic text-gold">episode</span>, in one place.
            </h1>
            {cap != null && videos && (
              <p className="mt-2 text-xs text-platinum-dim nums">
                {videos.length} of {cap} uploads stored ·{' '}
                <Link to="/docs#storage" className="underline decoration-white/25 underline-offset-2 hover:text-platinum">
                  storage rules
                </Link>
              </p>
            )}
          </div>
          {!user?.is_demo && (
            <Link to="/studio?new=1" className="btn btn-primary">
              <Plus size={14} aria-hidden="true" /> New upload
            </Link>
          )}
        </div>

        {error && (
          <p role="alert" className="notice mb-6">
            <CircleAlert size={15} className="mt-0.5 shrink-0 text-platinum-muted" aria-hidden="true" />
            {error}
          </p>
        )}

        {videos === null && !error && (
          <ul className="grid gap-4 sm:grid-cols-2" aria-label="Loading">
            {[0, 1].map((i) => (
              <li key={i} className="surface h-[132px] animate-pulse rounded-2xl" />
            ))}
          </ul>
        )}

        {videos?.length === 0 && (
          <div className="surface rounded-3xl px-8 py-16 text-center">
            <Mic size={22} className="mx-auto mb-4 text-platinum-dim" aria-hidden="true" />
            <p className="font-display text-xl">Nothing here yet</p>
            <p className="mt-2 text-sm text-platinum-muted">
              {user?.is_demo
                ? 'The demo library is empty right now.'
                : 'Upload a podcast or video in the studio to get started.'}
            </p>
            {!user?.is_demo && (
              <Link to="/studio?new=1" className="btn btn-secondary mt-6">
                Open the studio
              </Link>
            )}
          </div>
        )}

        <ul className="grid gap-4 sm:grid-cols-2">
          <AnimatePresence initial={false}>
            {videos?.map((v, i) => {
              const st = STATUS[v.status] || STATUS.uploaded
              const ex = expiry[v.id] || {}
              const kind = v.media_kind || ex.media_kind
              const Icon = kind === 'audio' ? Mic : Video
              const archived = v.archived ?? ex.archived
              const sourceExp = v.source_expires_at || ex.source_expires_at
              const clipsExp = v.clips_expire_at || ex.clips_expire_at
              return (
                <motion.li
                  key={v.id}
                  layout
                  initial={{ opacity: 0, y: 14 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.97 }}
                  transition={{ ...SPRING_SOFT, delay: i * 0.04 }}
                  className="surface group flex flex-col rounded-2xl p-5 transition-colors duration-300 ease-lux hover:border-white/20"
                >
                  <div className="flex items-start gap-3">
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/8 bg-obsidian-800">
                      <Icon size={16} className="text-platinum-muted" aria-hidden="true" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[15px] text-platinum" title={v.filename}>{v.filename}</p>
                      <p className="mt-0.5 text-[11px] text-platinum-dim nums">
                        {fmtDuration(v.duration)} · {kind === 'audio' ? 'audio' : v.resolution || '—'} · {fmtDate(v.created_at)}
                      </p>
                    </div>
                    <span className={`shrink-0 rounded-full border px-2.5 py-0.5 text-[10px] uppercase tracking-wider ${st.cls}`}>
                      {st.label}
                    </span>
                  </div>

                  {(archived || sourceExp || clipsExp) && (
                    <p className="mt-3 flex items-center gap-1.5 text-[11px] text-platinum-dim nums">
                      {archived ? (
                        <>
                          <Archive size={12} aria-hidden="true" /> Archived · source deleted
                          {clipsExp && <> · clips delete {fmtDate(clipsExp)}</>}
                        </>
                      ) : (
                        <>
                          {sourceExp && <>Source deletes {fmtDate(sourceExp)}</>}
                          {sourceExp && clipsExp && ' · '}
                          {clipsExp && <>clips {fmtDate(clipsExp)}</>}
                        </>
                      )}
                    </p>
                  )}

                  <div className="mt-5 flex items-center gap-2">
                    <span className="text-xs text-platinum-muted nums">
                      {v.clips_count} {v.clips_count === 1 ? 'clip' : 'clips'}
                    </span>
                    <div className="ml-auto flex items-center gap-2">
                      {canDelete && confirming === v.id ? (
                        <>
                          <button type="button" onClick={() => setConfirming(null)} className="btn btn-ghost btn-sm">
                            Keep
                          </button>
                          <button
                            type="button"
                            onClick={() => remove(v.id)}
                            disabled={deleting === v.id}
                            className="btn btn-danger btn-sm"
                          >
                            {deleting === v.id && <Loader2 size={12} className="animate-spin" aria-hidden="true" />}
                            Delete for good
                          </button>
                        </>
                      ) : (
                        <>
                          {canDelete && (
                            <button
                              type="button"
                              onClick={() => setConfirming(v.id)}
                              aria-label={`Delete ${v.filename}`}
                              className="icon-btn h-8 w-8 border border-white/10"
                            >
                              <Trash2 size={13} aria-hidden="true" />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => navigate(`/studio?video=${encodeURIComponent(v.id)}`)}
                            className="btn btn-secondary btn-sm"
                          >
                            <Play size={12} aria-hidden="true" /> Open
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </motion.li>
              )
            })}
          </AnimatePresence>
        </ul>
      </main>
    </div>
  )
}

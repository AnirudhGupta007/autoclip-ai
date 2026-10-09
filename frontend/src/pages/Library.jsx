import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Scissors, Film, Trash2, Loader2, Plus, Play, AlertTriangle } from 'lucide-react'
import { getVideos, deleteVideo } from '../services/api'
import { useAuth } from '../auth/AuthContext'
import UserMenu from '../components/UserMenu'
import { apiError } from '../components/AuthShell'

const STATUS = {
  analyzed: { label: 'Ready', cls: 'border-gold-700/60 text-gold-300' },
  analyzing: { label: 'Analysing', cls: 'border-white/15 text-platinum-muted' },
  uploaded: { label: 'Not analysed', cls: 'border-white/10 text-platinum-dim' },
  failed: { label: 'Failed', cls: 'border-oxblood-400/50 text-oxblood-400' },
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

  const load = useCallback(() => {
    getVideos()
      .then((res) => setVideos(res.data))
      .catch((err) => setError(apiError(err, 'Could not load your library.')))
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
      <header className="hairline flex shrink-0 items-center gap-4 px-4 py-3.5 sm:px-6">
        <Link to="/studio" className="flex items-center gap-3" aria-label="Back to the studio">
          <span className="grid h-8 w-8 place-items-center rounded-lg border border-gold-700/60 bg-obsidian-800">
            <Scissors size={14} className="text-gold" aria-hidden="true" />
          </span>
          <div>
            <p className="font-display text-base leading-none tracking-tight">
              AutoClip<span className="text-gold">.</span>
            </p>
            <p className="mt-1 text-[10px] uppercase tracking-[0.2em] text-platinum-dim">Library</p>
          </div>
        </Link>
        <div className="ml-auto flex items-center gap-3">
          <UserMenu />
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-10 sm:px-6">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="mb-2 text-[11px] uppercase tracking-[0.3em] text-gold-600">
              {user?.is_demo ? 'Demo library' : 'Your library'}
            </p>
            <h1 className="font-display text-display-md">
              Every <span className="italic text-gold-400">long cut</span>, in one place.
            </h1>
            {cap != null && videos && (
              <p className="mt-2 text-xs text-platinum-dim nums">
                {videos.length} of {cap} videos stored
              </p>
            )}
          </div>
          {!user?.is_demo && (
            <Link
              to="/studio?new=1"
              className="inline-flex items-center gap-2 rounded-full bg-gold-sheen bg-[length:200%_auto] px-4 py-2 text-sm font-semibold text-obsidian transition-all duration-500 ease-lux hover:bg-[position:80%_50%]"
            >
              <Plus size={14} aria-hidden="true" /> New video
            </Link>
          )}
        </div>

        {error && (
          <p role="alert" className="mb-6 rounded-xl border border-oxblood-400/40 bg-oxblood-600/15 px-4 py-2.5 text-sm text-oxblood-400">
            {error}
          </p>
        )}

        {videos === null && !error && (
          <div className="grid place-items-center py-24">
            <Loader2 size={20} className="animate-spin text-gold" aria-label="Loading" />
          </div>
        )}

        {videos?.length === 0 && (
          <div className="glass rounded-3xl px-8 py-16 text-center">
            <Film size={22} className="mx-auto mb-4 text-gold" aria-hidden="true" />
            <p className="font-display text-xl">No videos yet</p>
            <p className="mt-2 text-sm text-platinum-muted">
              {user?.is_demo ? 'The demo library is empty right now.' : 'Upload one in the studio to get started.'}
            </p>
          </div>
        )}

        <ul className="grid gap-4 sm:grid-cols-2">
          <AnimatePresence initial={false}>
            {videos?.map((v, i) => {
              const st = STATUS[v.status] || STATUS.uploaded
              return (
                <motion.li
                  key={v.id}
                  layout
                  initial={{ opacity: 0, y: 14 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.97 }}
                  transition={{ delay: i * 0.04, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                  className="glass group flex flex-col rounded-2xl p-5 transition-colors duration-500 ease-lux hover:border-gold-700/50"
                >
                  <div className="flex items-start gap-3">
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/8 bg-white/[0.03]">
                      <Film size={16} className="text-gold" aria-hidden="true" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[15px] text-platinum" title={v.filename}>{v.filename}</p>
                      <p className="mt-0.5 text-[11px] text-platinum-dim nums">
                        {fmtDuration(v.duration)} · {v.resolution || '—'} · {fmtDate(v.created_at)}
                      </p>
                    </div>
                    <span className={`shrink-0 rounded-full border px-2.5 py-0.5 text-[10px] uppercase tracking-wider ${st.cls}`}>
                      {st.label}
                    </span>
                  </div>

                  <div className="mt-5 flex items-center gap-2">
                    <span className="text-xs text-platinum-muted nums">
                      {v.clips_count} {v.clips_count === 1 ? 'clip' : 'clips'}
                    </span>
                    <div className="ml-auto flex items-center gap-2">
                      {canDelete && confirming === v.id ? (
                        <>
                          <button
                            type="button"
                            onClick={() => setConfirming(null)}
                            className="rounded-full px-3 py-1.5 text-xs text-platinum-dim hover:text-platinum"
                          >
                            Keep
                          </button>
                          <button
                            type="button"
                            onClick={() => remove(v.id)}
                            disabled={deleting === v.id}
                            className="inline-flex items-center gap-1.5 rounded-full border border-oxblood-400/60 px-3 py-1.5 text-xs text-oxblood-400 transition-colors hover:bg-oxblood-600/20 disabled:opacity-50"
                          >
                            {deleting === v.id ? (
                              <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                            ) : (
                              <AlertTriangle size={12} aria-hidden="true" />
                            )}
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
                              className="grid h-8 w-8 place-items-center rounded-full border border-white/10 text-platinum-dim transition-colors duration-300 hover:border-oxblood-400/60 hover:text-oxblood-400"
                            >
                              <Trash2 size={13} aria-hidden="true" />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => navigate(`/studio?video=${encodeURIComponent(v.id)}`)}
                            className="inline-flex items-center gap-1.5 rounded-full border border-gold-700/50 px-3.5 py-1.5 text-xs text-gold-300 transition-colors duration-300 hover:bg-gold-700/15"
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

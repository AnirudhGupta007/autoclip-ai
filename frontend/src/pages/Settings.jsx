import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Video, Mic, Archive, CircleAlert } from 'lucide-react'
import AppHeader from '../components/AppHeader'
import ConfirmDialog from '../components/ConfirmDialog'
import { apiError } from '../components/AuthShell'
import { SPRING_SOFT } from '../components/landing/primitives'
import { useAuth } from '../auth/AuthContext'
import { deleteAccount, getQuota, getUsage } from '../services/api'

function fmtBytes(n) {
  if (n == null || Number.isNaN(n)) return '—'
  if (n < 1024 ** 2) return `${Math.max(0, Math.round(n / 1024))} KB`
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(n < 10 * 1024 ** 2 ? 1 : 0)} MB`
  return `${(n / 1024 ** 3).toFixed(2)} GB`
}

function fmtDate(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

function Group({ title, children, footer }) {
  return (
    <section className="mb-10">
      <h2 className="eyebrow mb-3 px-1">{title}</h2>
      <div className="surface divide-y divide-white/8 overflow-hidden rounded-2xl">{children}</div>
      {footer && <p className="mt-2.5 px-1 text-xs leading-relaxed text-platinum-dim">{footer}</p>}
    </section>
  )
}

function Row({ label, children }) {
  return (
    <div className="flex min-h-[52px] flex-wrap items-center justify-between gap-x-6 gap-y-1 px-5 py-3">
      <span className="text-sm text-platinum">{label}</span>
      <span className="min-w-0 text-sm text-platinum-muted">{children}</span>
    </div>
  )
}

export default function Settings() {
  const { user, refresh } = useAuth()
  const navigate = useNavigate()
  const [usage, setUsage] = useState(null) // null = loading, false = unavailable
  const [quota, setQuota] = useState(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    getUsage()
      .then((res) => setUsage(res.data || false))
      .catch(() => {
        setUsage(false)
        // Older backend: at least show today's queries.
        getQuota().then((r) => setQuota(r.data)).catch(() => {})
      })
  }, [])

  const used = usage ? usage.queries_used : quota ? (quota.limit ?? 0) - (quota.remaining ?? 0) : null
  const limit = usage ? usage.queries_limit : quota?.limit
  const unlimited = (usage || quota) && limit == null
  const pct = usage?.storage_quota_bytes ? Math.min(1, (usage.storage_bytes || 0) / usage.storage_quota_bytes) : 0
  const items = usage?.items || []

  const doDelete = async () => {
    setDeleting(true)
    setError(null)
    try {
      await deleteAccount()
      await refresh()
      navigate('/', { replace: true })
    } catch (err) {
      setError(apiError(err, 'Could not delete the account. Please try again.'))
      setDeleting(false)
      setConfirmOpen(false)
    }
  }

  const googleLinked = !!(user?.google_linked || user?.google_sub)

  return (
    <div className="min-h-screen bg-obsidian text-platinum">
      <AppHeader />

      <main className="mx-auto w-full max-w-2xl px-4 pb-24 pt-10 sm:px-6 sm:pt-14">
        <p className="eyebrow mb-2">Settings</p>
        <h1 className="mb-10 font-display text-display-md">Your <span className="italic text-gold">account.</span></h1>

        {error && (
          <p role="alert" className="notice mb-6">
            <CircleAlert size={15} className="mt-0.5 shrink-0 text-platinum-muted" aria-hidden="true" />
            {error}
          </p>
        )}

        <Group title="Account">
          <Row label="Email">
            <span className="block truncate">{user?.is_demo ? 'Shared demo account' : user?.email}</span>
          </Row>
          <Row label="Google">{googleLinked ? 'Linked' : 'Not linked'}</Row>
          <Row label="Plan">{user?.is_demo ? 'Demo (read-only)' : user?.is_admin ? 'Admin' : 'Free'}</Row>
        </Group>

        <Group title="Today" footer="Each request that runs the agent counts once. A failed request is refunded.">
          <div className="flex min-h-[52px] items-center justify-between gap-6 px-5 py-4">
            <span className="text-sm text-platinum">Requests</span>
            {used == null && !unlimited ? (
              <span className="text-sm text-platinum-dim">{usage === null ? '…' : 'Unavailable'}</span>
            ) : unlimited ? (
              <span className="text-sm text-platinum-muted">Unlimited</span>
            ) : (
              <span className="flex items-center gap-3">
                <span className="flex gap-1" aria-hidden="true">
                  {Array.from({ length: Math.max(1, limit) }, (_, i) => (
                    <span key={i} className={`h-1.5 w-6 rounded-full ${i < used ? 'bg-gold' : 'bg-white/12'}`} />
                  ))}
                </span>
                <span className="text-sm text-platinum nums">
                  <span className="text-gold">{used}</span>
                  <span className="text-platinum-dim">/{limit}</span>
                </span>
              </span>
            )}
          </div>
        </Group>

        <Group
          title="Storage"
          footer={
            <>
              Sources are deleted 7 days after upload, clips after 30.{' '}
              <Link to="/docs#storage" className="underline decoration-white/25 underline-offset-2 hover:text-platinum">
                Storage rules
              </Link>
            </>
          }
        >
          <div className="px-5 py-4">
            {usage ? (
              <>
                <div className="mb-2.5 flex items-baseline justify-between gap-4 text-sm">
                  <span className="text-platinum">Used</span>
                  <span className="text-platinum-muted nums">
                    <span className="text-platinum">{fmtBytes(usage.storage_bytes)}</span> of {fmtBytes(usage.storage_quota_bytes)}
                  </span>
                </div>
                <div
                  className="h-2 overflow-hidden rounded-full bg-white/[0.07]"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(pct * 100)}
                  aria-label="Storage used"
                >
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.max(pct * 100, pct > 0 ? 1.5 : 0)}%` }}
                    transition={SPRING_SOFT}
                    className={`h-full rounded-full ${pct > 0.9 ? 'bg-platinum' : 'bg-gold'}`}
                  />
                </div>
              </>
            ) : (
              <p className="text-sm text-platinum-dim">{usage === null ? 'Loading…' : 'Storage details are unavailable right now.'}</p>
            )}
          </div>
          {items.map((it) => {
            const Icon = it.media_kind === 'audio' ? Mic : Video
            const src = fmtDate(it.source_expires_at)
            const clips = fmtDate(it.clips_expire_at)
            return (
              <div key={it.video_id} className="flex items-start gap-3 px-5 py-3.5">
                <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/8 bg-obsidian-800">
                  <Icon size={14} className="text-platinum-muted" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-platinum" title={it.title}>{it.title || 'Untitled'}</p>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-platinum-dim nums">
                    {it.archived ? (
                      <span className="inline-flex items-center gap-1"><Archive size={11} aria-hidden="true" /> Archived, source deleted</span>
                    ) : (
                      src && <>Source deletes on {src}</>
                    )}
                    {clips && <>{(it.archived || src) && ' · '}Clips delete on {clips}</>}
                  </p>
                </div>
                <span className="shrink-0 text-xs text-platinum-muted nums">{fmtBytes(it.size_bytes)}</span>
              </div>
            )
          })}
          {usage && items.length === 0 && (
            <p className="px-5 py-4 text-sm text-platinum-dim">Nothing stored yet.</p>
          )}
        </Group>

        {!user?.is_demo && (
          <Group title="Delete account" footer="Removes every upload, clip and chat, then the account itself. This can’t be undone.">
            <div className="flex min-h-[52px] flex-wrap items-center justify-between gap-4 px-5 py-4">
              <span className="text-sm text-platinum-muted">Delete your account and all its data.</span>
              <button type="button" className="btn btn-danger btn-sm" onClick={() => { setTyped(''); setConfirmOpen(true) }}>
                Delete account
              </button>
            </div>
          </Group>
        )}
      </main>

      <ConfirmDialog
        open={confirmOpen}
        title="Delete your account?"
        body={<>Every upload, clip and chat for <span className="text-platinum">{user?.email}</span> is deleted. This can’t be undone.</>}
        confirmLabel="Delete account"
        busy={deleting}
        confirmDisabled={typed.trim().toLowerCase() !== 'delete'}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => typed.trim().toLowerCase() === 'delete' && doDelete()}
      >
        <label htmlFor="confirm-delete" className="mt-4 block text-xs text-platinum-dim">
          Type <span className="font-mono text-platinum">delete</span> to confirm
        </label>
        <input
          id="confirm-delete"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && typed.trim().toLowerCase() === 'delete' && doDelete()}
          autoComplete="off"
          className="input mt-1.5"
        />
      </ConfirmDialog>
    </div>
  )
}

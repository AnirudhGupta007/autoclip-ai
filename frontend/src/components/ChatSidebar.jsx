import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { SquarePen, Pencil, Trash2, Check, X, MessageSquare, Loader2 } from 'lucide-react'
import { SPRING } from './landing/primitives'

function relDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  if (days <= 0) return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  if (days === 1) return 'Yesterday'
  if (days < 7) return d.toLocaleDateString(undefined, { weekday: 'short' })
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

function Row({ conv, active, readOnly, onSelect, onRename, onDelete }) {
  const [mode, setMode] = useState(null) // 'rename' | 'delete' | null
  const [title, setTitle] = useState(conv.title || '')
  const [busy, setBusy] = useState(false)
  const inputRef = useRef(null)

  useEffect(() => {
    if (mode === 'rename') inputRef.current?.select()
  }, [mode])

  const saveRename = async () => {
    const t = title.trim()
    if (!t || t === conv.title) return setMode(null)
    setBusy(true)
    try {
      await onRename(conv.id, t)
      setMode(null)
    } finally {
      setBusy(false)
    }
  }

  const confirmDelete = async () => {
    setBusy(true)
    try {
      await onDelete(conv.id)
    } finally {
      setBusy(false)
      setMode(null)
    }
  }

  if (mode === 'rename') {
    return (
      <li className="flex items-center gap-1 rounded-xl bg-white/[0.06] p-1">
        <label htmlFor={`rename-${conv.id}`} className="sr-only">Chat title</label>
        <input
          id={`rename-${conv.id}`}
          ref={inputRef}
          value={title}
          maxLength={120}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') saveRename()
            if (e.key === 'Escape') setMode(null)
          }}
          className="min-w-0 flex-1 rounded-lg bg-obsidian px-2.5 py-1.5 text-[13px] text-platinum outline-none ring-1 ring-white/15 focus:ring-white/30"
        />
        <button type="button" className="icon-btn h-8 w-8" onClick={saveRename} disabled={busy} aria-label="Save title">
          {busy ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Check size={14} aria-hidden="true" />}
        </button>
        <button type="button" className="icon-btn h-8 w-8" onClick={() => setMode(null)} aria-label="Cancel rename">
          <X size={14} aria-hidden="true" />
        </button>
      </li>
    )
  }

  if (mode === 'delete') {
    return (
      <li className="rounded-xl border border-white/12 bg-white/[0.04] p-3">
        <p className="truncate text-[13px] text-platinum">Delete “{conv.title || 'Untitled chat'}”?</p>
        <p className="mt-0.5 text-[11px] text-platinum-dim">The messages go. Clips stay in your library.</p>
        <div className="mt-2.5 flex justify-end gap-1.5">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setMode(null)} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-danger btn-sm" onClick={confirmDelete} disabled={busy}>
            {busy && <Loader2 size={12} className="animate-spin" aria-hidden="true" />}
            Delete
          </button>
        </div>
      </li>
    )
  }

  return (
    <li className="group relative">
      <button
        type="button"
        onClick={() => onSelect(conv)}
        aria-current={active ? 'true' : undefined}
        className={`flex min-h-[44px] w-full items-center gap-2.5 rounded-xl py-2 pl-3 text-left transition-colors duration-200 ease-lux ${
          readOnly ? 'pr-3' : 'pr-[4.5rem]'
        } ${active ? 'bg-white/[0.08] text-platinum' : 'text-platinum-muted hover:bg-white/[0.04] hover:text-platinum'}`}
      >
        {active && (
          <motion.span layoutId="chat-active-bar" transition={SPRING} className="absolute left-0 top-2.5 h-[calc(100%-1.25rem)] w-[2px] rounded-full bg-gold" aria-hidden="true" />
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px]">{conv.title || 'Untitled chat'}</span>
          <span className="block text-[11px] text-platinum-dim nums">{relDate(conv.updated_at)}</span>
        </span>
      </button>
      {!readOnly && (
        <div
          className={`absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center transition-opacity duration-200 ${
            active ? 'opacity-100' : 'opacity-100 lg:opacity-0 lg:group-focus-within:opacity-100 lg:group-hover:opacity-100'
          }`}
        >
          <button type="button" className="icon-btn h-8 w-8" onClick={() => setMode('rename')} aria-label={`Rename ${conv.title || 'chat'}`}>
            <Pencil size={13} aria-hidden="true" />
          </button>
          <button type="button" className="icon-btn h-8 w-8" onClick={() => setMode('delete')} aria-label={`Delete ${conv.title || 'chat'}`}>
            <Trash2 size={13} aria-hidden="true" />
          </button>
        </div>
      )}
    </li>
  )
}

function SidebarBody({ conversations, activeId, readOnly, onSelect, onNew, onRename, onDelete, error }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="p-3">
        <button type="button" onClick={onNew} className="btn btn-secondary w-full justify-start rounded-xl">
          <SquarePen size={15} aria-hidden="true" /> New chat
        </button>
      </div>
      <p className="eyebrow px-5 pb-2 pt-1 text-[10px]">Chats</p>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {conversations === null ? (
          <div className="space-y-2 px-1 pt-1" aria-label="Loading chats">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-11 animate-pulse rounded-xl bg-white/[0.04]" />
            ))}
          </div>
        ) : conversations.length === 0 ? (
          <div className="px-3 py-8 text-center">
            <MessageSquare size={18} className="mx-auto mb-3 text-platinum-dim" aria-hidden="true" />
            <p className="text-[13px] text-platinum-muted">{error ? 'Chat history is unavailable.' : 'No chats yet'}</p>
            <p className="mt-1 text-[11px] leading-relaxed text-platinum-dim">
              {error ? 'Your current chat still works.' : 'Your first request starts one.'}
            </p>
          </div>
        ) : (
          <ul className="space-y-0.5">
            {conversations.map((c) => (
              <Row
                key={c.id}
                conv={c}
                active={c.id === activeId}
                readOnly={readOnly}
                onSelect={onSelect}
                onRename={onRename}
                onDelete={onDelete}
              />
            ))}
          </ul>
        )}
      </div>
      {readOnly && (
        <p className="hairline px-5 py-3 text-[11px] leading-relaxed text-platinum-dim">
          Demo chats are read-only. Sign up to keep your own.
        </p>
      )}
    </div>
  )
}

/** Studio sidebar: past chats. A fixed column on desktop, a drawer on mobile. */
export default function ChatSidebar({ open, onClose, ...props }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const pick = (fn) => (...a) => {
    onClose()
    return fn(...a)
  }

  return (
    <>
      <aside aria-label="Chat history" className="hidden w-[272px] shrink-0 border-r border-white/8 bg-obsidian-900/60 lg:block">
        <SidebarBody {...props} />
      </aside>

      <AnimatePresence>
        {open && (
          <motion.div className="fixed inset-0 z-[60] lg:hidden" initial={{ opacity: 1 }} exit={{ opacity: 1 }}>
            <motion.div
              className="absolute inset-0 bg-black/60"
              onClick={onClose}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              aria-hidden="true"
            />
            <motion.aside
              aria-label="Chat history"
              role="dialog"
              aria-modal="true"
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={SPRING}
              className="glass absolute inset-y-0 left-0 w-[86%] max-w-[320px] border-y-0 border-l-0 shadow-elev-3"
            >
              <div className="flex h-14 items-center justify-between px-4">
                <p className="font-display text-base text-platinum">Chats</p>
                <button type="button" className="icon-btn" onClick={onClose} aria-label="Close chat history">
                  <X size={16} aria-hidden="true" />
                </button>
              </div>
              <div className="h-[calc(100%-3.5rem)]">
                <SidebarBody {...props} onSelect={pick(props.onSelect)} onNew={pick(props.onNew)} />
              </div>
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}

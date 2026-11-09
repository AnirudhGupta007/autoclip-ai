import { useEffect, useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Loader2 } from 'lucide-react'
import { SPRING } from './landing/primitives'

/**
 * Confirm step for destructive actions. Cancel is the default focus, the
 * destructive button is a platinum outline (never red), Escape cancels.
 */
export default function ConfirmDialog({
  open, title, body, confirmLabel = 'Delete', busy = false, confirmDisabled = false, onConfirm, onCancel, children,
}) {
  const cancelRef = useRef(null)

  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus()
    const onKey = (e) => e.key === 'Escape' && !busy && onCancel?.()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, busy, onCancel])

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[70] grid place-items-center px-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <div className="absolute inset-0 bg-black/60" onClick={() => !busy && onCancel?.()} aria-hidden="true" />
          <motion.div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            aria-describedby="confirm-body"
            initial={{ opacity: 0, scale: 0.95, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 4 }}
            transition={SPRING}
            className="glass relative w-full max-w-sm rounded-3xl p-6 shadow-elev-3"
          >
            <h2 id="confirm-title" className="font-display text-lg text-platinum">{title}</h2>
            <div id="confirm-body" className="mt-2 text-sm leading-relaxed text-platinum-muted">{body}</div>
            {children}
            <div className="mt-6 flex justify-end gap-2">
              <button ref={cancelRef} type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
                Cancel
              </button>
              <button type="button" className="btn btn-danger" onClick={onConfirm} disabled={busy || confirmDisabled}>
                {busy && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
                {confirmLabel}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

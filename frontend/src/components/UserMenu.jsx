import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, Library, LogOut, Clapperboard, UserPlus, Settings } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { SPRING } from './landing/primitives'

/** Account chip + dropdown for the app header. */
export default function UserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false)
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!user) return null
  const label = user.is_demo ? 'Demo' : user.email
  const initial = (user.is_demo ? 'D' : user.email?.[0] || '?').toUpperCase()

  const doLogout = async () => {
    setOpen(false)
    await logout()
    navigate(user.is_demo ? '/' : '/login', { replace: true })
  }

  const item =
    'flex min-h-[36px] w-full items-center gap-2.5 rounded-lg px-3 text-left text-[13px] text-platinum-muted transition-colors duration-200 hover:bg-white/[0.06] hover:text-platinum'

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex h-9 items-center gap-2 rounded-full border border-white/10 pl-1 pr-2.5 text-xs text-platinum-muted transition-colors duration-200 hover:border-white/25 hover:text-platinum"
      >
        <span className="grid h-7 w-7 place-items-center rounded-full bg-obsidian-600 text-[11px] font-semibold text-platinum">
          {initial}
        </span>
        <span className="hidden max-w-[160px] truncate lg:inline">{label}</span>
        {user.is_admin && (
          <span className="hidden rounded-full border border-white/15 px-1.5 text-[9px] uppercase tracking-wider text-platinum-dim lg:inline">
            admin
          </span>
        )}
        <ChevronDown size={12} aria-hidden="true" />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, scale: 0.96, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: -4 }}
            transition={SPRING}
            style={{ transformOrigin: 'top right' }}
            className="glass absolute right-0 z-50 mt-2 w-60 rounded-2xl p-2 shadow-elev-3"
          >
            <p className="truncate px-3 pb-2 pt-1.5 text-[11px] text-platinum-dim">
              {user.is_demo ? 'Shared demo account (read-only)' : user.email}
            </p>
            <Link role="menuitem" to="/studio" className={item} onClick={() => setOpen(false)}>
              <Clapperboard size={14} aria-hidden="true" /> Studio
            </Link>
            <Link role="menuitem" to="/library" className={item} onClick={() => setOpen(false)}>
              <Library size={14} aria-hidden="true" /> Library
            </Link>
            <Link role="menuitem" to="/settings" className={item} onClick={() => setOpen(false)}>
              <Settings size={14} aria-hidden="true" /> Settings
            </Link>
            {user.is_demo && (
              <Link role="menuitem" to="/signup" className={item} onClick={() => setOpen(false)}>
                <UserPlus size={14} aria-hidden="true" /> Create your own account
              </Link>
            )}
            <div className="my-1 h-px bg-white/8" />
            <button role="menuitem" type="button" onClick={doLogout} className={item}>
              <LogOut size={14} aria-hidden="true" /> {user.is_demo ? 'Leave demo' : 'Sign out'}
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

import { Link, NavLink } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Scissors, Clapperboard, Library, BookOpen, Settings, Github } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import UserMenu from './UserMenu'
import { GITHUB_URL, SPRING } from './landing/primitives'

const LINKS = [
  { to: '/studio', label: 'Studio', icon: Clapperboard },
  { to: '/library', label: 'Library', icon: Library },
  { to: '/docs', label: 'Docs', icon: BookOpen },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Wordmark({ className = '' }) {
  return (
    <Link to="/" className={`flex shrink-0 items-center gap-2.5 rounded-lg ${className}`} aria-label="AutoClip home">
      <span className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 bg-obsidian-800 shadow-elev-1">
        <Scissors size={14} className="text-platinum" aria-hidden="true" />
      </span>
      <span className="hidden font-display text-base leading-none tracking-tight text-platinum sm:inline">
        AutoClip<span className="text-gold">.</span>
      </span>
    </Link>
  )
}

/**
 * Shared header for the app pages (Studio · Library · Docs · Settings).
 * `leading` sits before the wordmark (e.g. the Studio sidebar toggle);
 * `trailing` sits before the account menu (e.g. the quota chip).
 */
export default function AppHeader({ leading = null, trailing = null }) {
  const { user } = useAuth()
  return (
    <header className="glass sticky top-0 z-40 shrink-0 border-x-0 border-t-0">
      <div className="flex h-14 items-center gap-1.5 px-3 sm:gap-3 sm:px-5">
        {leading}
        <Wordmark className="mr-1 sm:mr-3" />

        <nav aria-label="App" className="flex items-center gap-0.5 sm:gap-1">
          {LINKS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              aria-label={label}
              className={({ isActive }) =>
                `relative inline-flex h-9 items-center gap-2 rounded-full px-2.5 text-[13px] transition-colors duration-200 ease-lux sm:px-3.5 ${
                  isActive ? 'text-platinum' : 'text-platinum-dim hover:text-platinum'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId="app-nav-pill"
                      transition={SPRING}
                      className="absolute inset-0 rounded-full border border-white/10 bg-white/[0.07]"
                      aria-hidden="true"
                    />
                  )}
                  <Icon size={15} className={`relative ${isActive ? 'text-gold' : ''}`} aria-hidden="true" />
                  <span className="relative hidden md:inline">{label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1.5 sm:gap-2.5">
          {trailing}
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="Source on GitHub"
            className="icon-btn hidden sm:grid"
          >
            <Github size={16} aria-hidden="true" />
          </a>
          {user ? (
            <UserMenu />
          ) : (
            <Link to="/login" className="btn btn-secondary btn-sm">
              Log in
            </Link>
          )}
        </div>
      </div>
    </header>
  )
}

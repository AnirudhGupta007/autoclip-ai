import { NavLink } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Upload, LayoutDashboard, Sparkles } from 'lucide-react'

const links = [
  { to: '/', icon: Upload, label: 'Upload' },
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
]

export default function Sidebar() {
  return (
    <aside className="w-64 bg-surface border-r border-white/5 flex flex-col h-screen">
      <div className="p-6 border-b border-white/5">
        <div className="flex items-center gap-2">
          <Sparkles className="w-6 h-6 text-primary" />
          <h1 className="text-xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            AutoClip AI
          </h1>
        </div>
        <p className="text-xs text-muted mt-1">AI-Powered Video Clipping</p>
      </div>

      <nav className="flex-1 p-4 space-y-1">
        {links.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-3 rounded-lg transition-all ${
                isActive
                  ? 'bg-primary/20 text-primary'
                  : 'text-muted hover:bg-white/5 hover:text-white'
              }`
            }
          >
            <Icon className="w-5 h-5" />
            <span className="text-sm font-medium">{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="p-4 border-t border-white/5">
        <p className="text-xs text-muted text-center">v1.0.0</p>
      </div>
    </aside>
  )
}

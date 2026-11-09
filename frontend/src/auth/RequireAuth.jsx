import { Navigate, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from './AuthContext'
import { loginPath } from '../services/api'

export function FullScreenLoader() {
  return (
    <div className="grid h-screen place-items-center bg-obsidian">
      <Loader2 size={20} className="animate-spin text-platinum-dim" aria-label="Loading" />
    </div>
  )
}

/** Gate a route behind a session; bounce to /login?next=… otherwise. */
export default function RequireAuth({ children }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <FullScreenLoader />
  if (!user) return <Navigate to={loginPath(`${location.pathname}${location.search}`)} replace />
  return children
}

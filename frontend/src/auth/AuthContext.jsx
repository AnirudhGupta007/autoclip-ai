import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import * as api from '../services/api'

const AuthContext = createContext(null)

/** Session state for the whole app: who is signed in (GET /api/auth/me on load). */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const res = await api.getMe()
      setUser(res.data)
      return res.data
    } catch {
      setUser(null)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const value = useMemo(
    () => ({
      user,
      loading,
      refresh,
      login: async (email, password) => {
        const res = await api.login(email, password)
        setUser(res.data)
        return res.data
      },
      signup: async (email, password) => {
        const res = await api.signup(email, password)
        setUser(res.data)
        return res.data
      },
      loginDemo: async () => {
        const res = await api.loginDemo()
        setUser(res.data)
        return res.data
      },
      logout: async () => {
        try {
          await api.logout()
        } finally {
          setUser(null)
        }
      },
    }),
    [user, loading, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)

/** Only allow a `next` that is a local path (no open redirects). */
export function safeNext(next, fallback = '/studio') {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/login')) return fallback
  return next
}

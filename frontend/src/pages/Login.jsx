import { useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { Sparkles } from 'lucide-react'
import AuthShell, { Field, GoldButton, GhostButton, FormError, apiError } from '../components/AuthShell'
import { FullScreenLoader } from '../auth/RequireAuth'
import { useAuth, safeNext } from '../auth/AuthContext'

export default function Login() {
  const { user, loading, login, loginDemo } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const next = safeNext(params.get('next'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(null) // 'login' | 'demo' | null
  const [error, setError] = useState(null)

  if (loading) return <FullScreenLoader />
  if (user && !user.is_demo && !busy) return <Navigate to={next} replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy('login')
    setError(null)
    try {
      await login(email, password)
      navigate(next, { replace: true })
    } catch (err) {
      setError(apiError(err))
      setBusy(null)
    }
  }

  const tryDemo = async () => {
    setBusy('demo')
    setError(null)
    try {
      await loginDemo()
      navigate('/studio', { replace: true })
    } catch (err) {
      setError(apiError(err, "The demo isn't available right now."))
      setBusy(null)
    }
  }

  return (
    <AuthShell
      eyebrow="Welcome back"
      title="Sign in to the"
      accent="studio."
      subtitle="Your videos, clips and conversations are private to your account."
      footer={
        <>
          New here?{' '}
          <Link
            to={`/signup${params.get('next') ? `?next=${encodeURIComponent(next)}` : ''}`}
            className="text-platinum underline decoration-white/30 underline-offset-4 hover:decoration-platinum"
          >
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field
          id="email" label="Email" type="email" autoComplete="email" required
          value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@studio.com"
        />
        <Field
          id="password" label="Password" type="password" autoComplete="current-password" required
          value={password} onChange={(e) => setPassword(e.target.value)}
        />
        <FormError>{error}</FormError>
        <GoldButton type="submit" busy={busy === 'login'} disabled={!email || !password || !!busy}>
          Sign in
        </GoldButton>
      </form>

      <div className="my-5 flex items-center gap-3 text-[10px] uppercase tracking-[0.22em] text-platinum-dim">
        <span className="h-px flex-1 bg-white/10" />
        or
        <span className="h-px flex-1 bg-white/10" />
      </div>

      <GhostButton type="button" onClick={tryDemo} busy={busy === 'demo'} disabled={!!busy}>
        <Sparkles size={14} aria-hidden="true" />
        Try the demo — no account needed
      </GhostButton>
      <p className="mt-2.5 text-center text-[11px] text-platinum-dim">
        Explore a pre-analysed talk and chat with the agent. Uploads need an account.
      </p>
    </AuthShell>
  )
}

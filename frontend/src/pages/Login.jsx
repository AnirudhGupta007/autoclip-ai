import { useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import AuthShell, { Field, GoldButton, FormError, apiError } from '../components/AuthShell'
import { FullScreenLoader } from '../auth/RequireAuth'
import { useAuth, safeNext } from '../auth/AuthContext'

export default function Login() {
  const { user, loading, login } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const next = safeNext(params.get('next'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(null) // 'login' | null
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
    </AuthShell>
  )
}

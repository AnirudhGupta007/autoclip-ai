import { useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import AuthShell, { Field, GoldButton, FormError, apiError } from '../components/AuthShell'
import { FullScreenLoader } from '../auth/RequireAuth'
import { useAuth, safeNext } from '../auth/AuthContext'

const MIN_PASSWORD = 10

export default function Signup() {
  const { user, loading, signup } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const next = safeNext(params.get('next'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (loading) return <FullScreenLoader />
  if (user && !busy && !user.is_demo) return <Navigate to={next} replace />

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD

  const submit = async (e) => {
    e.preventDefault()
    if (password.length < MIN_PASSWORD) {
      setError(`Password must be at least ${MIN_PASSWORD} characters.`)
      return
    }
    setBusy(true)
    setError(null)
    try {
      await signup(email, password)
      navigate(next, { replace: true })
    } catch (err) {
      setError(apiError(err))
      setBusy(false)
    }
  }

  return (
    <AuthShell
      eyebrow="Create an account"
      title="Start with the"
      accent="long cut."
      subtitle="Upload your own videos and ask for clips in plain language."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="text-gold-400 underline-offset-4 hover:underline">
            Sign in
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
          id="password" label="Password" type="password" autoComplete="new-password" required
          minLength={MIN_PASSWORD} value={password} onChange={(e) => setPassword(e.target.value)}
          hint={tooShort ? `${MIN_PASSWORD - password.length} more characters` : `At least ${MIN_PASSWORD} characters.`}
        />
        <FormError>{error}</FormError>
        <GoldButton type="submit" busy={busy} disabled={!email || !password || busy}>
          Create account
        </GoldButton>
      </form>
    </AuthShell>
  )
}

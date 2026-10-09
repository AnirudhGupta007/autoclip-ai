import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import AuthShell, { FormError, apiError } from '../components/AuthShell'
import { FullScreenLoader } from '../auth/RequireAuth'
import { useAuth } from '../auth/AuthContext'

/** /demo — signs into the shared demo account and drops the visitor in the studio. */
export default function Demo() {
  const { loginDemo } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState(null)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return // StrictMode double-invoke
    started.current = true
    loginDemo()
      .then(() => navigate('/studio', { replace: true }))
      .catch((err) => setError(apiError(err, "The demo isn't available right now.")))
  }, [loginDemo, navigate])

  if (!error) return <FullScreenLoader />
  return (
    <AuthShell eyebrow="Demo" title="Demo" accent="unavailable.">
      <FormError>{error}</FormError>
      <p className="mt-4 text-center text-sm text-platinum-muted">
        <Link to="/signup" className="text-gold-400 underline-offset-4 hover:underline">Create an account</Link>
        {' '}or{' '}
        <Link to="/login" className="text-gold-400 underline-offset-4 hover:underline">sign in</Link>.
      </p>
    </AuthShell>
  )
}

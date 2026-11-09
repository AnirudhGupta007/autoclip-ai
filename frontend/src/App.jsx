import { Routes, Route, Navigate } from 'react-router-dom'
import { MotionConfig } from 'framer-motion'
import Landing from './pages/Landing'
import Chat from './pages/Chat'
import Login from './pages/Login'
import Signup from './pages/Signup'
import Demo from './pages/Demo'
import Library from './pages/Library'
import Docs from './pages/Docs'
import Settings from './pages/Settings'
import { AuthProvider } from './auth/AuthContext'
import RequireAuth from './auth/RequireAuth'

export default function App() {
  return (
    <AuthProvider>
      <MotionConfig reducedMotion="user">
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/demo" element={<Demo />} />
          <Route path="/studio" element={<RequireAuth><Chat /></RequireAuth>} />
          <Route path="/library" element={<RequireAuth><Library /></RequireAuth>} />
          <Route path="/docs" element={<Docs />} />
          <Route path="/settings" element={<RequireAuth><Settings /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </MotionConfig>
    </AuthProvider>
  )
}

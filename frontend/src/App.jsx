import { Routes, Route } from 'react-router-dom'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Chat />} />
      <Route path="/dashboard" element={<Dashboard />} />
    </Routes>
  )
}

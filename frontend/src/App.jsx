import { Routes, Route } from 'react-router-dom'
import Chat from './pages/Chat'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Chat />} />
    </Routes>
  )
}

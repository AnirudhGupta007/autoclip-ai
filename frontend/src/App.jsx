import { Routes, Route } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import Sidebar from './components/Sidebar'
import Home from './pages/Home'
import Process from './pages/Process'
import Results from './pages/Results'
import Dashboard from './pages/Dashboard'

export default function App() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6">
        <AnimatePresence mode="wait">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/process/:videoId" element={<Process />} />
            <Route path="/results/:videoId" element={<Results />} />
            <Route path="/dashboard" element={<Dashboard />} />
          </Routes>
        </AnimatePresence>
      </main>
    </div>
  )
}

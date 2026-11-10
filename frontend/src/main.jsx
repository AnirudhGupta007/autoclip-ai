import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
// Self-hosted fonts (no Google Fonts request). Only the weights the UI uses:
// Plus Jakarta Sans 700/800 + 700 italic (headings, canvas captions), Inter
// 400/500/600 (body, buttons), JetBrains Mono 400/500.
// Each file carries unicode-range subsets; browsers fetch only the Latin one.
import '@fontsource/plus-jakarta-sans/700.css'
import '@fontsource/plus-jakarta-sans/800.css'
import '@fontsource/plus-jakarta-sans/700-italic.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)

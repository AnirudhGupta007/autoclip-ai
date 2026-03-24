/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: '#0a0a0a',
        surface: '#1a1a2e',
        card: '#16213e',
        primary: '#6c5ce7',
        accent: '#00cec9',
        success: '#00b894',
        warning: '#fdcb6e',
        error: '#e17055',
        muted: '#a0a0b0',
      },
    },
  },
  plugins: [],
}

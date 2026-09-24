/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Obsidian base — layered, never pure black (pure black kills depth
        // on OLED and makes glass surfaces read as flat cut-outs).
        obsidian: {
          DEFAULT: '#000000',
          900: '#0B0B10',
          800: '#121218',
          700: '#191922',
          600: '#22222D',
        },
        // Champagne gold — the single brand accent.
        gold: {
          DEFAULT: '#D4AF7A',
          300: '#EBD6B3',
          400: '#E0C296',
          500: '#D4AF7A',
          600: '#B8905A',
          700: '#8C6A3F',
        },
        // Oxblood — reserved for emphasis/destructive, never decoration.
        oxblood: {
          DEFAULT: '#7B2D3B',
          400: '#9C4152',
          600: '#5E202B',
        },
        platinum: {
          DEFAULT: '#F5F3EF',
          muted: '#D2CDC4',
          dim: '#9C978E',
        },
      },
      fontFamily: {
        display: ['"Plus Jakarta Sans"', 'Inter', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        // Fluid display sizes — no layout jump between breakpoints.
        'display-xl': ['clamp(2.5rem, 6.4vw, 6rem)', { lineHeight: '1.02', letterSpacing: '-0.035em' }],
        'display-lg': ['clamp(1.9rem, 4.2vw, 3.5rem)', { lineHeight: '1.1', letterSpacing: '-0.03em' }],
        'display-md': ['clamp(1.5rem, 3vw, 2.25rem)', { lineHeight: '1.15' }],
      },
      spacing: {
        18: '4.5rem',
        22: '5.5rem',
        30: '7.5rem',
      },
      borderRadius: {
        '4xl': '2rem',
      },
      boxShadow: {
        'glass': '0 1px 0 0 rgba(255,255,255,0.06) inset, 0 20px 60px -20px rgba(0,0,0,0.9)',
        'gold': '0 0 0 1px rgba(212,175,122,0.25), 0 18px 50px -18px rgba(212,175,122,0.45)',
        'lift': '0 30px 80px -30px rgba(0,0,0,0.95)',
      },
      backgroundImage: {
        'gold-sheen': 'linear-gradient(103deg, #8C6A3F 0%, #EBD6B3 38%, #D4AF7A 52%, #8C6A3F 100%)',
        'obsidian-fade': 'linear-gradient(180deg, rgba(0,0,0,0) 0%, #000000 85%)',
      },
      transitionTimingFunction: {
        // One easing token everywhere, so motion feels like one system.
        'lux': 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      keyframes: {
        'sheen': {
          '0%': { backgroundPosition: '0% 50%' },
          '100%': { backgroundPosition: '200% 50%' },
        },
        'drift': {
          '0%, 100%': { transform: 'translate3d(0,0,0) scale(1)' },
          '50%': { transform: 'translate3d(2%, -3%, 0) scale(1.06)' },
        },
        'playhead': {
          '0%': { transform: 'translateX(0%)' },
          '100%': { transform: 'translateX(100%)' },
        },
        'rise': {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'sheen': 'sheen 7s linear infinite',
        'drift': 'drift 22s ease-in-out infinite',
        'playhead': 'playhead 6s linear infinite',
        'rise': 'rise 0.6s cubic-bezier(0.22,1,0.36,1) both',
      },
    },
  },
  plugins: [],
}

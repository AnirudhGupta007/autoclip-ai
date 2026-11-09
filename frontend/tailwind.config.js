/** @type {import('tailwindcss').Config} */

// Colours live as RGB channels in CSS variables (src/index.css :root) so
// Tailwind's `/<alpha>` modifiers keep working: `bg-gold/10`, `border-platinum/40`.
const v = (name) => `rgb(var(--c-${name}) / <alpha-value>)`

export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Palette: two major colours + one detail colour.
      colors: {
        // Major 1 — obsidian black. DEFAULT is pure black (page background);
        // 900–600 are the layered surfaces on top of it.
        obsidian: {
          DEFAULT: v('obsidian'),
          900: v('surface-900'),
          800: v('surface-800'),
          700: v('surface-700'),
          600: v('surface-600'),
        },
        // Major 2 — platinum, for text and UI.
        platinum: {
          DEFAULT: v('platinum'),
          muted: v('platinum-muted'),
          dim: v('platinum-dim'),
        },
        // Detail — gold. Only CTAs, active state, focus ring, key numbers and
        // one highlighted headline word. Never decoration.
        gold: {
          DEFAULT: v('gold'),
          300: v('gold-300'),
          400: v('gold-400'),
          500: v('gold'),
          600: v('gold-600'),
          700: v('gold-700'),
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
      // `white/8`-style modifiers are used across landing + studio; 8 isn't in
      // Tailwind's default opacity scale, so those classes silently vanished.
      opacity: {
        8: '0.08',
        12: '0.12',
      },
      // Apple radii, concentric: outer = inner + padding (8 + 8 = 16, 12 + 8 = 20).
      borderRadius: {
        lg: 'var(--radius-sm)',
        xl: 'var(--radius-md)',
        '2xl': 'var(--radius-lg)',
        '3xl': 'var(--radius-xl)',
        '4xl': '2rem',
      },
      // Layered dark shadows: a tight contact shadow plus a soft ambient one.
      boxShadow: {
        'elev-1': 'var(--shadow-1)',
        'elev-2': 'var(--shadow-2)',
        'elev-3': 'var(--shadow-3)',
        'glass': 'var(--shadow-2)',
        'lift': 'var(--shadow-3)',
        'gold': '0 0 0 1px rgb(var(--c-gold) / 0.35), 0 12px 32px -12px rgb(var(--c-gold) / 0.45)',
      },
      backgroundImage: {
        'obsidian-fade': 'linear-gradient(180deg, rgba(0,0,0,0) 0%, rgb(var(--c-obsidian)) 85%)',
      },
      transitionTimingFunction: {
        // One easing token everywhere, so motion feels like one system.
        'lux': 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      keyframes: {
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
        'drift': 'drift 22s ease-in-out infinite',
        'playhead': 'playhead 6s linear infinite',
        'rise': 'rise 0.6s cubic-bezier(0.22,1,0.36,1) both',
      },
    },
  },
  plugins: [],
}

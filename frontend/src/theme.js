/*
 * Hex mirrors of the CSS tokens in index.css, for places that can't read CSS
 * variables: SVG presentation attributes, three.js, framer-motion colour tweens.
 * Keep in step with :root in src/index.css.
 */
export const C = {
  obsidian: '#000000',
  surface900: '#0B0B10',
  surface800: '#121218',
  surface700: '#191922',
  platinum: '#F5F3EF',
  platinumMuted: '#D2CDC4',
  platinumDim: '#9C978E',
  gold: '#D4AF7A',
  gold300: '#EBD6B3',
}

/** `#RRGGBB` + alpha → `rgba(...)`. */
export const alpha = (hex, a) => {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
}

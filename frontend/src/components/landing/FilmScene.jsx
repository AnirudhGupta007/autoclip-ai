import { useEffect, useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import * as THREE from 'three'

/*
 * Scroll-driven 3D "film journey".
 *
 * The long-form source is a helix tunnel of 16:9 HD stills. Scroll flies the
 * camera through it; the moments the agent picks light up gold, then pull
 * forward and reshape into 9:16 clip cards that actually play, while
 * everything else falls back into the fog. `progress` is a framer-motion
 * MotionValue (0 → 1).
 *
 * Footage: "Tears of Steel" and "Sintel" (CC-BY 3.0, Blender Foundation).
 */

const OBSIDIAN = '#000000'
const GOLD = new THREE.Color('#D4AF7A')
const SRC_ASPECT = 16 / 9
const CLIP_ASPECT = 9 / 16
const GAP = 1.15
const STILL_COUNT = 34

const STILLS = Array.from({ length: STILL_COUNT }, (_, i) => `/film/still-${String(i + 1).padStart(2, '0')}.webp`)

const CLIPS = [
  { src: '/film/clip-2.mp4', poster: '/film/clip-2-poster.webp', caption: ['WAIT FOR', 'IT...'], score: '9.1' },
  { src: '/film/clip-3.mp4', poster: '/film/clip-3-poster.webp', caption: ['HE ACTUALLY', 'SAID THAT'], score: '8.9' },
  { src: '/film/clip-1.mp4', poster: '/film/clip-1-poster.webp', caption: ['IT WAS RIGHT', 'BEHIND HIM'], score: '8.7' },
  { src: '/film/clip-5.mp4', poster: '/film/clip-5-poster.webp', caption: ['THE MOMENT', 'IT CLICKED'], score: '8.4' },
  { src: '/film/clip-4.mp4', poster: '/film/clip-4-poster.webp', caption: ['THE QUIET', 'PART'], score: '8.2' },
]

function mulberry32(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const smooth = (a, b, x) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}
const lerp = THREE.MathUtils.lerp

function prepTexture(tex) {
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 16 // clamped to the GPU max; keeps tilted frames sharp
  return tex
}

/* Transparent 9:16 overlay: score chip on top, burned-in style caption at the bottom. */
const CAPTION_FONT = '"Plus Jakarta Sans"'

function paintCaption({ caption, score }, tex) {
  const W = 540
  const H = 960
  const c = tex ? tex.image : document.createElement('canvas')
  c.width = W
  c.height = H
  const g = c.getContext('2d')
  g.clearRect(0, 0, W, H)

  const scrim = g.createLinearGradient(0, H * 0.55, 0, H)
  scrim.addColorStop(0, 'rgba(0,0,0,0)')
  scrim.addColorStop(1, 'rgba(0,0,0,0.85)')
  g.fillStyle = scrim
  g.fillRect(0, H * 0.55, W, H * 0.45)

  g.textAlign = 'center'
  g.lineJoin = 'round'
  g.font = '800 50px "Plus Jakarta Sans", Inter, system-ui, sans-serif'
  g.lineWidth = 10
  g.strokeStyle = 'rgba(0,0,0,0.9)'
  caption.forEach((line, i) => {
    const y = H * 0.8 + i * 60
    g.strokeText(line, W / 2, y)
    g.fillStyle = i === 1 ? '#EBD6B3' : '#F5F3EF'
    g.fillText(line, W / 2, y)
  })

  g.fillStyle = 'rgba(0,0,0,0.72)'
  g.beginPath()
  g.roundRect(W / 2 - 58, 36, 116, 52, 26)
  g.fill()
  g.strokeStyle = 'rgba(212,175,122,0.6)'
  g.lineWidth = 2
  g.stroke()
  g.fillStyle = '#D4AF7A'
  g.font = '700 30px "Plus Jakarta Sans", Inter, system-ui, sans-serif'
  g.fillText(score, W / 2, 73)

  if (tex) {
    tex.needsUpdate = true
    return tex
  }
  return prepTexture(new THREE.CanvasTexture(c))
}

function useStillTextures() {
  const textures = useMemo(() => {
    const loader = new THREE.TextureLoader()
    return STILLS.map((url) => prepTexture(loader.load(url)))
  }, [])
  useEffect(() => () => textures.forEach((t) => t.dispose()), [textures])
  return textures
}

/* One <video> per picked clip. The poster shows until the first frame is ready. */
function useClipMedia(count) {
  const media = useMemo(() => {
    const loader = new THREE.TextureLoader()
    return CLIPS.slice(0, count).map((clip) => {
      const video = document.createElement('video')
      Object.assign(video, { src: clip.src, muted: true, loop: true, playsInline: true, preload: 'auto', crossOrigin: 'anonymous' })
      video.setAttribute('playsinline', '')
      return {
        video,
        poster: prepTexture(loader.load(clip.poster)),
        videoTex: prepTexture(new THREE.VideoTexture(video)),
        overlay: paintCaption(clip),
        ready: false,
      }
    })
  }, [count])

  // Canvas text falls back to system fonts if painted before the webfont arrives
  useEffect(() => {
    let live = true
    document.fonts
      ?.load(`800 50px ${CAPTION_FONT}`)
      .then(() => live && media.forEach((m, k) => paintCaption(CLIPS[k], m.overlay)))
      .catch(() => {})
    return () => {
      live = false
    }
  }, [media])

  useEffect(() => {
    const cleanups = media.map((m) => {
      const onReady = () => (m.ready = true)
      m.video.addEventListener('playing', onReady)
      return () => {
        m.video.removeEventListener('playing', onReady)
        m.video.pause()
        m.video.removeAttribute('src')
        m.video.load()
        m.poster.dispose()
        m.videoTex.dispose()
        m.overlay.dispose()
      }
    })
    return () => cleanups.forEach((fn) => fn())
  }, [media])

  return media
}

function useFrames(count, pickCount, stills, clips) {
  return useMemo(() => {
    const r = mulberry32(42)
    // Spread picks through the first ~70% of the tunnel so the camera passes them lit
    const pickAt = new Map()
    for (let k = 0; k < pickCount; k++) {
      pickAt.set(Math.round(((k + 0.8) / (pickCount + 0.6)) * count * 0.68), k)
    }
    // Shuffle the stills so live-action and animation interleave down the tunnel
    const order = [...stills.keys()].sort(() => r() - 0.5)
    return Array.from({ length: count }, (_, i) => {
      const angle = i * 2.39996 // golden angle — no two neighbours overlap
      const radius = 2.0 + r() * 1.4
      const k = pickAt.has(i) ? pickAt.get(i) : -1
      return {
        i,
        k,
        home: new THREE.Vector3(Math.cos(angle) * radius * 1.35, Math.sin(angle) * radius * 0.85, -i * GAP),
        rot: new THREE.Euler((r() - 0.5) * 0.3, (r() - 0.5) * 0.5, (r() - 0.5) * 0.25),
        size: 0.9 + r() * 0.4,
        phase: r() * Math.PI * 2,
        texture: k >= 0 ? clips[k].poster : stills[order[i % order.length]],
      }
    })
  }, [count, pickCount, stills, clips])
}

function Dust({ count, length }) {
  const geo = useMemo(() => {
    const r = mulberry32(7)
    const pos = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const a = r() * Math.PI * 2
      const rad = 0.5 + r() * 6
      pos[i * 3] = Math.cos(a) * rad * 1.4
      pos[i * 3 + 1] = Math.sin(a) * rad
      pos[i * 3 + 2] = 10 - r() * (length + 20)
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    return g
  }, [count, length])

  // Soft round sprite — default points render as hard squares
  const sprite = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = c.height = 32
    const g = c.getContext('2d')
    const grad = g.createRadialGradient(16, 16, 0, 16, 16, 16)
    grad.addColorStop(0, 'rgba(255,255,255,1)')
    grad.addColorStop(0.4, 'rgba(255,255,255,0.5)')
    grad.addColorStop(1, 'rgba(255,255,255,0)')
    g.fillStyle = grad
    g.fillRect(0, 0, 32, 32)
    return new THREE.CanvasTexture(c)
  }, [])

  const ref = useRef()
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.z += dt * 0.015
  })

  return (
    <points ref={ref} geometry={geo}>
      <pointsMaterial map={sprite} alphaTest={0.01} color={GOLD} size={0.06} sizeAttenuation transparent opacity={0.55} depthWrite={false} blending={THREE.AdditiveBlending} />
    </points>
  )
}

function Journey({ progress, reduced, active }) {
  const narrow = typeof window !== 'undefined' && window.innerWidth < 768
  const count = narrow ? 42 : 66
  const pickCount = narrow ? 3 : 5
  const stills = useStillTextures()
  const clips = useClipMedia(pickCount)
  const frames = useFrames(count, pickCount, stills, clips)
  const length = count * GAP
  const zEnd = -length * 0.62

  const meshes = useRef([])
  const glows = useRef([])
  const overlays = useRef([])
  const playing = useRef(false)
  const p = useRef(0)
  const look = useMemo(() => new THREE.Vector3(), [])
  const target = useMemo(() => new THREE.Vector3(), [])
  const plane = useMemo(() => new THREE.PlaneGeometry(1, 1), [])

  // Never decode video while the section is off-screen
  useEffect(() => {
    if (!active) {
      clips.forEach((c) => c.video.pause())
      playing.current = false
    }
  }, [active, clips])

  useFrame((state, dt) => {
    const cam = state.camera
    const t = state.clock.elapsedTime
    p.current = THREE.MathUtils.damp(p.current, progress.get(), 5, dt)
    const P = p.current

    // Clips only need to play once the picks start glowing
    const wantPlay = P > 0.2
    if (wantPlay !== playing.current) {
      playing.current = wantPlay
      clips.forEach((c) => (wantPlay ? c.video.play().catch(() => {}) : c.video.pause()))
    }

    // ── Camera: hover at the tunnel mouth, fly through, settle ──
    const fly = smooth(0.1, 0.62, P)
    const settle = smooth(0.55, 0.7, P)
    const sway = (1 - settle) * (reduced ? 0 : 1)
    cam.position.set(
      Math.sin(P * 7) * 0.35 * sway + state.pointer.x * 0.25,
      Math.cos(P * 5) * 0.2 * sway + state.pointer.y * 0.15,
      lerp(7.5, zEnd, fly),
    )
    look.set(cam.position.x * 0.4, cam.position.y * 0.4, cam.position.z - 6)
    cam.lookAt(look)
    cam.rotation.z += Math.sin(P * 5) * 0.05 * sway

    // ── Grid geometry for the final clip cards ──
    const cardH = 1.5
    const cardW = cardH * CLIP_ASPECT
    const gap = narrow ? 0.16 : 0.32
    const total = pickCount * cardW + (pickCount - 1) * gap
    const aspect = state.size.width / state.size.height
    const vfov = THREE.MathUtils.degToRad(cam.fov)
    const dist = Math.max(3.6, (total * (aspect < 1 ? 1.14 : 1.25)) / (2 * Math.tan(vfov / 2) * aspect))

    const lit = smooth(0.26, 0.42, P)
    const fade = smooth(0.52, 0.68, P)

    frames.forEach((f, idx) => {
      const m = meshes.current[idx]
      if (!m) return
      const bob = reduced ? 0 : Math.sin(t * 0.6 + f.phase) * 0.06
      const drift = 1 + fade * 0.8 // non-picks drift outward as they fade

      if (f.k < 0) {
        m.position.set(f.home.x * drift, f.home.y * drift + bob, f.home.z)
        m.rotation.copy(f.rot)
        m.scale.set(f.size * 1.6, f.size * 0.9, 1)
        m.material.opacity = lerp(1, 0.08, fade)
        return
      }

      // Swap poster → live video once the first frame is decoded
      const clip = clips[f.k]
      if (clip.ready && m.material.map !== clip.videoTex) {
        m.material.map = clip.videoTex
        m.material.needsUpdate = true
      }

      // Picked frame: tunnel → card, staggered per card
      const a = smooth(0.56 + f.k * 0.022, 0.74 + f.k * 0.022, P)
      target.set(
        (f.k - (pickCount - 1) / 2) * (cardW + gap),
        -0.3 + (reduced ? 0 : Math.sin(t * 0.8 + f.k) * 0.04 * a),
        zEnd - dist,
      )
      m.position.set(
        lerp(f.home.x, target.x, a),
        lerp(f.home.y + bob, target.y, a),
        lerp(f.home.z, target.z, a),
      )
      m.rotation.set(
        lerp(f.rot.x, 0, a),
        lerp(f.rot.y, reduced ? 0 : Math.sin(t * 0.5 + f.k) * 0.08, a),
        lerp(f.rot.z, 0, a),
      )
      const sx = lerp(f.size * 1.6, cardW, a)
      const sy = lerp(f.size * 0.9, cardH, a)
      m.scale.set(sx, sy, 1)
      // Reframe: crop to the card's current aspect instead of squashing the footage
      const rep = Math.min(1, sx / sy / SRC_ASPECT)
      const map = m.material.map
      map.repeat.x = rep
      map.offset.x = (1 - rep) / 2
      m.material.opacity = 1

      const overlay = overlays.current[idx]
      if (overlay) overlay.material.opacity = smooth(0.75, 1, a)

      const glow = glows.current[idx]
      if (glow) {
        const pulse = reduced ? 1 : 0.85 + Math.sin(t * 2.2 + f.k) * 0.15
        glow.material.opacity = lit * pulse * lerp(0.9, 0.28, a)
      }
    })
  })

  return (
    <>
      <color attach="background" args={[OBSIDIAN]} />
      <fogExp2 attach="fog" args={[OBSIDIAN, 0.032]} />
      <Dust count={narrow ? 500 : 1100} length={length} />
      {frames.map((f, idx) => (
        <mesh key={f.i} ref={(el) => (meshes.current[idx] = el)} geometry={plane}>
          <meshBasicMaterial map={f.texture} transparent toneMapped={false} />
          {f.k >= 0 && (
            <>
              <mesh ref={(el) => (overlays.current[idx] = el)} geometry={plane} position={[0, 0, 0.005]}>
                <meshBasicMaterial map={clips[f.k].overlay} transparent opacity={0} depthWrite={false} toneMapped={false} />
              </mesh>
              <mesh ref={(el) => (glows.current[idx] = el)} geometry={plane} position={[0, 0, -0.01]} scale={[1.05, 1.035, 1]}>
                <meshBasicMaterial color={GOLD} transparent opacity={0} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
              </mesh>
            </>
          )}
        </mesh>
      ))}
    </>
  )
}

export default function FilmScene({ progress, active = true, reduced = false }) {
  return (
    <Canvas
      className="!absolute inset-0"
      frameloop={active ? 'always' : 'never'}
      dpr={[1.5, 2]} // supersample on 1x screens — frames were soft at dpr 1
      camera={{ fov: 50, near: 0.1, far: 120, position: [0, 0, 7.5] }}
      gl={{ antialias: true, powerPreference: 'high-performance' }}
    >
      <Journey progress={progress} reduced={reduced} active={active} />
    </Canvas>
  )
}

<script setup lang="ts">
/**
 * PetalFall — 全站梅花瓣飘落背景层
 * 原生 Canvas 手绘粉色系花瓣，旋转飘落 + 轻微摆动 + 翻转。
 * 尊重 prefers-reduced-motion；localStorage:gf-petals=off 可关闭；
 * 监听 GF_PETALS_EVENT 自定义事件实现免刷新开关。
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { GF_PETALS_EVENT, getPetalsEnabled } from './shared'

interface Petal {
  x: number
  y: number
  size: number
  fall: number        // 下落速度
  swayAmp: number     // 摆动幅度
  swaySpeed: number   // 摆动频率
  phase: number       // 摆动相位
  rot: number         // 当前旋转角
  rotSpeed: number    // 旋转速度
  flipSpeed: number   // 翻转频率（scaleX 呼吸）
  alpha: number
  sprite: number      // 预渲染贴图下标
}

const visible = ref(false)
const canvasRef = ref<HTMLCanvasElement | null>(null)

let ctx: CanvasRenderingContext2D | null = null
let petals: Petal[] = []
let sprites: HTMLCanvasElement[] = []
let raf = 0
let last = 0
let width = 0
let height = 0
let dpr = 1
let running = false

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

/* 花瓣贴图：柔粉 → 胭脂 的渐变心形瓣，离线预渲染避免逐帧渐变开销 */
const SPRITE_COLORS: Array<[string, string]> = [
  ['#F7D8E2', '#EBA9BF'],
  ['#F3C9D6', '#E293AC'],
  ['#EFB7C8', '#D9708E'],
  ['#F9E4EA', '#F0B9C9'],
]
const SPRITE_SIZE = 48

function makeSprites() {
  sprites = SPRITE_COLORS.map(([light, deep]) => {
    const c = document.createElement('canvas')
    c.width = SPRITE_SIZE
    c.height = SPRITE_SIZE
    const g = c.getContext('2d')!
    const s = SPRITE_SIZE / 2
    g.translate(s, s)
    const grad = g.createLinearGradient(0, -s * 0.7, 0, s * 0.6)
    grad.addColorStop(0, light)
    grad.addColorStop(1, deep)
    g.fillStyle = grad
    // 梅瓣：圆润心形，尖端微凹
    g.beginPath()
    g.moveTo(0, s * 0.58)
    g.bezierCurveTo(-s * 0.95, s * 0.12, -s * 0.78, -s * 0.72, -s * 0.1, -s * 0.5)
    g.quadraticCurveTo(0, -s * 0.42, s * 0.1, -s * 0.5)
    g.bezierCurveTo(s * 0.78, -s * 0.72, s * 0.95, s * 0.12, 0, s * 0.58)
    g.closePath()
    g.fill()
    // 瓣心淡筋
    g.strokeStyle = 'rgba(255,255,255,.35)'
    g.lineWidth = 1
    g.beginPath()
    g.moveTo(0, s * 0.4)
    g.quadraticCurveTo(-s * 0.08, 0, 0, -s * 0.38)
    g.stroke()
    return c
  })
}

function petalCount() {
  return Math.max(10, Math.min(26, Math.round(window.innerWidth / 60)))
}

function spawn(initial: boolean): Petal {
  return {
    x: Math.random() * width,
    y: initial ? Math.random() * height : -30 - Math.random() * 60,
    size: 8 + Math.random() * 10,
    fall: 22 + Math.random() * 30,          // px/s
    swayAmp: 14 + Math.random() * 26,
    swaySpeed: 0.4 + Math.random() * 0.8,
    phase: Math.random() * Math.PI * 2,
    rot: Math.random() * Math.PI * 2,
    rotSpeed: (Math.random() - 0.5) * 1.6,
    flipSpeed: 0.5 + Math.random() * 1.1,
    alpha: 0.45 + Math.random() * 0.4,
    sprite: Math.floor(Math.random() * sprites.length),
  }
}

function resize() {
  const canvas = canvasRef.value
  if (!canvas) return
  dpr = Math.min(window.devicePixelRatio || 1, 2)
  width = window.innerWidth
  height = window.innerHeight
  canvas.width = Math.round(width * dpr)
  canvas.height = Math.round(height * dpr)
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  ctx = canvas.getContext('2d')
  if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}

function frame(t: number) {
  if (!running) return
  const dt = Math.min((t - last) / 1000, 0.05)
  last = t
  if (ctx) {
    ctx.clearRect(0, 0, width, height)
    const time = t / 1000
    for (const p of petals) {
      p.y += p.fall * dt
      p.rot += p.rotSpeed * dt
      const x = p.x + Math.sin(time * p.swaySpeed + p.phase) * p.swayAmp
      const flip = 0.55 + 0.45 * Math.sin(time * p.flipSpeed + p.phase)
      if (p.y > height + 40) Object.assign(p, spawn(false))
      ctx.save()
      ctx.translate(x, p.y)
      ctx.rotate(p.rot)
      ctx.scale(flip, 1)
      ctx.globalAlpha = p.alpha
      const img = sprites[p.sprite]
      ctx.drawImage(img, -p.size / 2, -p.size / 2, p.size, p.size)
      ctx.restore()
    }
  }
  raf = requestAnimationFrame(frame)
}

function start() {
  if (running || reducedMotion.matches || !getPetalsEnabled()) return
  running = true
  visible.value = true
  resize()
  petals = Array.from({ length: petalCount() }, () => spawn(true))
  last = performance.now()
  raf = requestAnimationFrame(frame)
}

function stop() {
  running = false
  visible.value = false
  cancelAnimationFrame(raf)
  if (ctx) ctx.clearRect(0, 0, width, height)
}

function onToggle(e: Event) {
  const on = (e as CustomEvent<boolean>).detail
  if (on) start()
  else stop()
}
function onStorage(e: StorageEvent) {
  if (e.key === 'gf-petals') (e.newValue === 'off' ? stop : start)()
}
function onMotionChange() {
  if (reducedMotion.matches) stop()
  else start()
}
function onResize() {
  if (running) resize()
}

onMounted(() => {
  makeSprites()
  start()
  window.addEventListener(GF_PETALS_EVENT, onToggle)
  window.addEventListener('storage', onStorage)
  window.addEventListener('resize', onResize, { passive: true })
  reducedMotion.addEventListener('change', onMotionChange)
})

onUnmounted(() => {
  stop()
  window.removeEventListener(GF_PETALS_EVENT, onToggle)
  window.removeEventListener('storage', onStorage)
  window.removeEventListener('resize', onResize)
  reducedMotion.removeEventListener('change', onMotionChange)
})
</script>

<template>
  <canvas v-show="visible" ref="canvasRef" class="petal-fall" aria-hidden="true"></canvas>
</template>

<style scoped>
.petal-fall {
  position: fixed;
  inset: 0;
  z-index: 1;
  pointer-events: none;
}
</style>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { apiGet, apiPost, apiPut } from '@/api/platform'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import { getPetalsEnabled, setPetalsEnabled } from '@/components/gf/shared'

declare global {
  interface Window {
    desktopAPI?: {
      setAutostart?: (enable: boolean) => unknown
      setPreventSleep?: (enable: boolean) => unknown
    }
    wanweiDesktop?: {
      getAutostart?: () => Promise<boolean>
      setAutostart?: (enable: boolean) => unknown
    }
  }
}

type ThemeChoice = 'day' | 'night' | 'system'
type LangChoice = 'zh' | 'en'

interface SystemSettings {
  theme?: string
  lang?: string
  petals?: boolean
  background_image?: string
  autostart?: boolean
  prevent_sleep?: boolean
}

interface LanStatus {
  enabled?: boolean
  lan_url?: string
  qr_payload?: string
  message?: string
  simulated?: boolean
}

interface EmulatorDownload {
  id: string
  name?: string
  version?: string
  size?: string
  progress?: number
  status?: string
  simulated?: boolean
}

const THEME_KEY = 'gf-theme'
const LANG_KEY = 'gf-lang'
const BG_KEY = 'gf-bg'
const BG_STYLE_ID = 'gf-bg-veil'

const themeOptions: { value: ThemeChoice; label: string; hint: string }[] = [
  { value: 'day', label: '宣纸白昼', hint: '明亮宣纸底色，宜日间伏案' },
  { value: 'night', label: '靛夜灯影', hint: '靛青夜色，宜灯下长耕' },
  { value: 'system', label: '跟随系统', hint: '随操作系统明暗自动切换' },
]
const langOptions: { value: LangChoice; label: string }[] = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
]

/* ── 基础状态 ── */
const theme = ref<ThemeChoice>(readTheme())
const lang = ref<LangChoice>(readLang())
const petalsOn = ref(getPetalsEnabled())
const autostart = ref(false)
const preventSleep = ref(false)
const bgDataUrl = shallowRef('')
const bgInput = ref<HTMLInputElement | null>(null)

const settingsOffline = ref(false)
const savingKey = shallowRef('')
const notice = shallowRef('')
const error = shallowRef('')

const lanStatus = shallowRef<LanStatus | null>(null)
const lanBusy = shallowRef(false)
const lanOffline = ref(false)

const downloads = shallowRef<EmulatorDownload[]>([])
const emuLoading = ref(true)
const emuOffline = ref(false)
const emuBusyId = shallowRef('')

const FALLBACK_DOWNLOADS: EmulatorDownload[] = [
  { id: 'emulator-base-image', name: '麒麟 Linux 模拟器基础镜像', version: '1.0', size: '约 2.4 GB', progress: 0, status: '未开始', simulated: true },
  { id: 'emulator-dev-toolchain', name: '开发工具链扩展包', version: '0.9', size: '约 860 MB', progress: 42, status: '已暂停', simulated: true },
]

/* ── 主题 / 语言 ── */
function readTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_KEY)
    if (v === 'night' || v === 'system') return v
  } catch { /* 隐私模式下静默 */ }
  return 'day'
}

function resolveTheme(choice: ThemeChoice): 'day' | 'night' {
  if (choice === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'night' : 'day'
  }
  return choice
}

function applyThemeChoice(choice: ThemeChoice) {
  document.documentElement.dataset.theme = resolveTheme(choice)
  try { localStorage.setItem(THEME_KEY, choice) } catch { /* ignore */ }
}

const systemThemeMq = window.matchMedia('(prefers-color-scheme: dark)')
function onSystemThemeChange() {
  if (theme.value === 'system') applyThemeChoice('system')
}

function selectTheme(choice: ThemeChoice) {
  theme.value = choice
  applyThemeChoice(choice)
  persistSettings({ theme: choice })
}

function readLang(): LangChoice {
  try { if (localStorage.getItem(LANG_KEY) === 'en') return 'en' } catch { /* ignore */ }
  return 'zh'
}

function applyLang(choice: LangChoice) {
  document.documentElement.lang = choice === 'en' ? 'en' : 'zh-CN'
  try { localStorage.setItem(LANG_KEY, choice) } catch { /* ignore */ }
}

function selectLang(choice: LangChoice) {
  lang.value = choice
  applyLang(choice)
  persistSettings({ lang: choice })
}

function togglePetals() {
  petalsOn.value = !petalsOn.value
  setPetalsEnabled(petalsOn.value)
  persistSettings({ petals: petalsOn.value })
}

/* ── 设置持久化（容错：离线时仅本机生效） ── */
async function persistSettings(patch: Record<string, unknown>) {
  savingKey.value = Object.keys(patch)[0] ?? ''
  try {
    await apiPut('/system/settings', patch)
    settingsOffline.value = false
  } catch {
    settingsOffline.value = true
    notice.value = '后端暂不可达，偏好已保存在本机浏览器。'
  } finally {
    savingKey.value = ''
  }
}

/* ── 背景图 ── */
function pickBackground() {
  bgInput.value?.click()
}

function downscaleImage(file: File, maxWidth: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('read failed'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('decode failed'))
      img.onload = () => {
        const scale = img.width > maxWidth ? maxWidth / img.width : 1
        const w = Math.max(1, Math.round(img.width * scale))
        const h = Math.max(1, Math.round(img.height * scale))
        const canvas = document.createElement('canvas')
        canvas.width = w
        canvas.height = h
        const ctx = canvas.getContext('2d')
        if (!ctx) { reject(new Error('canvas unavailable')); return }
        ctx.drawImage(img, 0, 0, w, h)
        resolve(canvas.toDataURL('image/jpeg', 0.85))
      }
      img.src = String(reader.result)
    }
    reader.readAsDataURL(file)
  })
}

function applyBodyBackground(dataUrl: string) {
  removeBodyBackground()
  const style = document.createElement('style')
  style.id = BG_STYLE_ID
  style.textContent = `body::before{content:'';position:fixed;inset:0;z-index:-1;pointer-events:none;background-image:url("${dataUrl}");background-size:cover;background-position:center;opacity:.8;}`
  document.head.appendChild(style)
  document.body.dataset.gfBg = 'on'
}

function removeBodyBackground() {
  document.getElementById(BG_STYLE_ID)?.remove()
  delete document.body.dataset.gfBg
}

async function onBackgroundFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) { error.value = '请选择图片文件。'; return }
  error.value = ''
  try {
    const dataUrl = await downscaleImage(file, 1600)
    bgDataUrl.value = dataUrl
    applyBodyBackground(dataUrl)
    try {
      localStorage.setItem(BG_KEY, dataUrl)
    } catch {
      notice.value = '图片体积较大，未能写入浏览器存储，仅本次会话生效。'
    }
    await persistSettings({ background_image: dataUrl })
    notice.value = '背景已应用，透明度固定 80%。'
  } catch {
    error.value = '图片读取失败，请换一张试试。'
  }
}

async function resetBackground() {
  bgDataUrl.value = ''
  removeBodyBackground()
  try { localStorage.removeItem(BG_KEY) } catch { /* ignore */ }
  await persistSettings({ background_image: '' })
  notice.value = '已恢复默认宣纸底纹。'
}

/* ── 系统：自启动 / 防睡眠 ── */
async function toggleAutostart() {
  const next = !autostart.value
  autostart.value = next
  try { window.desktopAPI?.setAutostart?.(next) } catch { /* ignore */ }
  try { window.wanweiDesktop?.setAutostart?.(next) } catch { /* ignore */ }
  await persistSettings({ autostart: next })
}

async function togglePreventSleep() {
  const next = !preventSleep.value
  preventSleep.value = next
  try { window.desktopAPI?.setPreventSleep?.(next) } catch { /* ignore */ }
  try {
    await apiPut('/system/power', { prevent_sleep: next })
    settingsOffline.value = false
  } catch {
    settingsOffline.value = true
    notice.value = '电源偏好后端暂不可达，已记录本机选择。'
  }
}

/* ── 局域网手机控制 ── */
async function loadLanStatus() {
  try {
    lanStatus.value = await apiGet<LanStatus>('/system/lan/status')
    lanOffline.value = false
  } catch {
    lanOffline.value = true
    lanStatus.value = { enabled: false, simulated: true, message: '后端暂不可达，以下为占位状态。' }
  }
}

async function enableLan() {
  if (lanBusy.value) return
  lanBusy.value = true
  try {
    const res = await apiPost<LanStatus>('/system/lan/enable')
    lanStatus.value = { ...res, enabled: res.enabled ?? true }
    lanOffline.value = false
    notice.value = '局域网访问已开启，手机浏览器打开下方地址即可。'
  } catch {
    lanOffline.value = true
    notice.value = '局域网服务开启失败：后端暂不可达或未配置。'
  } finally {
    lanBusy.value = false
  }
}

async function disableLan() {
  if (lanBusy.value) return
  lanBusy.value = true
  try {
    await apiPost('/system/lan/disable')
    lanStatus.value = { enabled: false }
    lanOffline.value = false
  } catch {
    lanOffline.value = true
    notice.value = '局域网服务关闭失败：后端暂不可达。'
  } finally {
    lanBusy.value = false
  }
}

/* ── 开发模拟器下载 ── */
function normalizeDownload(raw: EmulatorDownload, index: number): EmulatorDownload {
  const progress = typeof raw.progress === 'number' && Number.isFinite(raw.progress)
    ? Math.min(100, Math.max(0, Math.round(raw.progress)))
    : 0
  return {
    id: raw.id || `dl-${index}`,
    name: raw.name || '未命名镜像',
    version: raw.version ?? '',
    size: raw.size ?? '',
    progress,
    status: raw.status || '未知',
    simulated: raw.simulated,
  }
}

async function loadDownloads() {
  emuLoading.value = true
  try {
    const res = await apiGet<{ items?: EmulatorDownload[] } | EmulatorDownload[]>('/system/emulator/downloads')
    const items = Array.isArray(res) ? res : (res.items ?? [])
    downloads.value = items.map(normalizeDownload)
    emuOffline.value = false
  } catch {
    emuOffline.value = true
    downloads.value = FALLBACK_DOWNLOADS
  } finally {
    emuLoading.value = false
  }
}

async function startDownload(item: EmulatorDownload) {
  if (emuBusyId.value) return
  emuBusyId.value = item.id
  try {
    await apiPost(`/system/emulator/downloads/${encodeURIComponent(item.id)}/start`)
    await loadDownloads()
  } catch {
    notice.value = '下载服务暂不可达：模拟器镜像下载为配置就绪后启用的能力。'
  } finally {
    emuBusyId.value = ''
  }
}

async function cancelDownload(item: EmulatorDownload) {
  if (emuBusyId.value) return
  emuBusyId.value = item.id
  try {
    await apiPost(`/system/emulator/downloads/${encodeURIComponent(item.id)}/cancel`)
    await loadDownloads()
  } catch {
    notice.value = '下载服务暂不可达：取消指令未能送达。'
  } finally {
    emuBusyId.value = ''
  }
}

/* ── 装载 ── */
async function loadSettings() {
  try {
    const s = await apiGet<SystemSettings>('/system/settings')
    settingsOffline.value = false
    if (s.theme === 'day' || s.theme === 'night' || s.theme === 'system') {
      theme.value = s.theme
      applyThemeChoice(s.theme)
    }
    if (s.lang === 'zh' || s.lang === 'en') {
      lang.value = s.lang
      applyLang(s.lang)
    }
    if (typeof s.petals === 'boolean' && s.petals !== petalsOn.value) {
      petalsOn.value = s.petals
      setPetalsEnabled(s.petals)
    }
    if (typeof s.autostart === 'boolean') autostart.value = s.autostart
    if (typeof s.prevent_sleep === 'boolean') preventSleep.value = s.prevent_sleep
    if (typeof s.background_image === 'string' && s.background_image && !bgDataUrl.value) {
      bgDataUrl.value = s.background_image
    }
  } catch {
    settingsOffline.value = true
  }
}

onMounted(() => {
  systemThemeMq.addEventListener('change', onSystemThemeChange)
  applyThemeChoice(theme.value)
  applyLang(lang.value)
  try {
    const storedBg = localStorage.getItem(BG_KEY)
    if (storedBg) bgDataUrl.value = storedBg
  } catch { /* ignore */ }
  loadSettings().finally(() => {
    if (bgDataUrl.value) applyBodyBackground(bgDataUrl.value)
  })
  loadLanStatus()
  loadDownloads()
  const desktop = window.wanweiDesktop
  if (desktop?.getAutostart) {
    desktop.getAutostart()
      .then((v) => { if (typeof v === 'boolean') autostart.value = v })
      .catch(() => { /* 桌面端不可达时忽略 */ })
  }
})

onUnmounted(() => {
  systemThemeMq.removeEventListener('change', onSystemThemeChange)
  removeBodyBackground()
})
</script>

<template>
  <div>
    <PageHero
      seal="设"
      title="通用设置"
      en="SETTINGS"
      sub="主题、背景、系统行为与局域网控制。偏好即刻写入本机；后端离线时自动退为浏览器本地保存。"
    />

    <div v-if="error" class="notice error" role="alert" aria-live="polite">
      <span class="notice-text">{{ error }}</span>
      <GfButton variant="ghost" small @click="error = ''">知道了</GfButton>
    </div>
    <div v-else-if="notice" class="notice info" role="status" aria-live="polite">
      <span class="notice-text">{{ notice }}</span>
      <GfButton variant="ghost" small @click="notice = ''">知道了</GfButton>
    </div>

    <div class="grid">
      <!-- ══ 外观 ══ -->
      <GfCard title="外观" seal="观">
        <div class="block">
          <div class="block-label">界面主题</div>
          <div class="segmented" role="group" aria-label="界面主题">
            <button
              v-for="opt in themeOptions"
              :key="opt.value"
              type="button"
              class="seg-btn"
              :class="{ active: theme === opt.value }"
              :aria-pressed="theme === opt.value"
              :title="opt.hint"
              @click="selectTheme(opt.value)"
            >{{ opt.label }}</button>
          </div>
          <p class="hint">「跟随系统」将随操作系统明暗自动切换，并同步写入本机设置。</p>
        </div>

        <div class="block">
          <div class="block-label">界面语言</div>
          <div class="segmented" role="group" aria-label="界面语言">
            <button
              v-for="opt in langOptions"
              :key="opt.value"
              type="button"
              class="seg-btn"
              :class="{ active: lang === opt.value }"
              :aria-pressed="lang === opt.value"
              @click="selectLang(opt.value)"
            >{{ opt.label }}</button>
          </div>
          <p class="hint">语言偏好已记录；当前界面文案以中文为主，English 翻译逐步覆盖中。</p>
        </div>

        <div class="row">
          <div class="row-txt">
            <b>花瓣雨</b>
            <p>全站飘落的梅花瓣氛围层，关闭后更素净。</p>
          </div>
          <button class="switch" type="button" role="switch" :aria-checked="petalsOn" :class="{ on: petalsOn }" title="花瓣雨开关" @click="togglePetals">
            <span class="knob"></span>
          </button>
        </div>
      </GfCard>

      <!-- ══ 背景 ══ -->
      <GfCard title="软件背景" seal="景">
        <p class="hint">选择一张图片作为软件背景，将自动缩放至宽度不超过 1600 像素后保存。</p>
        <div class="bg-actions">
          <GfButton small :disabled="!!savingKey" @click="pickBackground">选择图片…</GfButton>
          <GfButton v-if="bgDataUrl" variant="ghost" small :disabled="!!savingKey" @click="resetBackground">恢复默认</GfButton>
          <input ref="bgInput" type="file" accept="image/*" class="visually-hidden" aria-label="选择背景图片" @change="onBackgroundFile" />
        </div>
        <div v-if="bgDataUrl" class="bg-preview">
          <img :src="bgDataUrl" alt="自定义背景预览" />
          <div class="bg-caption">
            <GfTag tone="gold">透明度固定 80%</GfTag>
            <span>离开本页后背景不再强制挂载，避免影响其他页面。</span>
          </div>
        </div>
        <GfEmpty v-else text="尚无自定义背景，默认为宣纸底纹。" />
      </GfCard>

      <!-- ══ 系统 ══ -->
      <GfCard title="系统" seal="统">
        <div class="row">
          <div class="row-txt">
            <b>开机自启动</b>
            <p>登录操作系统后自动唤起宛委·万枢桌面端。</p>
          </div>
          <button class="switch" type="button" role="switch" :aria-checked="autostart" :class="{ on: autostart }" title="开机自启动开关" @click="toggleAutostart">
            <span class="knob"></span>
          </button>
        </div>
        <p class="hint">说明：「登录自动启动」指你登录系统账户后，桌面端随之启动；麒麟 Linux 下通过 autostart 桌面条目实现，浏览器直接访问方式不受此开关影响。</p>

        <div class="row">
          <div class="row-txt">
            <b>任务运行期间阻止电脑睡眠</b>
            <p>有任务在执行时保持唤醒，任务结束后恢复系统电源策略。</p>
          </div>
          <button class="switch" type="button" role="switch" :aria-checked="preventSleep" :class="{ on: preventSleep }" title="阻止睡眠开关" @click="togglePreventSleep">
            <span class="knob"></span>
          </button>
        </div>
        <p v-if="settingsOffline" class="hint">当前后端离线：以上选择暂存于本机浏览器，联机后将以此为准重新写入。</p>
      </GfCard>

      <!-- ══ 局域网手机控制 ══ -->
      <GfCard title="局域网手机控制" seal="联">
        <div class="row">
          <div class="row-txt">
            <b>服务状态</b>
            <p>开启后，同一局域网内的手机可浏览器访问控制台。</p>
          </div>
          <GfTag :tone="lanStatus?.enabled ? 'bamboo' : 'ink'">{{ lanStatus?.enabled ? '已开启' : '已关闭' }}</GfTag>
        </div>
        <div class="bg-actions">
          <GfButton small :disabled="lanBusy || !!lanStatus?.enabled" @click="enableLan">{{ lanBusy ? '处理中…' : '开启' }}</GfButton>
          <GfButton variant="ghost" small :disabled="lanBusy || !lanStatus?.enabled" @click="disableLan">关闭</GfButton>
          <GfTag v-if="lanOffline || lanStatus?.simulated" tone="gold">离线占位</GfTag>
        </div>

        <div v-if="lanStatus?.enabled && (lanStatus.lan_url || lanStatus.qr_payload)" class="lan-panel">
          <div class="qr-box" aria-hidden="true">
            <svg viewBox="0 0 96 96" width="96" height="96">
              <rect x="6" y="6" width="26" height="26" class="qr-eye" />
              <rect x="64" y="6" width="26" height="26" class="qr-eye" />
              <rect x="6" y="64" width="26" height="26" class="qr-eye" />
              <rect x="12" y="12" width="14" height="14" class="qr-eye-in" />
              <rect x="70" y="12" width="14" height="14" class="qr-eye-in" />
              <rect x="12" y="70" width="14" height="14" class="qr-eye-in" />
              <rect x="42" y="8" width="8" height="8" class="qr-dot" />
              <rect x="56" y="20" width="8" height="8" class="qr-dot" />
              <rect x="42" y="34" width="8" height="8" class="qr-dot" />
              <rect x="8" y="42" width="8" height="8" class="qr-dot" />
              <rect x="26" y="48" width="8" height="8" class="qr-dot" />
              <rect x="48" y="48" width="8" height="8" class="qr-dot" />
              <rect x="68" y="42" width="8" height="8" class="qr-dot" />
              <rect x="84" y="52" width="8" height="8" class="qr-dot" />
              <rect x="42" y="66" width="8" height="8" class="qr-dot" />
              <rect x="58" y="78" width="8" height="8" class="qr-dot" />
              <rect x="76" y="70" width="8" height="8" class="qr-dot" />
            </svg>
            <GfTag tone="gold">二维码占位</GfTag>
          </div>
          <div class="lan-txt">
            <p class="lan-tip">手机浏览器打开此地址：</p>
            <code class="lan-url">{{ lanStatus.lan_url || lanStatus.qr_payload }}</code>
            <p v-if="lanStatus.qr_payload && lanStatus.lan_url" class="hint">扫码内容：{{ lanStatus.qr_payload }}</p>
            <p class="hint">真实二维码渲染尚未接入，当前为占位图案。</p>
          </div>
        </div>
        <p v-else-if="lanStatus?.message" class="hint">{{ lanStatus.message }}</p>
      </GfCard>

      <!-- ══ 开发模拟器 ══ -->
      <GfCard title="开发模拟器" seal="拟" class="span-2">
        <p class="hint">
          模拟器镜像下载为「配置就绪才启用」的能力；后端未就绪时展示离线示例，不产生真实下载。
          <GfTag v-if="emuOffline" tone="gold">离线示例</GfTag>
        </p>
        <div v-if="emuLoading" class="muted">研墨中…</div>
        <template v-else>
          <div v-if="downloads.length" class="dl-list">
            <article v-for="item in downloads" :key="item.id" class="dl-row">
              <div class="dl-head">
                <div class="dl-name">
                  <b>{{ item.name }}</b>
                  <span v-if="item.version" class="dl-meta">v{{ item.version }}</span>
                  <span v-if="item.size" class="dl-meta">{{ item.size }}</span>
                  <GfTag v-if="item.simulated" tone="gold">示例</GfTag>
                </div>
                <GfTag :tone="(item.progress ?? 0) >= 100 ? 'bamboo' : 'dai'">{{ item.status }}</GfTag>
              </div>
              <div class="progress" role="progressbar" :aria-valuenow="item.progress ?? 0" aria-valuemin="0" aria-valuemax="100" :aria-label="`${item.name} 下载进度`">
                <div class="progress-bar" :style="{ width: `${item.progress ?? 0}%` }"></div>
              </div>
              <div class="dl-foot">
                <span class="dl-meta">{{ item.progress ?? 0 }}%</span>
                <div class="button-row">
                  <GfButton variant="ghost" small :disabled="!!emuBusyId || (item.progress ?? 0) >= 100" @click="startDownload(item)">
                    {{ emuBusyId === item.id ? '发送中…' : (item.progress ?? 0) > 0 ? '继续' : '开始' }}
                  </GfButton>
                  <GfButton variant="danger" small :disabled="!!emuBusyId || (item.progress ?? 0) === 0 || (item.progress ?? 0) >= 100" @click="cancelDownload(item)">取消</GfButton>
                </div>
              </div>
            </article>
          </div>
          <GfEmpty v-else text="暂无可下载的模拟器镜像。" />
        </template>
      </GfCard>
    </div>
  </div>
</template>

<style scoped>
.notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0 0 18px;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  font-size: 12px;
}
.notice.error {
  color: var(--cinnabar-deep);
  border-color: var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 7%, transparent);
}
.notice.info {
  color: var(--dai-deep);
  border-color: color-mix(in srgb, var(--dai) 32%, transparent);
  background: color-mix(in srgb, var(--dai) 7%, transparent);
}
.notice-text { line-height: 1.6; }
.muted { color: var(--ink-soft); font-size: 13px; padding: 14px 0; font-family: var(--font-kai); letter-spacing: 2px; }

.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.span-2 { grid-column: span 2; }

.block { padding-bottom: 14px; margin-bottom: 4px; }
.block-label { font-family: var(--font-kai); font-size: 14px; letter-spacing: 2px; color: var(--ink); margin-bottom: 8px; }
.hint { font-size: 11px; color: var(--ink-muted); line-height: 1.7; margin-top: 8px; letter-spacing: .5px; }

/* ── 分段选择 ── */
.segmented {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--bg-soft);
}
.seg-btn {
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--ink-soft);
  padding: 6px 16px;
  font-size: 12px;
  font-family: var(--font-kai);
  letter-spacing: 2px;
  cursor: pointer;
  transition: background .18s ease, color .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.seg-btn:hover { color: var(--cinnabar); }
.seg-btn.active {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: 0 2px 10px var(--cinnabar-glow);
}

/* ── 行 + 开关 ── */
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 0;
  border-top: 1px solid var(--line-soft);
}
.row-txt b { font-size: 13px; color: var(--ink); letter-spacing: 1px; }
.row-txt p { font-size: 11px; color: var(--ink-muted); margin-top: 4px; line-height: 1.6; }
.switch {
  flex-shrink: 0;
  width: 46px;
  height: 25px;
  border-radius: 999px;
  border: 1px solid var(--gold-line);
  background: var(--line-soft);
  position: relative;
  cursor: pointer;
  transition: background .2s ease, border-color .2s ease, box-shadow .2s ease;
}
.switch:hover { box-shadow: var(--shadow-glow-rouge); }
.switch.on { background: color-mix(in srgb, var(--bamboo) 55%, transparent); border-color: var(--bamboo); }
.knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 19px;
  height: 19px;
  border-radius: 50%;
  background: var(--card-solid);
  box-shadow: var(--shadow-card);
  transition: transform .2s ease;
}
.switch.on .knob { transform: translateX(21px); }

/* ── 背景卡 ── */
.bg-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 12px; }
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}
.bg-preview { margin-top: 14px; }
.bg-preview img {
  display: block;
  width: 100%;
  max-height: 220px;
  object-fit: cover;
  border-radius: var(--radius-small);
  border: 1px solid var(--line);
  opacity: .8;
}
.bg-caption { display: flex; align-items: center; gap: 10px; margin-top: 8px; font-size: 11px; color: var(--ink-muted); flex-wrap: wrap; }

/* ── 局域网 ── */
.lan-panel {
  display: flex;
  gap: 16px;
  align-items: center;
  margin-top: 14px;
  padding: 14px;
  border: 1px dashed var(--gold-line);
  border-radius: var(--radius-small);
  background: color-mix(in srgb, var(--gold) 5%, transparent);
  flex-wrap: wrap;
}
.qr-box {
  display: grid;
  place-items: center;
  gap: 6px;
  padding: 10px;
  border-radius: var(--radius-small);
  background: var(--card-solid);
  border: 1px solid var(--line);
}
.qr-eye { fill: none; stroke: var(--ink); stroke-width: 3; }
.qr-eye-in { fill: var(--ink); }
.qr-dot { fill: var(--ink-soft); }
.lan-txt { flex: 1; min-width: 220px; }
.lan-tip { font-family: var(--font-kai); font-size: 13px; letter-spacing: 2px; color: var(--ink); }
.lan-url {
  display: inline-block;
  margin-top: 6px;
  padding: 6px 12px;
  border-radius: var(--radius-small);
  border: 1px solid var(--line);
  background: var(--bg-soft);
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--dai);
  overflow-wrap: anywhere;
  user-select: all;
}

/* ── 模拟器下载 ── */
.dl-list { display: grid; gap: 12px; margin-top: 12px; }
.dl-row {
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  box-shadow: var(--shadow-card);
  padding: 14px;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.dl-row:hover { transform: translateY(-2px); box-shadow: var(--shadow-lift); border-color: var(--gold-line); }
.dl-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.dl-name { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.dl-name b { font-size: 13px; color: var(--ink); letter-spacing: 1px; }
.dl-meta { font-size: 11px; color: var(--ink-muted); font-family: var(--font-mono); }
.progress {
  margin-top: 10px;
  height: 8px;
  border-radius: 999px;
  background: var(--line-soft);
  border: 1px solid var(--line);
  overflow: hidden;
}
.progress-bar {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--dai), var(--bamboo));
  transition: width .3s ease;
}
.dl-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.button-row { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; }

@media (max-width: 980px) {
  .grid { grid-template-columns: 1fr; }
  .span-2 { grid-column: auto; }
}
</style>

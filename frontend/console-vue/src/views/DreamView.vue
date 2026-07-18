<script setup lang="ts">
/**
 * DreamView — 梦境日志「卷轴日志流」
 * POST /soul/dream 触发入梦（走 client.ts 追加的 soulDreamCycle，携带必填 task_id），
 * 梦境结果按 soul 存 localStorage，卷轴式铺展。
 */
import { onMounted, ref } from 'vue'
import PageHero from '@/components/gf/PageHero.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import { api, soulDreamCycle } from '@/api/client'

const SOUL_KEY = 'gf-soul-id'
const LOG_KEY = (id: string) => `gf-dream-log:${id}`

interface DreamEntry {
  time: string
  dream: Record<string, any>
}

const soulId = ref('')
const soulName = ref('枢忆')
const dreams = ref<DreamEntry[]>([])
const dreaming = ref(false)
const errorMsg = ref('')

function now(): string {
  return new Date().toLocaleString('zh-CN', { hour12: false })
}

function persist(): void {
  if (!soulId.value) return
  try {
    localStorage.setItem(LOG_KEY(soulId.value), JSON.stringify(dreams.value.slice(0, 50)))
  } catch { /* 存不下便作罢 */ }
}

function loadLog(id: string): void {
  try {
    const raw = localStorage.getItem(LOG_KEY(id))
    dreams.value = raw ? (JSON.parse(raw) as DreamEntry[]) : []
  } catch {
    dreams.value = []
  }
}

async function ensureSoul(): Promise<void> {
  const saved = localStorage.getItem(SOUL_KEY)
  if (saved) {
    soulId.value = saved
  } else {
    try {
      const res = await api.soulConnect()
      soulId.value = res.soul_id
      localStorage.setItem(SOUL_KEY, res.soul_id)
    } catch (e: any) {
      errorMsg.value = `结契未成：${e?.message || e}`
      return
    }
  }
  loadLog(soulId.value)
  try {
    const s = await api.soulState(soulId.value)
    if (s?.persona?.name) soulName.value = s.persona.name
  } catch { /* 名讳未取到，用默认 */ }
}

async function enterDream(): Promise<void> {
  if (!soulId.value || dreaming.value) return
  dreaming.value = true
  errorMsg.value = ''
  try {
    const res = await soulDreamCycle(soulId.value)
    dreams.value.unshift({ time: now(), dream: res?.dream ?? {} })
    persist()
  } catch (e: any) {
    errorMsg.value = `入梦未成：${e?.message || e}`
  } finally {
    dreaming.value = false
  }
}

function clearDreams(): void {
  dreams.value = []
  persist()
}

/* 梦境成果条目（后端字段若缺省则为 0） */
function dreamStats(d: Record<string, any>): { label: string; value: number }[] {
  return [
    { label: '新缘', value: Number(d.new_edges ?? 0) },
    { label: '合卷', value: Number(d.merged_capsules ?? 0) },
    { label: '删芜', value: Number(d.pruned_capsules ?? 0) },
    { label: '顿悟', value: Number(d.synthesized_insights ?? 0) },
    { label: '化情', value: Number(d.emotional_events_digested ?? 0) },
  ]
}

function statusTone(status: string): 'bamboo' | 'gold' | 'ink' {
  if (status === 'ok' || status === 'done') return 'bamboo'
  if (status === 'placeholder') return 'gold'
  return 'ink'
}

onMounted(ensureSoul)
</script>

<template>
  <div class="dream-view">
    <PageHero
      seal="梦"
      title="梦境日志"
      en="Dream Scroll"
      sub="卷轴展梦 · 夜阑织忆。每一次入梦，都是记忆的低语重整。"
    />

    <p v-if="errorMsg" class="dream-error">{{ errorMsg }}</p>

    <!-- 入梦操作行 -->
    <div class="dream-bar">
      <div class="db-soul">
        <span class="db-moon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18">
            <path d="M15 3 A9.5 9.5 0 1 0 21 15 A7.6 7.6 0 0 1 15 3 Z" fill="var(--gold)" opacity=".85" />
          </svg>
        </span>
        <span class="db-text">
          {{ soulId ? `${soulName} · ${soulId}` : '尚未结契' }}
        </span>
      </div>
      <div class="db-actions">
        <GfButton v-if="dreams.length" variant="ghost" small @click="clearDreams">焚卷</GfButton>
        <GfButton :disabled="dreaming || !soulId" @click="enterDream">
          {{ dreaming ? '入梦中…' : '今夜入梦' }}
        </GfButton>
      </div>
    </div>

    <!-- 卷轴流 -->
    <div v-if="dreams.length" class="scroll-flow">
      <TransitionGroup name="unroll">
        <article v-for="(entry, i) in dreams" :key="entry.time + i" class="scroll-item">
          <!-- 卷轴天杆 -->
          <div class="scroll-rod" aria-hidden="true"><span class="rod-knob"></span><span class="rod-body"></span><span class="rod-knob"></span></div>

          <div class="scroll-paper">
            <header class="sp-head">
              <span class="sp-seal">梦</span>
              <div class="sp-title">
                <span class="sp-no">第 {{ dreams.length - i }} 梦</span>
                <span class="sp-time">{{ entry.time }}</span>
              </div>
              <GfTag :tone="statusTone(entry.dream.status || '')">{{ entry.dream.status || '未知' }}</GfTag>
            </header>

            <div class="sp-stats">
              <div v-for="s in dreamStats(entry.dream)" :key="s.label" class="sp-stat">
                <span class="sp-stat-value">{{ s.value }}</span>
                <span class="sp-stat-label">{{ s.label }}</span>
              </div>
            </div>

            <p class="sp-note">
              梦中重整记忆卷帙：缔新缘、合旧卷、删芜杂、得顿悟、化余情。
            </p>
          </div>

          <!-- 卷轴地杆 -->
          <div class="scroll-rod scroll-rod--bottom" aria-hidden="true"><span class="rod-knob"></span><span class="rod-body"></span><span class="rod-knob"></span></div>
        </article>
      </TransitionGroup>
    </div>

    <GfEmpty v-else-if="!dreaming" text="长夜未眠 · 尚无梦境可展" />

    <div v-if="dreaming" class="dreaming-hint">
      <span class="dh-moon"></span>
      <span class="dh-text">{{ soulName }} 正在入眠，记忆于月下悄然重织…</span>
    </div>
  </div>
</template>

<style scoped>
.dream-view { padding-bottom: 24px; }

.dream-error {
  margin-bottom: 14px;
  padding: 10px 16px;
  border-radius: var(--radius-small);
  border: 1px solid color-mix(in srgb, var(--cinnabar) 40%, transparent);
  background: color-mix(in srgb, var(--cinnabar) 8%, transparent);
  color: var(--cinnabar);
  font-size: 13px;
  letter-spacing: 1px;
}

/* ── 入梦操作行 ── */
.dream-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 20px;
  padding: 12px 18px;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: var(--shadow-card);
}
.db-soul { display: flex; align-items: center; gap: 10px; min-width: 0; }
.db-moon { display: grid; place-items: center; filter: drop-shadow(0 0 6px var(--gold-line)); }
.db-text {
  font-family: var(--font-kai);
  font-size: 14px;
  letter-spacing: 2px;
  color: var(--ink-soft);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.db-actions { display: flex; gap: 10px; }

/* ── 卷轴流 ── */
.scroll-flow {
  display: grid;
  gap: 26px;
  max-width: 760px;
  margin: 0 auto;
}

.scroll-item { display: grid; }

/* 天杆 / 地杆 */
.scroll-rod {
  display: flex;
  align-items: center;
  height: 12px;
  z-index: 1;
}
.rod-knob {
  width: 10px;
  height: 12px;
  border-radius: 4px;
  background: linear-gradient(180deg, var(--gold), var(--gold-line));
  box-shadow: 0 1px 3px rgba(0, 0, 0, .18);
  flex-shrink: 0;
}
.rod-body {
  flex: 1;
  height: 7px;
  border-radius: 999px;
  background: linear-gradient(180deg, var(--gold), color-mix(in srgb, var(--gold) 55%, var(--ink)));
  margin: 0 -2px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, .15);
}
.scroll-rod--bottom { transform: scaleY(-1); }

/* 卷心宣纸 */
.scroll-paper {
  position: relative;
  background: var(--card-solid);
  border: 1px solid var(--gold-line);
  border-radius: 6px;
  padding: 18px 22px 16px;
  box-shadow: var(--shadow-card);
}
.scroll-paper::before {
  content: '';
  position: absolute;
  inset: 5px;
  border: 1px solid var(--line-soft);
  border-radius: 4px;
  pointer-events: none;
}

.sp-head { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.sp-seal {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  font-family: var(--font-kai);
  font-size: 16px;
  font-weight: 700;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: 0 0 12px var(--cinnabar-glow);
  flex-shrink: 0;
}
.sp-title { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.sp-no { font-family: var(--font-kai); font-size: 17px; font-weight: 700; letter-spacing: 3px; color: var(--ink); }
.sp-time { font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px; color: var(--ink-muted); }

.sp-stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}
.sp-stat {
  display: grid;
  justify-items: center;
  gap: 2px;
  padding: 10px 4px 8px;
  border-radius: var(--radius-small);
  background: var(--line-soft);
}
.sp-stat-value {
  font-family: var(--font-kai);
  font-size: 22px;
  font-weight: 700;
  color: var(--dai);
  line-height: 1.1;
}
.sp-stat-label { font-size: 11px; letter-spacing: 2px; color: var(--ink-muted); }

.sp-note {
  font-size: 12px;
  line-height: 1.9;
  letter-spacing: 1px;
  color: var(--ink-muted);
  text-align: center;
}

/* 展卷动画 */
.unroll-enter-active { transition: opacity .4s ease, transform .4s ease; transform-origin: top center; }
.unroll-enter-from { opacity: 0; transform: scaleY(.6) translateY(-10px); }

/* 入梦提示 */
.dreaming-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 36px 0;
}
.dh-moon {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--gold);
  box-shadow: 0 0 18px var(--gold-line);
  animation: moonBreathe 1.8s ease-in-out infinite;
}
@keyframes moonBreathe {
  50% { transform: scale(.78); opacity: .6; }
}
.dh-text { font-family: var(--font-kai); font-size: 13px; letter-spacing: 3px; color: var(--ink-muted); }

@media (max-width: 640px) {
  .sp-stats { grid-template-columns: repeat(3, 1fr); }
}
</style>

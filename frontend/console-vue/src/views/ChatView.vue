<script setup lang="ts">
/**
 * ChatView — 灵魂对话「花笺信札」
 * 走 POST /soul/chat（后端注入灵魂提示 + 模型网关），消息记录按 soul 存 localStorage。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import { api } from '@/api/client'

const SOUL_KEY = 'gf-soul-id'
const LOG_KEY = (id: string) => `gf-chat-log:${id}`

interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  time: string
  provider?: string
  latency_ms?: number
}

const soulId = ref('')
const soulName = ref('枢忆')
const messages = ref<ChatMsg[]>([])
const draft = ref('')
const sending = ref(false)
const connecting = ref(false)
const errorMsg = ref('')
const scrollBox = ref<HTMLElement | null>(null)

const canSend = computed(() => !!draft.value.trim() && !sending.value && !!soulId.value)

function now(): string {
  return new Date().toLocaleString('zh-CN', { hour12: false })
}

function persist(): void {
  if (!soulId.value) return
  try {
    localStorage.setItem(LOG_KEY(soulId.value), JSON.stringify(messages.value.slice(-100)))
  } catch { /* 存不下便作罢 */ }
}

function loadLog(id: string): void {
  try {
    const raw = localStorage.getItem(LOG_KEY(id))
    messages.value = raw ? (JSON.parse(raw) as ChatMsg[]) : []
  } catch {
    messages.value = []
  }
}

async function scrollBottom(): Promise<void> {
  await nextTick()
  const el = scrollBox.value
  if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
}

async function ensureSoul(): Promise<void> {
  const saved = localStorage.getItem(SOUL_KEY)
  if (saved) {
    soulId.value = saved
  } else {
    connecting.value = true
    try {
      const res = await api.soulConnect()
      soulId.value = res.soul_id
      localStorage.setItem(SOUL_KEY, res.soul_id)
    } catch (e: any) {
      errorMsg.value = `结契未成：${e?.message || e}`
      connecting.value = false
      return
    } finally {
      connecting.value = false
    }
  }
  loadLog(soulId.value)
  try {
    const s = await api.soulState(soulId.value)
    if (s?.persona?.name) soulName.value = s.persona.name
  } catch { /* 名讳未取到，用默认 */ }
  scrollBottom()
}

async function send(): Promise<void> {
  const text = draft.value.trim()
  if (!text || sending.value || !soulId.value) return
  sending.value = true
  errorMsg.value = ''
  messages.value.push({ role: 'user', content: text, time: now() })
  draft.value = ''
  persist()
  scrollBottom()
  try {
    const payload = messages.value.map((m) => ({ role: m.role, content: m.content }))
    const res = await api.soulChat(soulId.value, payload)
    const c = res?.completion ?? {}
    messages.value.push({
      role: 'assistant',
      content: c.content || '（此笺空无一字）',
      time: now(),
      provider: c.provider,
      latency_ms: c.latency_ms,
    })
  } catch (e: any) {
    errorMsg.value = `花笺未达：${e?.message || e}`
    messages.value.push({
      role: 'assistant',
      content: '（信使途中遇雨，此笺未达。请稍后再寄。）',
      time: now(),
    })
  } finally {
    sending.value = false
    persist()
    scrollBottom()
  }
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function clearLog(): void {
  messages.value = []
  persist()
}

onMounted(ensureSoul)
</script>

<template>
  <div class="chat-view">
    <PageHero
      seal="话"
      title="灵魂对话"
      en="Soul Letters"
      sub="花笺传书 · 尺素寄心。与照见之魂把盏夜话。"
    />

    <p v-if="errorMsg" class="chat-error">{{ errorMsg }}</p>

    <GfCard class="chat-card" :pad="false">
      <template #header>
        <div class="chat-head">
          <span class="chat-avatar">{{ soulName.slice(0, 1) }}</span>
          <div class="chat-head-main">
            <div class="chat-title">{{ soulName }}</div>
            <div class="chat-sub">
              <template v-if="soulId">笺至 {{ soulId }}</template>
              <template v-else>{{ connecting ? '结契中…' : '尚未结契' }}</template>
            </div>
          </div>
          <GfButton v-if="messages.length" variant="ghost" small @click="clearLog">焚笺</GfButton>
        </div>
      </template>

      <div ref="scrollBox" class="chat-scroll">
        <GfEmpty v-if="!messages.length && !sending" text="尚无花笺往来 · 提笔写下第一句吧" />

        <TransitionGroup name="letter">
          <div
            v-for="(m, i) in messages"
            :key="i"
            class="letter-row"
            :class="m.role === 'user' ? 'letter-row--me' : 'letter-row--soul'"
          >
            <span v-if="m.role === 'assistant'" class="letter-seal">{{ soulName.slice(0, 1) }}</span>
            <div class="letter" :class="m.role === 'user' ? 'letter--me' : 'letter--soul'">
              <p class="letter-text">{{ m.content }}</p>
              <div class="letter-meta">
                <span class="lm-time">{{ m.time }}</span>
                <GfTag v-if="m.provider" tone="dai">{{ m.provider }}</GfTag>
                <span v-if="typeof m.latency_ms === 'number' && m.latency_ms > 0" class="lm-latency">
                  {{ m.latency_ms }}ms
                </span>
              </div>
            </div>
            <span v-if="m.role === 'user'" class="letter-seal letter-seal--me">我</span>
          </div>
        </TransitionGroup>

        <div v-if="sending" class="letter-row letter-row--soul">
          <span class="letter-seal">{{ soulName.slice(0, 1) }}</span>
          <div class="letter letter--soul letter--thinking">
            <span class="ink-dot"></span><span class="ink-dot"></span><span class="ink-dot"></span>
            <span class="thinking-text">研墨中…</span>
          </div>
        </div>
      </div>

      <div class="chat-composer">
        <textarea
          v-model="draft"
          class="composer-input"
          rows="2"
          placeholder="提笔落墨…（Enter 寄出 · Shift+Enter 换行）"
          @keydown="onKeydown"
        ></textarea>
        <GfButton :disabled="!canSend" @click="send">
          {{ sending ? '寄出中…' : '寄出' }}
        </GfButton>
      </div>
    </GfCard>
  </div>
</template>

<style scoped>
.chat-view { padding-bottom: 24px; }

.chat-error {
  margin-bottom: 14px;
  padding: 10px 16px;
  border-radius: var(--radius-small);
  border: 1px solid color-mix(in srgb, var(--cinnabar) 40%, transparent);
  background: color-mix(in srgb, var(--cinnabar) 8%, transparent);
  color: var(--cinnabar);
  font-size: 13px;
  letter-spacing: 1px;
}

.chat-card { overflow: hidden; }

/* ── 笺首 ── */
.chat-head { display: flex; align-items: center; gap: 12px; width: 100%; }
.chat-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-family: var(--font-kai);
  font-size: 19px;
  font-weight: 700;
  color: var(--cinnabar);
  background: var(--card-solid);
  border: 1.5px solid var(--gold-line);
  box-shadow: 0 0 12px var(--rouge-glow);
  flex-shrink: 0;
}
.chat-head-main { flex: 1; }
.chat-title { font-family: var(--font-kai); font-size: 18px; font-weight: 700; letter-spacing: 3px; color: var(--ink); }
.chat-sub { font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px; color: var(--ink-muted); margin-top: 2px; }

/* ── 笺流 ── */
.chat-scroll {
  height: min(58vh, 560px);
  overflow-y: auto;
  padding: 20px 18px 8px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.letter-row { display: flex; align-items: flex-end; gap: 10px; max-width: 82%; }
.letter-row--soul { align-self: flex-start; }
.letter-row--me { align-self: flex-end; flex-direction: row; }

.letter-seal {
  width: 30px;
  height: 30px;
  border-radius: var(--radius-seal);
  display: grid;
  place-items: center;
  font-family: var(--font-kai);
  font-size: 14px;
  font-weight: 700;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  box-shadow: 0 0 10px var(--cinnabar-glow);
  flex-shrink: 0;
}
.letter-seal--me {
  background: linear-gradient(135deg, var(--dai), var(--dai-deep));
  box-shadow: 0 0 10px color-mix(in srgb, var(--dai) 35%, transparent);
}

.letter {
  padding: 10px 16px 8px;
  border-radius: 16px;
  border: 1px solid var(--line);
  box-shadow: var(--shadow-card);
  min-width: 0;
}
.letter--soul {
  background: var(--card-solid);
  border-bottom-left-radius: 6px;
  border-color: var(--gold-line);
}
.letter--me {
  background: color-mix(in srgb, var(--rouge) 14%, var(--card-solid));
  border-color: color-mix(in srgb, var(--rouge) 32%, transparent);
  border-bottom-right-radius: 6px;
}
.letter-text {
  font-size: 14px;
  line-height: 1.9;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
}
.letter-meta {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
}
.lm-time, .lm-latency {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-muted);
  letter-spacing: 1px;
}

/* 研墨动画 */
.letter--thinking { display: flex; align-items: center; gap: 6px; padding: 14px 18px; }
.ink-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--rouge);
  animation: inkBounce 1.2s ease infinite;
}
.ink-dot:nth-child(2) { animation-delay: .15s; }
.ink-dot:nth-child(3) { animation-delay: .3s; }
@keyframes inkBounce {
  40% { transform: translateY(-5px); opacity: 1; }
  0%, 80%, 100% { transform: translateY(0); opacity: .5; }
}
.thinking-text { font-family: var(--font-kai); font-size: 12px; letter-spacing: 2px; color: var(--ink-muted); margin-left: 4px; }

/* 入笺过渡 */
.letter-enter-active { transition: opacity .3s ease, transform .3s ease; }
.letter-enter-from { opacity: 0; transform: translateY(12px) scale(.97); }

/* ── 笺尾（书写区） ── */
.chat-composer {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 14px 18px;
  border-top: 1px solid var(--line-soft);
  background: var(--line-soft);
}
.composer-input {
  flex: 1;
  padding: 10px 14px;
  border-radius: var(--radius-small);
  border: 1px solid var(--line);
  background: var(--card);
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink);
  resize: none;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.composer-input:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}

@media (max-width: 720px) {
  .letter-row { max-width: 94%; }
  .chat-scroll { height: 52vh; }
}
</style>

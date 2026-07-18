<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiGet, apiPost, apiPut } from '@/api/platform'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfStat from '@/components/gf/GfStat.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

const MAX_LINES = 200

interface DreamNight {
  key: string
  date: string
  summary: string
  topics: string[]
}

interface RememberFeedback {
  ok: boolean
  text: string
  evicted: string[]
}

/* ── 离线兜底示例数据 ── */
const FALLBACK_LINES = [
  '回答一律使用中文，语气温和',
  '修改代码前先说明改动理由',
  '引用外部数据时标注来源与日期',
]
const FALLBACK_DREAMS: DreamNight[] = [
  {
    key: 'demo-1',
    date: '示例·前夜',
    summary: '整理了近日对话：模型网关联调收尾，控制台夜间主题定稿，常用语新增三条。',
    topics: ['模型网关', '夜间主题', '常用语'],
  },
  {
    key: 'demo-2',
    date: '示例·前二夜',
    summary: '沉淀了记忆中枢的使用约定：指令上限二百行，写满后挤出最早条目；梦境按夜归档成卷。',
    topics: ['记忆指令', '梦境归档'],
  },
]

/* ── 宽容解析工具（缺字段不炸） ── */
function asRecord(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {}
}
function asList(raw: unknown, keys: string[] = ['items', 'list', 'data']): unknown[] {
  if (Array.isArray(raw)) return raw
  const o = asRecord(raw)
  for (const k of keys) {
    if (Array.isArray(o[k])) return o[k] as unknown[]
  }
  return []
}
function numOr(raw: unknown): number | null {
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}
function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
function linesOf(text: string): string[] {
  return text.split('\n').map((l) => l.trim()).filter(Boolean)
}
function extractLines(raw: unknown): string[] {
  if (typeof raw === 'string') return linesOf(raw)
  if (Array.isArray(raw)) return raw.map((l) => String(l ?? '').trim()).filter(Boolean)
  const o = asRecord(raw)
  for (const k of ['lines', 'instructions', 'items']) {
    if (Array.isArray(o[k])) return (o[k] as unknown[]).map((l) => String(l ?? '').trim()).filter(Boolean)
  }
  for (const k of ['text', 'content', 'body', 'instructions']) {
    if (typeof o[k] === 'string') return linesOf(o[k] as string)
  }
  return []
}
function normDream(raw: unknown, index: number): DreamNight {
  const o = asRecord(raw)
  const dateRaw = String(o.date ?? o.night ?? o.day ?? o.archived_at ?? '').trim()
  const topicsRaw = o.key_topics ?? o.topics ?? o.keywords ?? o.tags
  return {
    key: `${dateRaw || 'night'}-${index}`,
    date: dateRaw || `第 ${index + 1} 夜`,
    summary: String(o.summary ?? o.text ?? o.digest ?? '（这一夜没有留下摘要）'),
    topics: Array.isArray(topicsRaw) ? topicsRaw.map((t) => String(t)).filter(Boolean) : [],
  }
}
function normEvicted(raw: unknown): string[] {
  if (raw === null || raw === undefined || raw === '') return []
  const list = Array.isArray(raw) ? raw : [raw]
  return list
    .map((e) => {
      if (typeof e === 'string') return e
      const o = asRecord(e)
      return String(o.line ?? o.text ?? o.instruction ?? '')
    })
    .filter(Boolean)
}

/* ── 状态 ── */
const loading = ref(true)
const offline = ref(false)
const error = ref('')

const instructionsText = ref('')
const savedText = ref('')
const savingInstructions = ref(false)
const instructionsMsg = ref('')
const instructionsMsgErr = ref(false)

const rememberText = ref('')
const remembering = ref(false)
const rememberFeedback = ref<RememberFeedback | null>(null)

const dreams = ref<DreamNight[]>([])
const archiving = ref(false)
const archiveMsg = ref('')

const scheduleText = ref('每夜 03:00')
const scheduleTime = ref('03:00')
const scheduleEnabled = ref(true)

const lineCount = computed(() => linesOf(instructionsText.value).length)
const overLimit = computed(() => lineCount.value > MAX_LINES)
const dirty = computed(() => instructionsText.value.replace(/\s+$/g, '') !== savedText.value.replace(/\s+$/g, ''))

function normSchedule(raw: unknown): void {
  const o = asRecord(raw)
  scheduleEnabled.value = o.enabled !== false
  const time = typeof o.time === 'string' && o.time.trim() ? o.time.trim() : ''
  const tz = typeof o.timezone === 'string' && o.timezone.trim() ? ` · ${o.timezone.trim()}` : ''
  if (time) {
    scheduleTime.value = time
    scheduleText.value = `每夜 ${time}${tz}`
    return
  }
  const cron = typeof o.cron === 'string' ? o.cron.trim() : ''
  const m = cron.match(/^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$/)
  if (m) {
    const t = `${String(m[2]).padStart(2, '0')}:${String(m[1]).padStart(2, '0')}`
    scheduleTime.value = t
    scheduleText.value = `每夜 ${t}${tz}`
    return
  }
  scheduleTime.value = '03:00'
  scheduleText.value = `每夜 03:00${tz}`
}

async function loadAll(): Promise<void> {
  loading.value = true
  error.value = ''
  const results = await Promise.allSettled([
    apiGet<unknown>('/memory/instructions'),
    apiGet<unknown>('/memory/dreams'),
    apiGet<unknown>('/memory/dreams/schedule'),
  ])
  const [ins, drm, sch] = results
  const failedAll = results.every((r) => r.status === 'rejected')
  offline.value = failedAll

  if (ins.status === 'fulfilled') {
    instructionsText.value = extractLines(ins.value).join('\n')
    savedText.value = instructionsText.value
  } else if (failedAll) {
    instructionsText.value = FALLBACK_LINES.join('\n')
    savedText.value = instructionsText.value
  }

  if (drm.status === 'fulfilled') {
    dreams.value = asList(drm.value, ['items', 'dreams', 'nights', 'list', 'data']).map(normDream)
  } else if (failedAll) {
    dreams.value = FALLBACK_DREAMS.map((d) => ({ ...d }))
  }

  if (sch.status === 'fulfilled') normSchedule(sch.value)

  if (!failedAll && results.some((r) => r.status === 'rejected')) {
    error.value = '部分数据加载失败，已展示可用内容'
  }
  loading.value = false
}

async function refreshInstructions(): Promise<void> {
  try {
    const res = await apiGet<unknown>('/memory/instructions')
    instructionsText.value = extractLines(res).join('\n')
    savedText.value = instructionsText.value
  } catch {
    /* 静默：编辑器保持现状 */
  }
}

async function saveInstructions(): Promise<void> {
  if (savingInstructions.value || overLimit.value || !dirty.value) return
  savingInstructions.value = true
  instructionsMsg.value = ''
  instructionsMsgErr.value = false
  const lines = linesOf(instructionsText.value)
  try {
    await apiPut<unknown>('/memory/instructions', { lines })
    instructionsText.value = lines.join('\n')
    savedText.value = instructionsText.value
    instructionsMsg.value = `已保存 ${lines.length} 条记忆指令`
  } catch (e) {
    instructionsMsgErr.value = true
    instructionsMsg.value = `保存失败：${errText(e)}${offline.value ? '（离线示例模式，未写入后端）' : ''}`
  } finally {
    savingInstructions.value = false
  }
}

async function remember(): Promise<void> {
  const text = rememberText.value.trim()
  if (!text || remembering.value) return
  remembering.value = true
  rememberFeedback.value = null
  try {
    const res = await apiPost<unknown>('/memory/remember', { text })
    const o = asRecord(res)
    const count = numOr(o.count ?? o.total ?? o.lines)
    rememberFeedback.value = {
      ok: o.ok !== false,
      text: `已记住：${String(o.line ?? o.text ?? text)}${count !== null ? `（第 ${count} 条）` : ''}`,
      evicted: normEvicted(o.evicted ?? o.evicted_lines ?? o.dropped),
    }
    rememberText.value = ''
    void refreshInstructions()
  } catch (e) {
    rememberFeedback.value = {
      ok: false,
      text: `写入失败：${errText(e)}${offline.value ? '（离线示例模式，未写入后端）' : ''}`,
      evicted: [],
    }
  } finally {
    remembering.value = false
  }
}

async function archiveNow(): Promise<void> {
  if (archiving.value) return
  archiving.value = true
  archiveMsg.value = ''
  try {
    const res = await apiPost<unknown>('/memory/dreams/archive-now', {})
    const o = asRecord(res)
    const archived = numOr(o.archived ?? o.count ?? o.nights)
    const date = typeof o.date === 'string' ? o.date : ''
    archiveMsg.value = archived !== null
      ? `整理完成：${date || '昨夜'} 归档 ${archived} 段梦境`
      : '整理完成，昨夜梦境已归档入库'
    const drm = await apiGet<unknown>('/memory/dreams').catch(() => null)
    if (drm !== null) dreams.value = asList(drm, ['items', 'dreams', 'nights', 'list', 'data']).map(normDream)
  } catch (e) {
    archiveMsg.value = `整理失败：${errText(e)}${offline.value ? '（离线示例模式）' : ''}`
  } finally {
    archiving.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div>
    <PageHero
      seal="忆"
      title="记忆中枢"
      en="MEMORY CENTER"
      sub="记忆指令模型始终遵循；梦境记忆每夜 03:00 自动整理归档。"
    />

    <div v-if="offline" class="notice warn" role="status">
      <span class="notice-text">未连上后端，当前展示离线示例数据；保存与记住将在连接恢复后生效。</span>
      <GfButton variant="ghost" small @click="loadAll">重试连接</GfButton>
    </div>
    <div v-else-if="error" class="notice error" role="alert" aria-live="polite">
      <span class="notice-text">{{ error }}</span>
      <GfButton variant="ghost" small @click="loadAll">重试</GfButton>
    </div>

    <div class="stat-grid">
      <GfStat label="记忆指令" :value="`${lineCount}/${MAX_LINES}`" :tone="overLimit ? 'rouge' : 'ink'" hint="每行一条，超上限禁止保存" />
      <GfStat label="梦境记忆" :value="dreams.length" tone="dai" hint="按夜归档的整理成果" />
      <GfStat label="整理计划" :value="scheduleTime" tone="gold" :hint="scheduleEnabled ? '每夜自动整理开启中' : '自动整理已暂停'" />
    </div>

    <div class="grid-2">
      <div class="col">
        <GfCard title="记忆指令" seal="令">
          <p class="card-desc">模型始终遵循，对话中说『记住 xxx』自动追加。每行一条，上限 {{ MAX_LINES }} 行。</p>
          <textarea
            v-model="instructionsText"
            class="instr-editor"
            :class="{ over: overLimit }"
            rows="12"
            spellcheck="false"
            :disabled="savingInstructions"
            placeholder="每行一条指令，例如：回答一律使用中文"
          ></textarea>
          <div class="editor-bar">
            <span class="line-count" :class="{ over: overLimit }">{{ lineCount }}/{{ MAX_LINES }}</span>
            <span v-if="overLimit" class="over-hint">已超上限，请删减后再保存</span>
            <span class="bar-spacer"></span>
            <GfButton small :disabled="savingInstructions || overLimit || !dirty || loading" @click="saveInstructions">
              {{ savingInstructions ? '保存中…' : dirty ? '保存指令' : '已保存' }}
            </GfButton>
          </div>
          <p v-if="instructionsMsg" class="feedback" :class="{ err: instructionsMsgErr }" aria-live="polite">{{ instructionsMsg }}</p>
        </GfCard>

        <GfCard title="记住" seal="记">
          <p class="card-desc">一句话让模型立刻记住，效果等同在对话中说『记住 xxx』。</p>
          <form class="remember-bar" @submit.prevent="remember">
            <input
              v-model.trim="rememberText"
              class="remember-input"
              maxlength="200"
              placeholder="例如：我喜欢的图表配色是暖色系"
              :disabled="remembering"
            />
            <GfButton small :disabled="remembering || !rememberText" @click="remember">
              {{ remembering ? '写入中…' : '记住' }}
            </GfButton>
          </form>
          <div v-if="rememberFeedback" class="remember-result" aria-live="polite">
            <p class="feedback" :class="{ err: !rememberFeedback.ok }">{{ rememberFeedback.text }}</p>
            <div v-if="rememberFeedback.evicted.length" class="evicted">
              <p class="evicted-title">指令池已满，最早的记忆被挤出：</p>
              <div class="evicted-tags">
                <GfTag v-for="(e, i) in rememberFeedback.evicted" :key="`evicted-${i}`" tone="rouge">{{ e }}</GfTag>
              </div>
            </div>
          </div>
        </GfCard>
      </div>

      <div class="col">
        <GfCard title="整理计划" seal="程">
          <div class="schedule-row">
            <div class="schedule-main">
              <div class="schedule-time">{{ scheduleText }}</div>
              <div class="schedule-sub">{{ scheduleEnabled ? '到点自动整理昨夜梦境并归档成卷' : '自动整理当前已暂停' }}</div>
            </div>
            <GfButton variant="ghost" small :disabled="archiving" @click="archiveNow">
              {{ archiving ? '整理中…' : '立即整理' }}
            </GfButton>
          </div>
          <p v-if="archiveMsg" class="feedback" aria-live="polite">{{ archiveMsg }}</p>
        </GfCard>

        <GfCard title="梦境时间线" seal="梦">
          <div v-if="loading" class="muted">研墨中…</div>
          <template v-else>
            <div v-if="dreams.length" class="timeline">
              <article v-for="dream in dreams" :key="dream.key" class="scroll-card">
                <header class="scroll-head">
                  <span class="scroll-date">{{ dream.date }}</span>
                </header>
                <p class="scroll-summary">{{ dream.summary }}</p>
                <div v-if="dream.topics.length" class="scroll-topics">
                  <GfTag v-for="t in dream.topics" :key="t" tone="dai">{{ t }}</GfTag>
                </div>
              </article>
            </div>
            <GfEmpty v-else text="尚无梦境记忆，每夜 03:00 自动整理" />
          </template>
        </GfCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}
.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
  align-items: start;
}
.col { display: flex; flex-direction: column; gap: 20px; min-width: 0; }

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
.notice.warn {
  color: color-mix(in srgb, var(--gold) 78%, var(--ink));
  border-color: var(--gold-line);
  background: color-mix(in srgb, var(--gold) 8%, transparent);
}
.notice.error {
  color: var(--cinnabar-deep);
  border-color: var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 7%, transparent);
}
.notice-text { line-height: 1.6; }

.card-desc {
  font-size: 12px;
  letter-spacing: 1px;
  line-height: 1.8;
  color: var(--ink-muted);
  margin-bottom: 12px;
}
.muted {
  color: var(--ink-soft);
  font-size: 13px;
  padding: 14px 0;
  font-family: var(--font-kai);
  letter-spacing: 2px;
}
.feedback {
  margin-top: 10px;
  font-size: 12px;
  letter-spacing: 1px;
  color: var(--bamboo);
  line-height: 1.7;
}
.feedback.err { color: var(--cinnabar); }

/* ── 记忆指令编辑器 ── */
.instr-editor {
  display: block;
  width: 100%;
  min-height: 240px;
  resize: vertical;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 12px 14px;
  font: inherit;
  font-size: 13px;
  line-height: 1.9;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.instr-editor:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.instr-editor.over { border-color: var(--cinnabar); }
.instr-editor:disabled { opacity: .55; }
.editor-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}
.line-count {
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 1px;
  color: var(--ink-muted);
}
.line-count.over { color: var(--cinnabar); font-weight: 700; }
.over-hint {
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--cinnabar);
}
.bar-spacer { flex: 1; }

/* ── 记住 ── */
.remember-bar { display: flex; gap: 10px; align-items: center; }
.remember-input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
  background: var(--card);
  color: var(--ink);
  padding: 8px 16px;
  font: inherit;
  font-size: 13px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.remember-input:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.remember-input:disabled { opacity: .55; }
.remember-result { margin-top: 4px; }
.evicted { margin-top: 8px; }
.evicted-title {
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--cinnabar);
  margin-bottom: 6px;
}
.evicted-tags { display: flex; flex-wrap: wrap; gap: 6px; }

/* ── 整理计划 ── */
.schedule-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}
.schedule-time {
  font-family: var(--font-kai);
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 3px;
  color: var(--gold);
}
.schedule-sub {
  margin-top: 4px;
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--ink-muted);
}

/* ── 梦境时间线（卷轴） ── */
.timeline {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-left: 20px;
}
.timeline::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 8px;
  bottom: 8px;
  width: 1px;
  background: linear-gradient(180deg, transparent, var(--gold-line) 12%, var(--gold-line) 88%, transparent);
}
.scroll-card {
  position: relative;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  box-shadow: var(--shadow-card);
  padding: 14px 16px;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.scroll-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lift);
  border-color: var(--gold-line);
}
.scroll-card::before {
  content: '';
  position: absolute;
  left: -19px;
  top: 20px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--gold);
  box-shadow: 0 0 8px var(--gold-line);
}
.scroll-head { margin-bottom: 6px; }
.scroll-date {
  font-family: var(--font-kai);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 2px;
  color: var(--gold);
}
.scroll-summary {
  font-size: 13px;
  line-height: 1.9;
  color: var(--ink-soft);
}
.scroll-topics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

@media (max-width: 980px) {
  .grid-2 { grid-template-columns: 1fr; }
}
@media (max-width: 620px) {
  .stat-grid { grid-template-columns: 1fr; }
  .remember-bar { flex-direction: column; align-items: stretch; }
  .schedule-row { flex-direction: column; align-items: flex-start; }
}
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiDel, apiGet, apiPost, apiPut, isAuthError, isNetworkError } from '@/api/platform'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfStat from '@/components/gf/GfStat.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import InkDivider from '@/components/gf/InkDivider.vue'

interface SessionItem {
  id: string
  title: string
  turns: number
  agent: string
  updatedAt: string
  pinned: boolean
  archived: boolean
  autoExpand: boolean
}

interface Phrase {
  id: string
  text: string
  uses: number
}

/* ── 离线兜底示例数据 ── */
const FALLBACK_SESSIONS: SessionItem[] = [
  { id: 'demo-1', title: '示例 · 夜间主题联调复盘', turns: 24, agent: '主智能体', updatedAt: '示例时间', pinned: true, archived: false, autoExpand: true },
  { id: 'demo-2', title: '示例 · 模型网关 dry-run', turns: 11, agent: '主智能体', updatedAt: '示例时间', pinned: false, archived: false, autoExpand: false },
  { id: 'demo-3', title: '示例 · 周报素材整理', turns: 8, agent: '文书智能体', updatedAt: '示例时间', pinned: false, archived: true, autoExpand: false },
]
const FALLBACK_PHRASES: Phrase[] = [
  { id: 'demo-p1', text: '帮我写个周报', uses: 12 },
  { id: 'demo-p2', text: '把这段日志翻译成中文', uses: 7 },
  { id: 'demo-p3', text: '总结一下今天的进展', uses: 5 },
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
  if (isAuthError(e)) return `鉴权失败：${e.message}（请检查左侧 API 密钥）`
  if (isNetworkError(e)) return '网络异常，后端未连通'
  return e instanceof Error ? e.message : String(e)
}
function normSession(raw: unknown, index: number): SessionItem {
  const o = asRecord(raw)
  return {
    id: String(o.id ?? o.session_id ?? o.sid ?? `s-${index}`),
    title: String(o.title ?? o.name ?? '').trim() || '未命名会话',
    turns: numOr(o.turns ?? o.turn_count ?? o.rounds ?? o.message_count) ?? 0,
    agent: String(o.agent ?? o.agent_id ?? o.agent_name ?? '').trim() || '默认智能体',
    updatedAt: String(o.updated_at ?? o.updatedAt ?? o.last_active_at ?? o.last_message_at ?? ''),
    pinned: Boolean(o.pinned ?? o.is_pinned),
    archived: Boolean(o.archived ?? o.is_archived),
    autoExpand: Boolean(o.auto_expand_refs ?? o.autoExpandRefs ?? o.auto_expand ?? o.auto_expand_web),
  }
}
function normPhrase(raw: unknown, index: number): Phrase {
  if (typeof raw === 'string') return { id: `p-${index}`, text: raw, uses: 0 }
  const o = asRecord(raw)
  return {
    id: String(o.id ?? o.phrase_id ?? `p-${index}`),
    text: String(o.text ?? o.phrase ?? o.content ?? ''),
    // 后端字段为 usage_count（memory_center.py），其余为兼容候选（08-#28）
    uses: numOr(o.uses ?? o.usage_count ?? o.use_count ?? o.count ?? o.used) ?? 0,
  }
}
function fmtTime(raw: string): string {
  const s = raw.trim()
  if (!s) return '—'
  let d: Date
  if (/^\d{10,13}$/.test(s)) {
    const n = Number(s)
    d = new Date(s.length === 10 ? n * 1000 : n)
  } else {
    d = new Date(s)
  }
  if (Number.isNaN(d.getTime())) return s
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/* ── 状态 ── */
const loading = ref(true)
const offline = ref(false)
const error = ref('')

const sessions = ref<SessionItem[]>([])
const busyId = ref('')
const showArchived = ref(false)

const phrases = ref<Phrase[]>([])
const newPhrase = ref('')
const phraseBusy = ref(false)
const copiedId = ref('')

function cmpSessions(a: SessionItem, b: SessionItem): number {
  if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
  return (b.updatedAt || '').localeCompare(a.updatedAt || '')
}
const activeSessions = computed(() => sessions.value.filter((s) => !s.archived).sort(cmpSessions))
const archivedSessions = computed(() => sessions.value.filter((s) => s.archived).sort(cmpSessions))
const pinnedCount = computed(() => activeSessions.value.filter((s) => s.pinned).length)

async function loadAll(): Promise<void> {
  loading.value = true
  error.value = ''
  const results = await Promise.allSettled([
    apiGet<unknown>('/memory/sessions'),
    apiGet<unknown>('/memory/phrases'),
  ])
  const [sess, phr] = results
  const failedAll = results.every((r) => r.status === 'rejected')
  const allNetwork = results.every(
    (r) => r.status === 'rejected' && isNetworkError(r.reason),
  )
  const firstFailure = results.find((r): r is PromiseRejectedResult => r.status === 'rejected')
  offline.value = allNetwork

  if (sess.status === 'fulfilled') {
    sessions.value = asList(sess.value, ['items', 'sessions', 'list', 'data']).map(normSession)
  } else if (allNetwork) {
    sessions.value = FALLBACK_SESSIONS.map((s) => ({ ...s }))
  } else {
    // 鉴权/服务端错误不得沿用先前离线示例，避免把示例误当真实会话。
    sessions.value = []
  }

  if (phr.status === 'fulfilled') {
    phrases.value = asList(phr.value, ['items', 'phrases', 'list', 'data']).map(normPhrase).filter((p) => p.text)
  } else if (allNetwork) {
    phrases.value = FALLBACK_PHRASES.map((p) => ({ ...p }))
  } else {
    phrases.value = []
  }

  if (failedAll && firstFailure && !allNetwork) {
    error.value = errText(firstFailure.reason)
  } else if (!failedAll && firstFailure) {
    error.value = '部分数据加载失败，已展示可用内容'
  }
  loading.value = false
}

async function togglePin(s: SessionItem): Promise<void> {
  const next = !s.pinned
  s.pinned = next
  error.value = ''
  try {
    await apiPut<unknown>(`/memory/sessions/${encodeURIComponent(s.id)}`, { pinned: next })
  } catch (e) {
    s.pinned = !next
    error.value = `置顶失败：${errText(e)}`
  }
}

async function toggleAutoExpand(s: SessionItem): Promise<void> {
  const next = !s.autoExpand
  s.autoExpand = next
  error.value = ''
  try {
    await apiPut<unknown>(`/memory/sessions/${encodeURIComponent(s.id)}`, { auto_expand_refs: next })
  } catch (e) {
    s.autoExpand = !next
    error.value = `开关失败：${errText(e)}`
  }
}

async function archive(s: SessionItem): Promise<void> {
  if (busyId.value) return
  busyId.value = s.id
  error.value = ''
  try {
    const res = await apiPost<unknown>(`/memory/sessions/${encodeURIComponent(s.id)}/archive`, {})
    // 以后端返回的会话为准（08-#29）：后端归档不清置顶，
    // 前端不再本地强置 pinned=false，避免与刷新后的真实状态漂移。
    const sess = asRecord(asRecord(res).session ?? res)
    s.archived = typeof sess.archived === 'boolean' ? sess.archived : true
    if (typeof sess.pinned === 'boolean') s.pinned = sess.pinned
  } catch (e) {
    error.value = `归档失败：${errText(e)}`
  } finally {
    busyId.value = ''
  }
}

async function unarchive(s: SessionItem): Promise<void> {
  if (busyId.value) return
  busyId.value = s.id
  error.value = ''
  try {
    const res = await apiPost<unknown>(`/memory/sessions/${encodeURIComponent(s.id)}/unarchive`, {})
    const sess = asRecord(asRecord(res).session ?? res)
    s.archived = typeof sess.archived === 'boolean' ? sess.archived : false
    if (typeof sess.pinned === 'boolean') s.pinned = sess.pinned
  } catch (e) {
    error.value = `恢复失败：${errText(e)}`
  } finally {
    busyId.value = ''
  }
}

async function addPhrase(): Promise<void> {
  const text = newPhrase.value.trim()
  if (!text || phraseBusy.value) return
  phraseBusy.value = true
  error.value = ''
  try {
    const res = await apiPost<unknown>('/memory/phrases', { text })
    const o = asRecord(res)
    const item = asRecord(o.item ?? o.phrase ?? res)
    phrases.value.push({
      id: String(item.id ?? `p-${Date.now()}`),
      text: String(item.text ?? text),
      uses: numOr(item.uses ?? item.usage_count ?? item.use_count ?? item.count) ?? 0,
    })
    newPhrase.value = ''
  } catch (e) {
    error.value = `新增常用语失败：${errText(e)}`
  } finally {
    phraseBusy.value = false
  }
}

async function removePhrase(p: Phrase): Promise<void> {
  if (phraseBusy.value) return
  phraseBusy.value = true
  error.value = ''
  try {
    await apiDel<unknown>(`/memory/phrases/${encodeURIComponent(p.id)}`)
    phrases.value = phrases.value.filter((x) => x.id !== p.id)
  } catch (e) {
    error.value = `删除常用语失败：${errText(e)}`
  } finally {
    phraseBusy.value = false
  }
}

function legacyCopy(text: string): void {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
}

async function copyPhrase(p: Phrase): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(p.text)
    } else {
      legacyCopy(p.text)
    }
    copiedId.value = p.id
    window.setTimeout(() => {
      if (copiedId.value === p.id) copiedId.value = ''
    }, 1600)
  } catch {
    error.value = '复制失败，请手动选择文本复制'
    return
  }
  void bumpPhraseUsage(p)
}

/* 复制成功后上报使用计数（08-#28）：本地先 +1 乐观展示，
   再以 POST /phrases/{pid}/use 的响应校准；上报失败静默，
   下次刷新以服务端计数为准。 */
async function bumpPhraseUsage(p: Phrase): Promise<void> {
  p.uses += 1
  if (offline.value) return
  try {
    const res = await apiPost<unknown>(`/memory/phrases/${encodeURIComponent(p.id)}/use`, {})
    const item = asRecord(asRecord(res).item ?? res)
    const serverCount = numOr(item.usage_count ?? item.uses ?? item.use_count)
    if (serverCount !== null) p.uses = serverCount
  } catch {
    // 计数上报失败不打断复制流程
  }
}

onMounted(loadAll)
</script>

<template>
  <div>
    <PageHero
      seal="话"
      title="会话清册"
      en="SESSIONS & PHRASES"
      sub="会话置顶、归档与参考网页展开偏好；常用语一点即复制。"
    />

    <div v-if="offline" class="notice warn" role="status">
      <span class="notice-text">未连上后端，当前展示离线示例数据；编辑与计数暂不会保存，连接恢复后请重试。</span>
      <GfButton variant="ghost" small @click="loadAll">重试连接</GfButton>
    </div>
    <div v-else-if="error" class="notice error" role="alert" aria-live="polite">
      <span class="notice-text">{{ error }}</span>
      <GfButton variant="ghost" small @click="loadAll">重试</GfButton>
    </div>

    <div class="stat-grid">
      <GfStat label="进行中会话" :value="activeSessions.length" tone="ink" hint="置顶会话排在最前" />
      <GfStat label="置顶" :value="pinnedCount" tone="rouge" hint="钉住的会话" />
      <GfStat label="已归档" :value="archivedSessions.length" tone="gold" hint="折叠收纳，可随时恢复" />
      <GfStat label="常用语" :value="phrases.length" tone="dai" hint="点击词条即复制" />
    </div>

    <GfCard title="会话列表" seal="话" class="sess-card">
      <div v-if="loading" class="muted">研墨中…</div>
      <template v-else>
        <div v-if="activeSessions.length" class="sess-list">
          <div v-for="s in activeSessions" :key="s.id" class="sess-row" :class="{ pinned: s.pinned }">
            <button
              class="pin-btn"
              :class="{ active: s.pinned }"
              type="button"
              :title="s.pinned ? '取消置顶' : '置顶此会话'"
              :aria-pressed="s.pinned"
              @click="togglePin(s)"
            >钉</button>
            <div class="sess-main">
              <div class="sess-title">{{ s.title }}</div>
              <div class="sess-meta">
                <span>{{ s.turns }} 轮</span>
                <GfTag tone="dai">{{ s.agent }}</GfTag>
                <span>更新于 {{ fmtTime(s.updatedAt) }}</span>
              </div>
            </div>
            <label class="expand-toggle" :title="s.autoExpand ? '关闭自动展开参考网页' : '开启自动展开参考网页'">
              <button
                class="switch"
                :class="{ on: s.autoExpand }"
                type="button"
                role="switch"
                :aria-checked="s.autoExpand"
                @click="toggleAutoExpand(s)"
              >
                <span class="knob"></span>
              </button>
              <span class="expand-label">自动展开参考网页</span>
            </label>
            <GfButton variant="ghost" small :disabled="!!busyId" @click="archive(s)">
              {{ busyId === s.id ? '归档中…' : '归档' }}
            </GfButton>
          </div>
        </div>
        <GfEmpty v-else text="暂无进行中的会话，去工作台开一场新对话吧" />

        <template v-if="archivedSessions.length">
          <InkDivider :label="`已归档 ${archivedSessions.length}`" />
          <button class="archived-toggle" type="button" :aria-expanded="showArchived" @click="showArchived = !showArchived">
            <span class="archived-arrow" :class="{ open: showArchived }">▸</span>
            {{ showArchived ? '收起已归档会话' : `展开已归档会话（${archivedSessions.length}）` }}
          </button>
          <div v-if="showArchived" class="sess-list archived">
            <div v-for="s in archivedSessions" :key="s.id" class="sess-row">
              <div class="sess-main">
                <div class="sess-title">{{ s.title }}</div>
                <div class="sess-meta">
                  <span>{{ s.turns }} 轮</span>
                  <GfTag tone="ink">{{ s.agent }}</GfTag>
                  <span>更新于 {{ fmtTime(s.updatedAt) }}</span>
                </div>
              </div>
              <GfButton variant="ghost" small :disabled="!!busyId" @click="unarchive(s)">
                {{ busyId === s.id ? '恢复中…' : '恢复' }}
              </GfButton>
            </div>
          </div>
        </template>
      </template>
    </GfCard>

    <GfCard title="常用语" seal="语" class="phrase-card">
      <p class="card-desc">点击词条复制到剪贴板，右侧数字为使用计数。</p>
      <div v-if="loading" class="muted">研墨中…</div>
      <template v-else>
        <div v-if="phrases.length" class="chip-cloud">
          <span v-for="p in phrases" :key="p.id" class="chip" :class="{ copied: copiedId === p.id }">
            <button class="chip-text" type="button" :title="`点击复制：${p.text}`" @click="copyPhrase(p)">{{ p.text }}</button>
            <span class="chip-uses">{{ copiedId === p.id ? '已复制' : `×${p.uses}` }}</span>
            <button class="chip-del" type="button" title="删除此常用语" :disabled="phraseBusy" @click="removePhrase(p)">×</button>
          </span>
        </div>
        <GfEmpty v-else text="尚无常用语，添加一句试试" />
        <form class="phrase-add" @submit.prevent="addPhrase">
          <input
            v-model.trim="newPhrase"
            class="phrase-input"
            maxlength="200"
            placeholder="新增常用语，例如：帮我写个周报"
            :disabled="phraseBusy"
          />
          <GfButton small :disabled="phraseBusy || !newPhrase" @click="addPhrase">
            {{ phraseBusy ? '添加中…' : '添加' }}
          </GfButton>
        </form>
      </template>
    </GfCard>
  </div>
</template>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}
.sess-card { margin-bottom: 20px; }

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

.muted {
  color: var(--ink-soft);
  font-size: 13px;
  padding: 14px 0;
  font-family: var(--font-kai);
  letter-spacing: 2px;
}
.card-desc {
  font-size: 12px;
  letter-spacing: 1px;
  line-height: 1.8;
  color: var(--ink-muted);
  margin-bottom: 12px;
}

/* ── 会话行 ── */
.sess-list { display: flex; flex-direction: column; }
.sess-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 6px;
  border-bottom: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  transition: background .18s ease;
}
.sess-row:last-child { border-bottom: none; }
.sess-row:hover { background: color-mix(in srgb, var(--rouge) 6%, transparent); }
.sess-row.pinned { background: color-mix(in srgb, var(--gold) 6%, transparent); }
.sess-row.pinned:hover { background: color-mix(in srgb, var(--gold) 9%, transparent); }

.pin-btn {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid var(--gold-line);
  background: transparent;
  color: var(--ink-muted);
  font-family: var(--font-kai);
  font-size: 13px;
  display: grid;
  place-items: center;
  transition: transform .18s ease, box-shadow .18s ease, background .18s ease, color .18s ease;
}
.pin-btn:hover {
  transform: translateY(-2px);
  color: var(--cinnabar);
  border-color: var(--rouge);
  box-shadow: var(--shadow-glow-rouge);
}
.pin-btn.active {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-color: transparent;
  color: var(--card-solid);
  box-shadow: 0 0 10px var(--cinnabar-glow);
}

.sess-main { flex: 1; min-width: 0; }
.sess-title {
  font-family: var(--font-kai);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 1px;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sess-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--ink-muted);
}

/* ── 自动展开开关 ── */
.expand-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  cursor: pointer;
}
.expand-label {
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--ink-muted);
  white-space: nowrap;
}
.switch {
  position: relative;
  width: 34px;
  height: 19px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line);
  background: var(--line-soft);
  padding: 0;
  transition: background .2s ease, border-color .2s ease;
}
.switch .knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: var(--card-solid);
  box-shadow: var(--shadow-card);
  transition: transform .2s ease, background .2s ease;
}
.switch.on {
  background: color-mix(in srgb, var(--bamboo) 40%, transparent);
  border-color: color-mix(in srgb, var(--bamboo) 60%, transparent);
}
.switch.on .knob {
  transform: translateX(15px);
  background: var(--bamboo);
}

/* ── 已归档折叠区 ── */
.archived-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: none;
  background: none;
  padding: 4px 2px;
  font-family: var(--font-kai);
  font-size: 13px;
  letter-spacing: 2px;
  color: var(--ink-soft);
  transition: color .18s ease;
}
.archived-toggle:hover { color: var(--cinnabar); }
.archived-arrow {
  font-size: 11px;
  transition: transform .18s ease;
  display: inline-block;
}
.archived-arrow.open { transform: rotate(90deg); }
.sess-list.archived .sess-title { color: var(--ink-soft); }

/* ── 常用语 chips ── */
.chip-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 14px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--gold-line);
  background: var(--card);
  transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
}
.chip:hover {
  border-color: var(--rouge);
  box-shadow: var(--shadow-glow-rouge);
  transform: translateY(-2px);
}
.chip.copied {
  border-color: var(--bamboo);
  box-shadow: 0 0 12px color-mix(in srgb, var(--bamboo) 35%, transparent);
}
.chip-text {
  border: none;
  background: none;
  padding: 0;
  font-size: 13px;
  letter-spacing: 1px;
  color: var(--ink);
  cursor: copy;
}
.chip-uses {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 1px;
  color: var(--ink-muted);
  white-space: nowrap;
}
.chip.copied .chip-uses { color: var(--bamboo); }
.chip-del {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: none;
  background: transparent;
  color: var(--ink-muted);
  font-size: 12px;
  line-height: 1;
  display: grid;
  place-items: center;
  transition: background .18s ease, color .18s ease;
}
.chip-del:hover {
  color: var(--cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 12%, transparent);
}
.chip-del:disabled { opacity: .5; cursor: not-allowed; }

.phrase-add {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 14px;
}
.phrase-input {
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
.phrase-input:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.phrase-input:disabled { opacity: .55; }

@media (max-width: 980px) {
  .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .expand-label { display: none; }
}
@media (max-width: 620px) {
  .stat-grid { grid-template-columns: 1fr; }
  .sess-row { flex-wrap: wrap; }
  .phrase-add { flex-direction: column; align-items: stretch; }
}
</style>

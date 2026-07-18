<script setup lang="ts">
/**
 * 宛委典藏 · 知识库
 * 契约（后端 platform_api/knowledge）：
 *   GET    /knowledge/docs             文档列表
 *   POST   /knowledge/docs             新建文档 { title, body, tags }
 *   PUT    /knowledge/docs/{id}        更新（编辑 / 置顶）
 *   DELETE /knowledge/docs/{id}        删除
 *   GET    /knowledge/search?q=        搜索（snippet 内含 <b> 高亮，v-html 渲染）
 *   GET    /knowledge/stats            统计（总量 / 近7日 / 来源分布）
 * 全部字段容错（可选链 + 默认值），后端未连通时展示离线示例并诚实标注。
 */
import { computed, onMounted, ref, shallowRef } from 'vue'
import { apiDel, apiGet, apiPost, apiPut } from '@/api/platform'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfStat from '@/components/gf/GfStat.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

type TagTone = 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
type SourceType = 'manual' | 'web' | 'chat' | 'file'
type SourceFilter = 'all' | SourceType

interface KnowledgeDoc {
  id: string
  title: string
  body: string
  tags: string[]
  source: SourceType
  pinned: boolean
  updatedAt: string
}

interface SearchHit {
  id: string
  title: string
  snippet: string
  source: SourceType
  score: number | null
}

interface KnowledgeStats {
  total: number
  recent7d: number
  sources: Record<string, number>
}

interface SourceSegment {
  key: SourceType
  label: string
  tone: TagTone
  count: number
  pct: number
}

interface DocForm {
  title: string
  body: string
  tags: string
}

const SOURCE_ORDER: SourceType[] = ['manual', 'web', 'chat', 'file']
const SOURCE_LABELS: Record<SourceType, string> = {
  manual: '手动录入',
  web: '网页采集',
  chat: '会话沉淀',
  file: '文件归档',
}
const SOURCE_TONES: Record<SourceType, TagTone> = {
  manual: 'gold',
  web: 'dai',
  chat: 'rouge',
  file: 'bamboo',
}

/* ── 离线兜底示例数据 ── */
const SAMPLE_DOCS: KnowledgeDoc[] = [
  {
    id: 'doc-1',
    title: '麒麟 Linux 部署要点',
    body: '麒麟 Linux 目标平台部署需注意：字体包自带楷体回退；Electron 需关闭 sandbox 以兼容国产内核；自启动写入 ~/.config/autostart。',
    tags: ['部署', '麒麟', '桌面端'],
    source: 'manual',
    pinned: true,
    updatedAt: '今日 09:12',
  },
  {
    id: 'doc-2',
    title: '模型网关联调记录',
    body: 'openai_compatible 渠道已打通 dry-run 与真实 smoke；密钥仅在提交时发送，列表只回显掩码。',
    tags: ['模型', '网关'],
    source: 'chat',
    pinned: false,
    updatedAt: '昨日 17:40',
  },
  {
    id: 'doc-3',
    title: '国风双主题令牌摘录',
    body: '宣纸白昼与靛夜灯影两套主题共用 tokens.css；卡片半透 blur(8px)，印章朱砂渐变，禁蓝紫渐变。',
    tags: ['设计', '主题'],
    source: 'web',
    pinned: false,
    updatedAt: '昨日 11:05',
  },
  {
    id: 'doc-4',
    title: '平台 API 契约草案',
    body: 'platform_api 自动发现子模块挂载 /platform 前缀；持久化统一走 JsonStore；固定路径须先于参数路径定义。',
    tags: ['架构', '契约'],
    source: 'file',
    pinned: false,
    updatedAt: '三日前',
  },
]

const SAMPLE_STATS: KnowledgeStats = {
  total: 4,
  recent7d: 3,
  sources: { manual: 1, web: 1, chat: 1, file: 1 },
}

/* ── 规范化（对后端缺字段容错） ── */
function pickArray(res: unknown, keys: string[]): Record<string, unknown>[] {
  if (Array.isArray(res)) return res as Record<string, unknown>[]
  if (res && typeof res === 'object') {
    const obj = res as Record<string, unknown>
    for (const k of keys) {
      if (Array.isArray(obj[k])) return obj[k] as Record<string, unknown>[]
    }
  }
  return []
}

function fmtTime(v: unknown): string {
  if (!v) return ''
  const s = String(v)
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function normSource(v: unknown): SourceType {
  const s = String(v ?? 'manual').toLowerCase()
  return (SOURCE_ORDER as string[]).includes(s) ? (s as SourceType) : 'manual'
}

function normTags(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String).filter(Boolean)
  if (typeof v === 'string') return v.split(/[,，、\s]+/).filter(Boolean)
  return []
}

function normDoc(raw: Record<string, unknown>): KnowledgeDoc {
  return {
    id: String(raw.id ?? raw.doc_id ?? ''),
    title: String(raw.title ?? '未命名文档'),
    body: String(raw.body ?? raw.content ?? ''),
    tags: normTags(raw.tags),
    source: normSource(raw.source),
    pinned: raw.pinned === true || raw.pinned === 1,
    updatedAt: fmtTime(raw.updated_at ?? raw.created_at),
  }
}

function normHit(raw: Record<string, unknown>, i: number): SearchHit {
  const sc = Number(raw.score ?? raw.rank)
  return {
    id: String(raw.id ?? raw.doc_id ?? `hit-${i}`),
    title: String(raw.title ?? '未命名'),
    snippet: String(raw.snippet ?? raw.highlight ?? raw.excerpt ?? ''),
    source: normSource(raw.source),
    score: Number.isFinite(sc) ? sc : null,
  }
}

function normStats(res: unknown): KnowledgeStats {
  const o = (res && typeof res === 'object' ? res : {}) as Record<string, unknown>
  const sources: Record<string, number> = {}
  const rawSrc = o.by_source ?? o.sources ?? o.source_distribution ?? o.distribution
  if (Array.isArray(rawSrc)) {
    for (const it of rawSrc) {
      const r = (it && typeof it === 'object' ? it : {}) as Record<string, unknown>
      const k = String(r.source ?? r.name ?? '')
      if (k) sources[k] = Number(r.count ?? r.value ?? 0) || 0
    }
  } else if (rawSrc && typeof rawSrc === 'object') {
    for (const [k, v] of Object.entries(rawSrc as Record<string, unknown>)) {
      sources[k] = Number(v) || 0
    }
  }
  return {
    total: Number(o.total ?? o.count ?? o.total_docs ?? 0) || 0,
    recent7d: Number(o.recent_7d ?? o.recent7d ?? o.last_7d ?? o.week ?? 0) || 0,
    sources,
  }
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => {
    const map: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
    return map[c] ?? c
  })
}

/* ── 状态 ── */
const docs = shallowRef<KnowledgeDoc[]>([])
const stats = shallowRef<KnowledgeStats>({ total: 0, recent7d: 0, sources: {} })
const loading = shallowRef(true)
const offline = shallowRef(false)
const notice = shallowRef('')
const noticeKind = shallowRef<'error' | 'offline' | 'ok'>('ok')

const q = shallowRef('')
const searching = shallowRef(false)
const searched = shallowRef(false)
const hits = shallowRef<SearchHit[]>([])
const sourceFilter = ref<SourceFilter>('all')

const showEditor = shallowRef(false)
const editingDoc = shallowRef<KnowledgeDoc | null>(null)
const saving = shallowRef(false)
const docForm = ref<DocForm>({ title: '', body: '', tags: '' })

const deletingDoc = shallowRef<KnowledgeDoc | null>(null)
const deleteBusy = shallowRef(false)
const pinningId = shallowRef('')

const sourceSegments = computed<SourceSegment[]>(() => {
  const segs = SOURCE_ORDER.map((key) => ({
    key,
    label: SOURCE_LABELS[key],
    tone: SOURCE_TONES[key],
    count: Number(stats.value.sources[key] ?? 0) || 0,
    pct: 0,
  }))
  const sum = segs.reduce((acc, s) => acc + s.count, 0)
  const base = sum > 0 ? sum : stats.value.total
  if (base > 0) {
    for (const s of segs) s.pct = Math.max(0, Math.round((s.count / base) * 100))
  }
  return segs
})

const hasSourceData = computed(() => sourceSegments.value.some((s) => s.count > 0))

const filteredDocs = computed<KnowledgeDoc[]>(() => {
  const sorted = [...docs.value].sort(
    (a, b) => Number(b.pinned) - Number(a.pinned) || b.updatedAt.localeCompare(a.updatedAt),
  )
  if (sourceFilter.value === 'all') return sorted
  return sorted.filter((d) => d.source === sourceFilter.value)
})

const filteredHits = computed<SearchHit[]>(() => {
  if (sourceFilter.value === 'all') return hits.value
  return hits.value.filter((h) => h.source === sourceFilter.value)
})

function setNotice(text: string, kind: 'error' | 'offline' | 'ok' = 'ok'): void {
  notice.value = text
  noticeKind.value = kind
}

/* ── 加载 ── */
async function load(): Promise<void> {
  loading.value = true
  notice.value = ''
  const [docsRes, statsRes] = await Promise.allSettled([
    apiGet<unknown>('/knowledge/docs'),
    apiGet<unknown>('/knowledge/stats'),
  ])

  const docsFailed = docsRes.status !== 'fulfilled'
  docs.value = docsRes.status === 'fulfilled'
    ? pickArray(docsRes.value, ['items', 'docs', 'data']).map(normDoc).filter((d) => d.id)
    : SAMPLE_DOCS
  stats.value = statsRes.status === 'fulfilled' ? normStats(statsRes.value) : SAMPLE_STATS

  offline.value = docsFailed
  if (docsFailed) {
    setNotice('后端未连通，当前展示离线示例数据；一切变更仅在本地生效，不会持久化。', 'offline')
  }
  loading.value = false
}

/* ── 搜索 ── */
async function doSearch(): Promise<void> {
  const query = q.value.trim()
  if (!query || searching.value) return
  searching.value = true
  try {
    if (!offline.value) {
      const res = await apiGet<unknown>(`/knowledge/search?q=${encodeURIComponent(query)}`)
      hits.value = pickArray(res, ['items', 'results', 'hits', 'data']).map(normHit)
      searched.value = true
    } else {
      /* 离线兜底：在示例数据上本地检索并生成 <b> 高亮片段 */
      const needle = query.toLowerCase()
      hits.value = docs.value
        .filter((d) => `${d.title}\n${d.body}`.toLowerCase().includes(needle))
        .map((d) => {
          const idx = d.body.toLowerCase().indexOf(needle)
          const start = Math.max(0, idx - 24)
          const end = Math.min(d.body.length, idx + query.length + 40)
          const raw = idx >= 0 ? d.body.slice(start, end) : d.body.slice(0, 64)
          const escaped = escapeHtml(raw)
          const highlighted = idx >= 0
            ? escaped.replace(new RegExp(escapeHtml(query).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), (m) => `<b>${m}</b>`)
            : escaped
          return { id: d.id, title: d.title, snippet: `${start > 0 ? '…' : ''}${highlighted}${end < d.body.length ? '…' : ''}`, source: d.source, score: null }
        })
      searched.value = true
      setNotice('离线模式：搜索仅在本页示例数据上进行。', 'offline')
    }
  } catch (e) {
    setNotice(`搜索失败：${e instanceof Error ? e.message : String(e)}`, 'error')
  } finally {
    searching.value = false
  }
}

function clearSearch(): void {
  q.value = ''
  hits.value = []
  searched.value = false
}

/* ── 新建 / 编辑 ── */
function openCreate(): void {
  editingDoc.value = null
  docForm.value = { title: '', body: '', tags: '' }
  showEditor.value = true
}

function openEdit(doc: KnowledgeDoc): void {
  editingDoc.value = doc
  docForm.value = { title: doc.title, body: doc.body, tags: doc.tags.join('，') }
  showEditor.value = true
}

function closeEditor(): void {
  if (saving.value) return
  showEditor.value = false
  editingDoc.value = null
}

function parseTags(input: string): string[] {
  return input.split(/[,，、\s]+/).map((t) => t.trim()).filter(Boolean).slice(0, 12)
}

async function saveDoc(): Promise<void> {
  if (saving.value) return
  saving.value = true
  const payload = {
    title: docForm.value.title,
    body: docForm.value.body,
    tags: parseTags(docForm.value.tags),
  }
  const target = editingDoc.value
  try {
    if (!offline.value) {
      if (target) {
        await apiPut<unknown>(`/knowledge/docs/${target.id}`, payload)
      } else {
        await apiPost<unknown>('/knowledge/docs', { ...payload, source: 'manual' })
      }
      showEditor.value = false
      editingDoc.value = null
      setNotice(target ? '文档已更新。' : '文档已入库。', 'ok')
      await load()
    } else {
      if (target) {
        docs.value = docs.value.map((d) =>
          d.id === target.id
            ? { ...d, title: payload.title, body: payload.body, tags: payload.tags, updatedAt: fmtTime(new Date().toISOString()) }
            : d,
        )
      } else {
        const local: KnowledgeDoc = {
          id: `local-${Date.now()}`,
          title: payload.title,
          body: payload.body,
          tags: payload.tags,
          source: 'manual',
          pinned: false,
          updatedAt: fmtTime(new Date().toISOString()),
        }
        docs.value = [local, ...docs.value]
      }
      showEditor.value = false
      editingDoc.value = null
      setNotice('离线模式：变更仅存在于本页内存。', 'offline')
    }
  } catch (e) {
    setNotice(`保存失败：${e instanceof Error ? e.message : String(e)}`, 'error')
  } finally {
    saving.value = false
  }
}

/* ── 置顶 ── */
async function togglePin(doc: KnowledgeDoc): Promise<void> {
  if (pinningId.value) return
  pinningId.value = doc.id
  const next = !doc.pinned
  try {
    if (!offline.value) {
      await apiPut<unknown>(`/knowledge/docs/${doc.id}`, { pinned: next })
    } else {
      setNotice('离线模式：置顶状态仅本地生效。', 'offline')
    }
    docs.value = docs.value.map((d) => (d.id === doc.id ? { ...d, pinned: next } : d))
  } catch (e) {
    setNotice(`置顶操作失败：${e instanceof Error ? e.message : String(e)}`, 'error')
  } finally {
    pinningId.value = ''
  }
}

/* ── 删除 ── */
function askDelete(doc: KnowledgeDoc): void {
  deletingDoc.value = doc
}

async function confirmDelete(): Promise<void> {
  const doc = deletingDoc.value
  if (!doc || deleteBusy.value) return
  deleteBusy.value = true
  try {
    if (!offline.value) {
      await apiDel<unknown>(`/knowledge/docs/${doc.id}`)
      setNotice(`《${doc.title}》已删除。`, 'ok')
    } else {
      setNotice('离线模式：删除仅在本页内存生效。', 'offline')
    }
    docs.value = docs.value.filter((d) => d.id !== doc.id)
    deletingDoc.value = null
  } catch (e) {
    setNotice(`删除失败：${e instanceof Error ? e.message : String(e)}`, 'error')
  } finally {
    deleteBusy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHero
      seal="典"
      title="宛委典藏"
      en="KNOWLEDGE ARCHIVE"
      sub="搜索 · 归档 · 溯源。凡所过目，皆可典藏。"
    />

    <div v-if="notice" class="notice" :class="noticeKind" role="status" aria-live="polite">
      <span class="notice-text">{{ notice }}</span>
      <GfButton variant="ghost" small :disabled="loading" @click="load">刷新</GfButton>
    </div>

    <!-- ── 统计带 ── -->
    <div class="stats-band">
      <GfStat label="典藏总量" :value="stats.total" tone="gold" hint="篇文档在库" />
      <GfStat label="近 7 日新增" :value="stats.recent7d" tone="rouge" hint="持续沉淀中" />
      <div class="src-card">
        <div class="src-title">来源分布</div>
        <div v-if="hasSourceData" class="src-bar" role="img" aria-label="来源分布条形图">
          <span
            v-for="seg in sourceSegments"
            :key="seg.key"
            class="src-seg"
            :data-tone="seg.tone"
            :style="{ width: seg.pct + '%' }"
            :title="`${seg.label} · ${seg.count}`"
          ></span>
        </div>
        <div v-else class="src-bar src-bar--empty"></div>
        <div class="src-legend">
          <span v-for="seg in sourceSegments" :key="seg.key" class="src-item">
            <i class="src-dot" :data-tone="seg.tone"></i>{{ seg.label }} · {{ seg.count }}
          </span>
        </div>
      </div>
    </div>

    <!-- ── 搜索与筛选 ── -->
    <div class="search-row">
      <div class="search-box">
        <input
          v-model="q"
          type="search"
          placeholder="检索典藏，试试「麒麟」或「契约」…"
          aria-label="知识库搜索"
          @keyup.enter="doSearch"
        />
        <GfButton small :disabled="searching || !q.trim()" @click="doSearch">
          {{ searching ? '检索中…' : '搜索' }}
        </GfButton>
        <GfButton v-if="searched" variant="ghost" small @click="clearSearch">清除</GfButton>
      </div>
      <div class="filter-chips" role="group" aria-label="来源筛选">
        <button
          v-for="opt in (['all', ...SOURCE_ORDER] as SourceFilter[])"
          :key="opt"
          class="chip"
          :class="{ on: sourceFilter === opt }"
          type="button"
          :aria-pressed="sourceFilter === opt"
          @click="sourceFilter = opt"
        >
          {{ opt === 'all' ? '全部' : SOURCE_LABELS[opt] }}
        </button>
      </div>
    </div>

    <!-- ── 搜索结果 ── -->
    <GfCard v-if="searched" title="检索结果" seal="觅" class="result-card">
      <div v-if="filteredHits.length" class="hit-list">
        <article v-for="hit in filteredHits" :key="hit.id" class="hit-row">
          <div class="hit-head">
            <h3 class="hit-title">{{ hit.title }}</h3>
            <GfTag :tone="SOURCE_TONES[hit.source]">{{ SOURCE_LABELS[hit.source] }}</GfTag>
            <span v-if="hit.score !== null" class="hit-score">相关度 {{ hit.score.toFixed(2) }}</span>
          </div>
          <!-- 后端返回的 snippet 内含 <b> 高亮标记 -->
          <p class="hit-snippet" v-html="hit.snippet || '（无摘要）'"></p>
        </article>
      </div>
      <GfEmpty v-else text="未寻得匹配典藏。换个关键词试试。" />
    </GfCard>

    <!-- ── 文档卡片列表 ── -->
    <template v-else>
      <div class="action-bar">
        <GfButton :disabled="loading" @click="openCreate">新建文档</GfButton>
      </div>
      <div v-if="loading" class="muted">研墨中…</div>
      <template v-else>
        <div v-if="filteredDocs.length" class="doc-grid">
          <article v-for="doc in filteredDocs" :key="doc.id" class="doc-card" :class="{ pinned: doc.pinned }">
            <div class="doc-head">
              <button
                class="pin"
                :class="{ on: doc.pinned }"
                type="button"
                :aria-pressed="doc.pinned"
                :title="doc.pinned ? '取消置顶' : '置顶'"
                :disabled="pinningId === doc.id"
                @click="togglePin(doc)"
              >
                <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                  <path d="M6 1.2h4l-.8 5.6 2.6 2.6v1.8H4.2V9.4l2.6-2.6L6 1.2z" fill="currentColor" />
                  <path d="M7.2 11.2h1.6v2.7l-.8 1-.8-1v-2.7z" fill="currentColor" />
                </svg>
              </button>
              <h3 class="doc-title">{{ doc.title }}</h3>
              <GfTag :tone="SOURCE_TONES[doc.source]">{{ SOURCE_LABELS[doc.source] }}</GfTag>
            </div>
            <p v-if="doc.body" class="doc-body">{{ doc.body }}</p>
            <div v-if="doc.tags.length" class="doc-tags">
              <GfTag v-for="t in doc.tags" :key="t" tone="ink">{{ t }}</GfTag>
            </div>
            <div class="doc-foot">
              <span class="doc-time">{{ doc.updatedAt || '—' }}</span>
              <div class="doc-actions">
                <GfButton variant="ghost" small @click="openEdit(doc)">编辑</GfButton>
                <GfButton variant="danger" small @click="askDelete(doc)">删除</GfButton>
              </div>
            </div>
          </article>
        </div>
        <GfCard v-else :pad="true">
          <GfEmpty text="此来源下暂无典藏。点上方「新建文档」落笔第一篇。" />
        </GfCard>
      </template>
    </template>

    <!-- ── 新建 / 编辑弹层 ── -->
    <div v-if="showEditor" class="overlay" @click.self="closeEditor">
      <div class="modal" role="dialog" aria-modal="true" :aria-label="editingDoc ? '编辑文档' : '新建文档'">
        <header class="modal-hd">
          <span class="modal-seal">{{ editingDoc ? '修' : '新' }}</span>
          <h3>{{ editingDoc ? '编辑文档' : '新建文档' }}</h3>
        </header>
        <form class="modal-form" @submit.prevent="saveDoc">
          <label>标题<input v-model.trim="docForm.title" required maxlength="80" placeholder="例如：麒麟 Linux 部署要点" autocomplete="off" /></label>
          <label>正文<textarea v-model.trim="docForm.body" rows="6" placeholder="把值得记住的内容写在这里…"></textarea></label>
          <label>标签<input v-model.trim="docForm.tags" placeholder="以逗号或空格分隔，如：部署，麒麟，桌面端" autocomplete="off" /></label>
          <div class="modal-actions">
            <button class="form-submit" type="submit" :disabled="saving">{{ saving ? '保存中…' : editingDoc ? '保存修改' : '收录入库' }}</button>
            <button class="form-cancel" type="button" :disabled="saving" @click="closeEditor">取消</button>
          </div>
        </form>
      </div>
    </div>

    <!-- ── 删除确认弹层 ── -->
    <div v-if="deletingDoc" class="overlay" @click.self="deletingDoc = null">
      <div class="modal modal--narrow" role="alertdialog" aria-modal="true" aria-label="删除确认">
        <header class="modal-hd">
          <span class="modal-seal modal-seal--danger">删</span>
          <h3>确认删除</h3>
        </header>
        <p class="confirm-text">将删除《{{ deletingDoc.title }}》，此操作不可撤销。</p>
        <div class="modal-actions">
          <button class="form-submit form-submit--danger" type="button" :disabled="deleteBusy" @click="confirmDelete">
            {{ deleteBusy ? '删除中…' : '确认删除' }}
          </button>
          <button class="form-cancel" type="button" :disabled="deleteBusy" @click="deletingDoc = null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.muted { color: var(--ink-soft); font-size: 13px; padding: 14px 0; font-family: var(--font-kai); letter-spacing: 2px; }

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
.notice.offline {
  color: color-mix(in srgb, var(--gold) 80%, var(--ink));
  border-color: var(--gold-line);
  background: color-mix(in srgb, var(--gold) 8%, transparent);
}
.notice.ok {
  color: color-mix(in srgb, var(--bamboo) 72%, var(--ink));
  border-color: color-mix(in srgb, var(--bamboo) 40%, transparent);
  background: color-mix(in srgb, var(--bamboo) 9%, transparent);
}
.notice-text { line-height: 1.6; }

/* ── 统计带 ── */
.stats-band {
  display: grid;
  grid-template-columns: 200px 200px minmax(0, 1fr);
  gap: 14px;
  margin-bottom: 18px;
}
.src-card {
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: 16px 18px;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.src-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lift); border-color: var(--gold-line); }
.src-title { font-size: 11px; letter-spacing: 2px; color: var(--ink-muted); margin-bottom: 12px; }
.src-bar {
  display: flex;
  height: 10px;
  border-radius: 999px;
  overflow: hidden;
  background: var(--line-soft);
  border: 1px solid var(--line-soft);
}
.src-seg { display: block; height: 100%; transition: width .3s ease; }
.src-seg[data-tone='gold'] { background: color-mix(in srgb, var(--gold) 68%, transparent); }
.src-seg[data-tone='dai'] { background: color-mix(in srgb, var(--dai) 62%, transparent); }
.src-seg[data-tone='rouge'] { background: color-mix(in srgb, var(--rouge) 62%, transparent); }
.src-seg[data-tone='bamboo'] { background: color-mix(in srgb, var(--bamboo) 66%, transparent); }
.src-legend { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 10px; }
.src-item { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; letter-spacing: 1px; color: var(--ink-soft); }
.src-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.src-dot[data-tone='gold'] { background: var(--gold); }
.src-dot[data-tone='dai'] { background: var(--dai); }
.src-dot[data-tone='rouge'] { background: var(--rouge); }
.src-dot[data-tone='bamboo'] { background: var(--bamboo); }

/* ── 搜索与筛选 ── */
.search-row { display: grid; gap: 10px; margin-bottom: 16px; }
.search-box { display: flex; gap: 10px; align-items: center; }
.search-box input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--card);
  color: var(--ink);
  padding: 9px 18px;
  font: inherit;
  font-size: 13px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.search-box input:focus { outline: none; border-color: var(--cinnabar); box-shadow: 0 0 0 3px var(--rouge-glow); }
.filter-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip {
  padding: 4px 14px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--card);
  color: var(--ink-soft);
  font-size: 12px;
  letter-spacing: 1px;
  font-family: var(--font-kai);
  cursor: pointer;
  transition: border-color .18s ease, color .18s ease, box-shadow .18s ease, transform .18s ease;
}
.chip:hover { transform: translateY(-1px); border-color: var(--rouge); color: var(--cinnabar); }
.chip.on {
  border-color: color-mix(in srgb, var(--rouge) 55%, transparent);
  color: var(--cinnabar);
  background: color-mix(in srgb, var(--rouge) 10%, transparent);
  box-shadow: var(--shadow-glow-rouge);
}

/* ── 搜索结果 ── */
.result-card { margin-bottom: 18px; }
.hit-list { display: grid; gap: 12px; }
.hit-row {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  box-shadow: var(--shadow-card);
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
}
.hit-row:hover { transform: translateY(-2px); box-shadow: var(--shadow-lift); border-color: var(--gold-line); }
.hit-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.hit-title { font-family: var(--font-kai); font-size: 16px; letter-spacing: 2px; color: var(--ink); overflow-wrap: anywhere; }
.hit-score { font-size: 11px; color: var(--ink-muted); font-family: var(--font-mono); }
.hit-snippet { margin-top: 8px; font-size: 12px; color: var(--ink-soft); line-height: 1.8; overflow-wrap: anywhere; }
.hit-snippet :deep(b) {
  color: var(--cinnabar);
  background: color-mix(in srgb, var(--rouge) 18%, transparent);
  padding: 0 3px;
  border-radius: 4px;
  font-weight: 700;
}

.action-bar { display: flex; justify-content: flex-end; margin: -4px 0 16px; }

/* ── 文档卡片 ── */
.doc-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.doc-card {
  display: flex;
  flex-direction: column;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: var(--shadow-card);
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
}
.doc-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lift); border-color: var(--gold-line); }
.doc-card.pinned { border-color: color-mix(in srgb, var(--gold) 55%, transparent); }
.doc-head { display: flex; align-items: center; gap: 8px; }
.doc-title { flex: 1; min-width: 0; font-family: var(--font-kai); font-size: 17px; letter-spacing: 2px; color: var(--ink); overflow-wrap: anywhere; }
.pin {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--card);
  color: var(--ink-muted);
  cursor: pointer;
  flex-shrink: 0;
  transition: color .18s ease, border-color .18s ease, transform .18s ease, box-shadow .18s ease;
}
.pin:hover { transform: translateY(-1px); border-color: var(--gold); color: var(--gold); }
.pin.on {
  color: var(--gold);
  border-color: color-mix(in srgb, var(--gold) 55%, transparent);
  background: color-mix(in srgb, var(--gold) 12%, transparent);
  box-shadow: 0 0 10px color-mix(in srgb, var(--gold) 30%, transparent);
}
.pin:disabled { opacity: .55; cursor: not-allowed; transform: none; }
.doc-body {
  margin-top: 10px;
  font-size: 12px;
  color: var(--ink-soft);
  line-height: 1.7;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.doc-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.doc-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: auto;
  padding-top: 12px;
}
.doc-time { font-size: 11px; color: var(--ink-muted); letter-spacing: 1px; }
.doc-actions { display: flex; gap: 7px; }

/* ── 弹层 ── */
.overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 20px;
  background: color-mix(in srgb, var(--ink) 34%, transparent);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}
.modal {
  width: min(560px, 100%);
  background: var(--card-solid);
  border: 1px solid var(--gold-line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-lift);
  padding: 20px 22px;
}
.modal--narrow { width: min(420px, 100%); }
.modal-hd { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.modal-seal {
  font-family: var(--font-kai);
  font-size: 13px;
  font-weight: 700;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: 0 0 10px var(--cinnabar-glow);
}
.modal-seal--danger { background: linear-gradient(135deg, var(--cinnabar-deep), var(--cinnabar-deep)); }
.modal-hd h3 { font-family: var(--font-kai); font-size: 20px; letter-spacing: 3px; color: var(--ink); }
.confirm-text { font-size: 13px; color: var(--ink-soft); line-height: 1.7; margin-bottom: 16px; }
.modal-form { display: grid; gap: 12px; }
.modal-form label { display: grid; gap: 6px; color: var(--ink-muted); font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px; }
.modal-form input, .modal-form textarea {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 8px 12px;
  font: inherit;
  font-size: 12px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.modal-form textarea { resize: vertical; }
.modal-form input:focus, .modal-form textarea:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }

/* 原生提交/取消按钮（GfButton 固定 type=button） */
.form-submit, .form-cancel {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 20px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 13px;
  letter-spacing: 2px;
  font-family: var(--font-kai);
  cursor: pointer;
  transition: transform .18s ease, box-shadow .18s ease, background .18s ease, color .18s ease, border-color .18s ease;
}
.form-submit {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: 0 2px 12px var(--cinnabar-glow), var(--shadow-card);
}
.form-submit:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 4px 18px var(--cinnabar-glow), var(--shadow-glow-rouge); }
.form-submit--danger { background: linear-gradient(135deg, var(--cinnabar-deep), var(--cinnabar-deep)); }
.form-cancel { background: var(--card); border-color: var(--gold-line); color: var(--ink-soft); }
.form-cancel:hover:not(:disabled) { transform: translateY(-2px); border-color: var(--rouge); color: var(--cinnabar); box-shadow: var(--shadow-glow-rouge); }
.form-submit:disabled, .form-cancel:disabled { opacity: .55; cursor: not-allowed; transform: none; box-shadow: none; }

@media (max-width: 980px) {
  .stats-band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .src-card { grid-column: span 2; }
  .doc-grid { grid-template-columns: 1fr; }
}
@media (max-width: 620px) {
  .stats-band { grid-template-columns: 1fr; }
  .src-card { grid-column: auto; }
  .action-bar { justify-content: flex-start; }
  .search-box { flex-wrap: wrap; }
}
</style>

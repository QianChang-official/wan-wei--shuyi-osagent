<script setup lang="ts">
/**
 * ProvidersView — 模型接入（万枢协作平台 V2）
 * 契约（backend/app/platform_api/providers.py）：
 *   GET  /providers/catalog           31 家供应商目录
 *   GET  /providers/configs           已保存配置（密钥仅回尾号掩码）
 *   PUT  /providers/configs/{pid}     保存单家配置
 *   POST /providers/test              连通性测试 { pid }
 *   POST /providers/auth/{pid}/begin  OAuth 设备码授权开始
 *   POST /providers/auth/{pid}/poll   OAuth 授权轮询
 *   GET  /providers/aux               全局辅助模型
 *   PUT  /providers/aux               保存全局辅助模型
 * 全部字段容错（可选链 + 默认值）；目录加载失败时启用内置 31 家离线兜底并标注「离线数据」。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { apiGet, apiPost, apiPut, isAuthError, isNetworkError, PlatformApiError } from '@/api/platform'
import PageHero from '@/components/gf/PageHero.vue'

function platformErrText(e: unknown): string {
  if (isAuthError(e)) return `鉴权失败：${e.message}（请检查左侧 API 密钥）`
  if (isNetworkError(e)) return '网络异常，后端未连通'
  return e instanceof Error ? e.message : String(e)
}
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfStat from '@/components/gf/GfStat.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import InkDivider from '@/components/gf/InkDivider.vue'

/* ── 契约类型（字段全可选，后端缺字段不炸） ── */
type ProviderKind = 'cloud' | 'local' | 'oauth' | 'aggregator' | 'custom'

interface CatalogModel { id?: string; name?: string }
interface ProviderCatalogItem {
  id?: string
  pid: string
  name: string
  kind: string
  base_url?: string
  models?: Array<string | CatalogModel>
  aux_capable?: boolean
  note?: string
}
interface ProviderConfig {
  pid: string
  configured?: boolean
  enabled?: boolean
  model?: string
  base_url?: string
  /* 后端 _masked_config 实际返回的脱敏字段 */
  has_api_key?: boolean
  api_key_tail?: string
  /* 历史别名容错（旧字段），读取时一律以后端新字段优先 */
  key_tail?: string
  has_key?: boolean
  aux?: boolean
  authorized?: boolean
}
interface AuxConfig { provider?: string; model?: string; purpose?: string }
interface OauthState {
  status: 'idle' | 'pending' | 'authorized' | 'stub' | 'error'
  verificationUri: string
  userCode: string
  hint: string
}

const KIND_LABELS: Record<ProviderKind, string> = {
  cloud: '云端', local: '本地', oauth: 'OAuth', aggregator: '聚合', custom: '自定义',
}
const KIND_TONES: Record<ProviderKind, 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'> = {
  cloud: 'dai', local: 'bamboo', oauth: 'rouge', aggregator: 'gold', custom: 'ink',
}

function normalizeKind(raw: unknown): ProviderKind {
  const k = String(raw ?? '').toLowerCase()
  if (k.includes('oauth') || k.includes('授权')) return 'oauth'
  if (k.includes('local') || k.includes('本地') || k.includes('本机')) return 'local'
  if (k.includes('agg') || k.includes('聚合') || k.includes('router') || k.includes('gateway')) return 'aggregator'
  if (k.includes('custom') || k.includes('自定')) return 'custom'
  return 'cloud'
}

function modelNames(models: ProviderCatalogItem['models']): string[] {
  if (!Array.isArray(models)) return []
  return models
    .map((m) => (typeof m === 'string' ? m : (m?.id ?? m?.name ?? '')))
    .filter((m): m is string => !!m)
}

function normCatalogItem(p: ProviderCatalogItem): ProviderCatalogItem {
  if (!p.pid && p.id) p.pid = p.id
  return p
}

function asArray<T>(raw: unknown, keys: string[] = ['items', 'providers', 'catalog', 'configs']): T[] {
  if (Array.isArray(raw)) return raw as T[]
  if (raw && typeof raw === 'object') {
    const obj = raw as Record<string, unknown>
    for (const k of keys) {
      const v = obj[k]
      if (Array.isArray(v)) return v as T[]
      if (v && typeof v === 'object' && !Array.isArray(v)) {
        // { configs: { pid: {...} } } 映射形态
        return Object.entries(v as Record<string, unknown>).map(([pid, val]) => ({
          pid,
          ...(val && typeof val === 'object' ? (val as Record<string, unknown>) : {}),
        })) as unknown as T[]
      }
    }
  }
  return []
}

/* ── 离线兜底目录：31 家，pid 与 backend/app/platform_api/providers.py CATALOG 的 id 键逐一对齐（标注「离线数据」展示） ── */
const FALLBACK_CATALOG: ProviderCatalogItem[] = [
  { pid: 'openrouter', name: 'OpenRouter', kind: 'aggregator', base_url: 'https://openrouter.ai/api/v1', models: ['anthropic/claude-sonnet-4.5', 'openai/gpt-4o', 'google/gemini-2.5-pro'], aux_capable: true },
  { pid: 'mixture_of_agents', name: 'MoA', kind: 'aggregator', base_url: 'https://api.moa-ai.com/v1', models: ['moa-large', 'moa-standard', 'moa-lite'], aux_capable: true },
  { pid: 'novitaai', name: 'NovitaAI', kind: 'cloud', base_url: 'https://api.novita.ai/v3/openai', models: ['deepseek/deepseek-v3.2', 'meta/llama-3.3-70b', 'qwen/qwen3-235b'], aux_capable: true },
  { pid: 'lm_studio', name: 'LM Studio', kind: 'local', base_url: 'http://localhost:1234/v1', models: ['local-model'], aux_capable: true, note: '本机推理' },
  { pid: 'anthropic', name: 'Anthropic', kind: 'cloud', base_url: 'https://api.anthropic.com', models: ['claude-sonnet-4-5', 'claude-opus-4-1', 'claude-haiku-4-5'] },
  { pid: 'openai', name: 'OpenAI', kind: 'cloud', base_url: 'https://api.openai.com/v1', models: ['gpt-4o', 'gpt-4.1', 'o3'] },
  { pid: 'qwen_cloud', name: 'Qwen Cloud 通义千问', kind: 'cloud', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen3-max', 'qwen-plus', 'qwen-turbo'], aux_capable: true },
  { pid: 'xai_grok', name: 'xAI Grok', kind: 'cloud', base_url: 'https://api.x.ai/v1', models: ['grok-4', 'grok-3', 'grok-3-mini'] },
  { pid: 'xiaomi_mimo', name: 'Xiaomi MiMo', kind: 'cloud', base_url: 'https://api.xiaomimimo.com/v1', models: ['mimo-v2-flash', 'mimo-v2-pro'] },
  { pid: 'tencent_tokenhub', name: 'Tencent TokenHub', kind: 'cloud', base_url: 'https://api.hunyuan.cloud.tencent.com/v1', models: ['hunyuan-turbos', 'hunyuan-pro', 'hunyuan-lite'], aux_capable: true },
  { pid: 'nvidia_nim', name: 'NVIDIA NIM', kind: 'cloud', base_url: 'https://integrate.api.nvidia.com/v1', models: ['meta/llama-3.3-70b-instruct', 'deepseek-ai/deepseek-r1', 'qwen/qwen3-235b-a22b'], aux_capable: true },
  { pid: 'github_copilot', name: 'GitHub Copilot', kind: 'oauth', base_url: 'https://api.githubcopilot.com', models: ['gpt-4o', 'claude-sonnet-4.5', 'o3-mini'] },
  { pid: 'huggingface', name: 'Hugging Face', kind: 'cloud', base_url: 'https://router.huggingface.co/v1', models: ['deepseek-ai/DeepSeek-V3.2', 'meta-llama/Llama-3.3-70B-Instruct', 'Qwen/Qwen3-235B-A22B'], aux_capable: true },
  { pid: 'google_ai_studio', name: 'Google AI Studio', kind: 'cloud', base_url: 'https://generativelanguage.googleapis.com/v1beta', models: ['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite'], aux_capable: true },
  { pid: 'google_vertex', name: 'Google Vertex AI', kind: 'oauth', base_url: 'https://aiplatform.googleapis.com', models: ['gemini-2.5-pro', 'gemini-2.5-flash'] },
  { pid: 'deepseek', name: 'DeepSeek', kind: 'cloud', base_url: 'https://api.deepseek.com', models: ['deepseek-chat', 'deepseek-reasoner'], aux_capable: true },
  { pid: 'zai', name: 'Z.AI 智谱', kind: 'cloud', base_url: 'https://open.bigmodel.cn/api/paas/v4', models: ['glm-4.6', 'glm-4.5-air', 'glm-4.5-flash'], aux_capable: true },
  { pid: 'kimi_moonshot', name: 'Kimi 月之暗面', kind: 'cloud', base_url: 'https://api.moonshot.cn/v1', models: ['kimi-k2-0905-preview', 'moonshot-v1-128k', 'moonshot-v1-32k'], aux_capable: true },
  { pid: 'stepfun', name: 'StepFun 阶跃星辰', kind: 'cloud', base_url: 'https://api.stepfun.com/v1', models: ['step-3', 'step-2-16k', 'step-1-flash'], aux_capable: true },
  { pid: 'minimax', name: 'MiniMax', kind: 'cloud', base_url: 'https://api.minimax.chat/v1', models: ['MiniMax-M2', 'abab6.5s-chat'], aux_capable: true },
  { pid: 'ollama_cloud', name: 'Ollama Cloud', kind: 'local', base_url: 'http://localhost:11434/v1', models: ['qwen3:32b', 'llama3.3:70b', 'deepseek-r1:32b'], aux_capable: true, note: '本机/云端混合' },
  { pid: 'arcee_ai', name: 'Arcee AI', kind: 'cloud', base_url: 'https://api.arcee.ai/v1', models: ['arcee-agent', 'arcee-lite'] },
  { pid: 'gmi_cloud', name: 'GMI Cloud', kind: 'cloud', base_url: 'https://api.gmicloud.ai/v1', models: ['deepseek-r1', 'llama-3.3-70b'] },
  { pid: 'kilo_code', name: 'Kilo Code', kind: 'oauth', base_url: 'https://api.kilocode.ai/v1', models: ['kilo-auto'] },
  { pid: 'opencode', name: 'OpenCode', kind: 'oauth', base_url: 'https://api.opencode.ai/v1', models: ['opencode-sonnet'] },
  { pid: 'aws_bedrock', name: 'AWS Bedrock', kind: 'cloud', base_url: 'https://bedrock-runtime.us-east-1.amazonaws.com', models: ['anthropic.claude-sonnet-4-5', 'amazon.nova-pro-v1'] },
  { pid: 'azure_foundry', name: 'Azure Foundry', kind: 'cloud', base_url: 'https://<resource>.services.ai.azure.com/models', models: ['gpt-4o', 'DeepSeek-V3.2'] },
  { pid: 'qwen_oauth', name: 'Qwen OAuth', kind: 'oauth', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen3-max', 'qwen-plus'] },
  { pid: 'alibaba_coding_plan', name: 'Alibaba Coding Plan', kind: 'cloud', base_url: 'https://coding.dashscope.aliyuncs.com/v1', models: ['qwen3-coder-plus', 'qwen3-coder-flash'] },
  { pid: 'siliconflow', name: 'SiliconFlow 硅基流动', kind: 'aggregator', base_url: 'https://api.siliconflow.cn/v1', models: ['deepseek-ai/DeepSeek-V3.2', 'Qwen/Qwen3-235B-A22B', 'moonshotai/Kimi-K2-Instruct'], aux_capable: true },
  { pid: 'custom_endpoint', name: '自定义端点', kind: 'custom', base_url: '', models: [], aux_capable: true, note: '任意 OpenAI 兼容端点' },
]

/* ── 页面状态 ── */
const loading = ref(true)
const error = ref('')
const catalog = ref<ProviderCatalogItem[]>([])
const catalogOffline = ref(false)
const configs = ref<ProviderConfig[]>([])
const configsOffline = ref(false)
const auxCfg = ref<AuxConfig>({})
const activeKind = ref<'all' | ProviderKind>('all')

const configMap = computed(() => {
  const m = new Map<string, ProviderConfig>()
  for (const c of configs.value) if (c?.pid) m.set(c.pid, c)
  return m
})

function isConfigured(pid: string): boolean {
  const c = configMap.value.get(pid)
  if (!c) return false
  // 后端 _masked_config 的 configured 是权威标记（base_url/model/enabled 均有默认值，不能作为判据）；
  // 旧后端无 configured 字段时，按密钥痕迹（has_api_key/api_key_tail 及历史别名）推断。
  if (typeof c.configured === 'boolean') return c.configured
  return !!(c.has_api_key || c.has_key || c.api_key_tail || c.key_tail || c.authorized)
}

const configuredCount = computed(() => catalog.value.filter((p) => isConfigured(p.pid)).length)
const enabledCount = computed(() => configs.value.filter((c) => c?.enabled).length)
const auxLabel = computed(() => auxCfg.value?.model || '未设置')
const auxHint = computed(() => {
  const pid = auxCfg.value?.provider
  if (!pid) return '尚未指定辅助供应商'
  const p = catalog.value.find((x) => x.pid === pid)
  return p ? p.name : pid
})

const kindCounts = computed(() => {
  const counts: Record<ProviderKind, number> = { cloud: 0, local: 0, oauth: 0, aggregator: 0, custom: 0 }
  for (const p of catalog.value) counts[normalizeKind(p.kind)] += 1
  return counts
})
const presentKinds = computed(() =>
  (Object.keys(KIND_LABELS) as ProviderKind[]).filter((k) => kindCounts.value[k] > 0),
)
const filteredCatalog = computed(() =>
  activeKind.value === 'all'
    ? catalog.value
    : catalog.value.filter((p) => normalizeKind(p.kind) === activeKind.value),
)

async function loadCatalog() {
  try {
    const raw = await apiGet<unknown>('/providers/catalog')
    const items = asArray<ProviderCatalogItem>(raw)
      .map(normCatalogItem)
      .filter((p) => p && p.pid)
    if (items.length) {
      catalog.value = items
      catalogOffline.value = false
      return
    }
    throw new Error('empty catalog')
  } catch (e) {
    const network = isNetworkError(e)
    catalogOffline.value = network
    if (network) catalog.value = FALLBACK_CATALOG
  }
}

async function loadConfigs() {
  try {
    const raw = await apiGet<unknown>('/providers/configs')
    configs.value = asArray<ProviderConfig>(raw)
    configsOffline.value = false
  } catch (e) {
    configsOffline.value = isNetworkError(e)
    configs.value = []
  }
}

async function loadAux() {
  try {
    const raw = await apiGet<unknown>('/providers/aux')
    const obj = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
    const aux = (obj.aux && typeof obj.aux === 'object' ? obj.aux : obj) as AuxConfig
    auxCfg.value = {
      provider: String((aux as Record<string, unknown>)?.pid ?? aux?.provider ?? ''),
      model: aux?.model ?? '',
      purpose: aux?.purpose ?? '',
    }
    auxForm.value = {
      provider: auxCfg.value.provider ?? '',
      model: auxCfg.value.model ?? '',
      purpose: auxCfg.value.purpose ?? '',
    }
  } catch {
    auxCfg.value = {}
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadCatalog(), loadConfigs(), loadAux()])
    if (catalogOffline.value && configsOffline.value) {
      error.value = '平台接口暂不可达，当前展示内置离线目录；配置保存将在后端就绪后可用。'
    }
  } finally {
    loading.value = false
  }
}

/* ── 配置抽屉 ── */
const drawerOpen = ref(false)
const activeProvider = ref<ProviderCatalogItem | null>(null)
const form = ref({ api_key: '', base_url: '', model: '', enabled: false })
const saving = ref(false)
const saveHint = ref('')
const testing = ref(false)
const testResult = ref<Record<string, unknown> | null>(null)
const testError = ref('')

const activeModels = computed(() => modelNames(activeProvider.value?.models))
const activeKind_ = computed(() => normalizeKind(activeProvider.value?.kind))
const activeConfig = computed(() =>
  activeProvider.value ? configMap.value.get(activeProvider.value.pid) : undefined,
)
const storedKeyTail = computed(() => {
  const c = activeConfig.value
  // 后端脱敏字段 api_key_tail / has_api_key 优先，历史别名 key_tail / has_key 兜底
  const tail = c?.api_key_tail || c?.key_tail
  if (tail) return `已存密钥尾号 ····${tail}`
  if (c?.has_api_key || c?.has_key) return '已存密钥（尾号未回显）'
  return ''
})

function openDrawer(p: ProviderCatalogItem) {
  stopPolling()
  activeProvider.value = p
  const c = configMap.value.get(p.pid)
  form.value = {
    api_key: '',
    base_url: c?.base_url || p.base_url || '',
    model: c?.model || modelNames(p.models)[0] || '',
    enabled: !!c?.enabled,
  }
  testResult.value = null
  testError.value = ''
  saveHint.value = ''
  oauth.value = { status: 'idle', verificationUri: '', userCode: '', hint: '' }
  drawerOpen.value = true
}

function closeDrawer() {
  if (saving.value) return
  stopPolling()
  drawerOpen.value = false
  activeProvider.value = null
}

async function saveConfig() {
  const p = activeProvider.value
  if (!p || saving.value) return
  saving.value = true
  saveHint.value = ''
  testError.value = ''
  try {
    const payload: Record<string, unknown> = {
      base_url: form.value.base_url,
      model: form.value.model,
      enabled: form.value.enabled,
    }
    if (form.value.api_key) payload.api_key = form.value.api_key
    await apiPut(`/providers/configs/${encodeURIComponent(p.pid)}`, payload)
    form.value.api_key = ''
    saveHint.value = '已保存'
    await loadConfigs()
  } catch (e) {
    testError.value = `保存失败：${platformErrText(e)}`
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  const p = activeProvider.value
  if (!p || testing.value) return
  testing.value = true
  testResult.value = null
  testError.value = ''
  try {
    const raw = await apiPost<unknown>('/providers/test', { pid: p.pid })
    testResult.value = (raw && typeof raw === 'object' ? raw : { detail: String(raw) }) as Record<string, unknown>
  } catch (e) {
    testError.value = `测试失败：${platformErrText(e)}`
  } finally {
    testing.value = false
  }
}

const testIsSimulated = computed(() => {
  const r = testResult.value
  return !!(r && (r.simulated || r.stub || r.dry_run || r.mode === 'stub'))
})
const testOk = computed(() => {
  const r = testResult.value
  if (!r) return false
  if (typeof r.ok === 'boolean') return r.ok
  const s = String(r.status ?? '').toLowerCase()
  return s === 'ok' || s === 'success' || s === 'connected' || s === '200'
})
const testSummary = computed(() => {
  const r = testResult.value
  if (!r) return ''
  const parts: string[] = []
  const latency = r.latency_ms ?? r.latency
  if (typeof latency === 'number') parts.push(`延迟 ${latency} ms`)
  const detail = r.detail ?? r.message ?? r.error ?? r.reason ?? r.note ?? ''
  if (detail) parts.push(String(detail))
  return parts.join(' · ') || JSON.stringify(r)
})

/* ── OAuth 授权流 ── */
const oauth = ref<OauthState>({ status: 'idle', verificationUri: '', userCode: '', hint: '' })
const oauthBusy = ref(false)
let pollTimer: ReturnType<typeof setTimeout> | null = null

/** 轮询网络类错误的最大重试次数（退避后仍失败则放弃） */
const OAUTH_POLL_MAX_NET_RETRIES = 3

function stopPolling() {
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

/**
 * verificationUri 协议白名单：仅放行 https://。
 * 该值直接进 <a :href>，须防 javascript:/data: 等伪协议注入；不合规一律置空。
 */
function sanitizeVerificationUri(raw: unknown): string {
  const uri = String(raw ?? '').trim()
  return uri.startsWith('https://') ? uri : ''
}

async function beginAuth() {
  const p = activeProvider.value
  if (!p || oauthBusy.value) return
  oauthBusy.value = true
  stopPolling()
  try {
    const raw = await apiPost<Record<string, unknown>>(`/providers/auth/${encodeURIComponent(p.pid)}/begin`)
    const res = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
    const stub = !!(res.stub || res.simulated)
    const verificationUri = sanitizeVerificationUri(res.verification_uri ?? res.url ?? res.verification_url)
    oauth.value = {
      status: stub ? 'stub' : (String(res.status ?? 'pending').toLowerCase() as OauthState['status']),
      verificationUri,
      userCode: String(res.user_code ?? res.code ?? ''),
      hint: stub
        ? '后端尚未启用真实 OAuth，当前为模拟授权流程'
        : verificationUri
          ? ''
          : '后端未返回可用的 https 授权地址，请以后端提示为准',
    }
    if (oauth.value.status === 'stub' || oauth.value.status === 'authorized') return
    const intervalSec = typeof res.interval === 'number' && res.interval > 0 ? res.interval : 3
    startPolling(p.pid, intervalSec * 1000, 0)
  } catch (e) {
    const stub501 = e instanceof PlatformApiError && e.status === 501
    oauth.value = {
      status: stub501 ? 'stub' : 'error',
      verificationUri: '',
      userCode: '',
      hint: stub501
        ? '后端尚未启用真实 OAuth，当前为模拟授权流程'
        : `授权发起失败：${platformErrText(e)}`,
    }
  } finally {
    oauthBusy.value = false
  }
}

function startPolling(pid: string, intervalMs: number, attempt: number, netRetries = 0) {
  stopPolling()
  if (attempt >= 40) {
    oauth.value = { ...oauth.value, status: oauth.value.status === 'authorized' ? 'authorized' : 'error', hint: '轮询超时，请重新发起授权' }
    return
  }
  pollTimer = setTimeout(async () => {
    try {
      const raw = await apiPost<Record<string, unknown>>(`/providers/auth/${encodeURIComponent(pid)}/poll`)
      const res = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
      const status = String(res.status ?? 'pending').toLowerCase()
      if (status === 'authorized' || status === 'stub') {
        oauth.value = { ...oauth.value, status: status === 'stub' ? 'stub' : 'authorized', hint: '' }
        await loadConfigs()
        return
      }
      if (status === 'error' || status === 'expired' || status === 'denied') {
        oauth.value = { ...oauth.value, status: 'error', hint: String(res.detail ?? res.message ?? '授权失败或已过期') }
        return
      }
      startPolling(pid, intervalMs, attempt + 1, 0)
    } catch (e) {
      // 后端诚实返回 501（OAuth 未接入）时按 stub 展示，不再走错误提示
      if (e instanceof PlatformApiError && e.status === 501) {
        oauth.value = { ...oauth.value, status: 'stub', hint: '后端尚未启用真实 OAuth，当前为模拟授权流程' }
        return
      }
      // 网络类错误：指数退避重试至多 3 次再放弃；鉴权等其他错误如实停止
      if (isNetworkError(e) && netRetries < OAUTH_POLL_MAX_NET_RETRIES) {
        startPolling(pid, intervalMs * 2 ** (netRetries + 1), attempt + 1, netRetries + 1)
        return
      }
      oauth.value = {
        ...oauth.value,
        status: 'error',
        hint: isNetworkError(e)
          ? `网络异常，退避重试 ${OAUTH_POLL_MAX_NET_RETRIES} 次后仍未连通，已停止轮询`
          : `轮询失败：${platformErrText(e)}`,
      }
    }
  }, intervalMs)
}

const oauthStatusLabel = computed(() => {
  switch (oauth.value.status) {
    case 'pending': return '等待授权'
    case 'authorized': return '已授权'
    case 'stub': return '模拟授权'
    case 'error': return '授权失败'
    default: return '未发起'
  }
})
const oauthStatusTone = computed<'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'>(() => {
  switch (oauth.value.status) {
    case 'authorized': return 'bamboo'
    case 'pending': return 'gold'
    case 'stub': return 'gold'
    case 'error': return 'rouge'
    default: return 'ink'
  }
})

/* ── 全局辅助模型 ── */
const auxForm = ref({ provider: '', model: '', purpose: '' })
const auxSaving = ref(false)
const auxSaveHint = ref('')
const auxError = ref('')

const auxProviderOptions = computed(() => {
  const capable = catalog.value.filter((p) => p.aux_capable !== false)
  return capable.length ? capable : catalog.value
})

async function saveAux() {
  if (auxSaving.value) return
  auxSaving.value = true
  auxSaveHint.value = ''
  auxError.value = ''
  try {
    await apiPut('/providers/aux', {
      pid: auxForm.value.provider,
      model: auxForm.value.model,
      purpose: auxForm.value.purpose,
    })
    auxCfg.value = { ...auxForm.value }
    auxSaveHint.value = '已保存'
  } catch (e) {
    auxError.value = `保存失败：${platformErrText(e)}`
  } finally {
    auxSaving.value = false
  }
}

onMounted(load)
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="providers-view">
    <PageHero
      seal="接"
      title="模型接入"
      en="MODEL PROVIDERS"
      sub="三十一家供应商一册总揽；密钥仅落本机，回显只见尾号。"
    />

    <!-- 统计带 -->
    <div class="stat-row">
      <GfStat label="已配置" :value="configuredCount" tone="bamboo" :hint="`目录共 ${catalog.length} 家`" />
      <GfStat label="已启用" :value="enabledCount" tone="dai" hint="启用后方可被工作台调用" />
      <GfStat label="辅助模型" :value="auxLabel" tone="gold" :hint="auxHint" />
    </div>

    <div v-if="error" class="notice error" role="alert" aria-live="polite">
      <span class="notice-text">{{ error }}</span>
      <GfButton variant="ghost" small :disabled="loading" @click="load">重试</GfButton>
    </div>

    <!-- 分组筛选 -->
    <div class="filter-bar">
      <div class="kind-tabs" role="tablist" aria-label="按类型筛选">
        <button
          class="kind-tab"
          :class="{ active: activeKind === 'all' }"
          type="button"
          role="tab"
          :aria-selected="activeKind === 'all'"
          @click="activeKind = 'all'"
        >全部 · {{ catalog.length }}</button>
        <button
          v-for="k in presentKinds"
          :key="k"
          class="kind-tab"
          :class="{ active: activeKind === k }"
          type="button"
          role="tab"
          :aria-selected="activeKind === k"
          @click="activeKind = k"
        >{{ KIND_LABELS[k] }} · {{ kindCounts[k] }}</button>
      </div>
      <div class="filter-side">
        <GfTag v-if="catalogOffline" tone="gold">离线数据</GfTag>
        <GfButton variant="ghost" small :disabled="loading" @click="load">{{ loading ? '研墨中…' : '刷新' }}</GfButton>
      </div>
    </div>

    <!-- 供应商卡片网格 -->
    <div v-if="loading && !catalog.length" class="muted">研墨中…</div>
    <div v-else-if="filteredCatalog.length" class="provider-grid">
      <button
        v-for="p in filteredCatalog"
        :key="p.pid"
        class="provider-card"
        :class="{ configured: isConfigured(p.pid) }"
        type="button"
        :title="`配置 ${p.name}`"
        @click="openDrawer(p)"
      >
        <div class="pc-head">
          <span class="pc-name">{{ p.name }}</span>
          <span
            class="status-dot"
            :class="{ on: isConfigured(p.pid) }"
            :title="isConfigured(p.pid) ? '已配置' : '未配置'"
            :aria-label="isConfigured(p.pid) ? '已配置' : '未配置'"
          ></span>
        </div>
        <div class="pc-kind">
          <GfTag :tone="KIND_TONES[normalizeKind(p.kind)]">{{ KIND_LABELS[normalizeKind(p.kind)] }}</GfTag>
          <GfTag v-if="configMap.get(p.pid)?.enabled" tone="bamboo">已启用</GfTag>
          <GfTag v-if="auxCfg?.provider === p.pid" tone="gold">辅助</GfTag>
        </div>
        <p class="pc-url">{{ p.base_url || '端点地址在配置时填写' }}</p>
        <div v-if="modelNames(p.models).length" class="pc-models">
          <GfTag v-for="m in modelNames(p.models).slice(0, 3)" :key="m" tone="ink">{{ m }}</GfTag>
        </div>
        <p v-if="p.note" class="pc-note">{{ p.note }}</p>
      </button>
    </div>
    <GfEmpty v-else text="此类型下暂无供应商。" />

    <InkDivider label="辅助模型" />

    <!-- 全局辅助模型 -->
    <GfCard title="全局辅助模型" seal="辅" class="aux-card">
      <p class="aux-desc">
        辅助模型承担摘要、记忆整理、标题生成等轻量后台任务，建议选用低价高速模型。
      </p>
      <form class="aux-form" @submit.prevent="saveAux">
        <label class="field">
          <span class="field-label">供应商</span>
          <select v-model="auxForm.provider" class="field-input" :disabled="auxSaving">
            <option value="">未选择</option>
            <option v-for="p in auxProviderOptions" :key="p.pid" :value="p.pid">{{ p.name }}</option>
          </select>
        </label>
        <label class="field">
          <span class="field-label">模型</span>
          <input
            v-model.trim="auxForm.model"
            class="field-input"
            :disabled="auxSaving"
            list="aux-model-list"
            placeholder="选择或输入模型 ID"
            autocomplete="off"
          />
          <datalist id="aux-model-list">
            <option
              v-for="m in modelNames(catalog.find((p) => p.pid === auxForm.provider)?.models)"
              :key="m"
              :value="m"
            />
          </datalist>
        </label>
        <label class="field field--wide">
          <span class="field-label">用途说明</span>
          <input
            v-model.trim="auxForm.purpose"
            class="field-input"
            :disabled="auxSaving"
            placeholder="例如：会话标题生成、记忆摘要、梦境归档初筛"
            autocomplete="off"
          />
        </label>
        <div class="aux-actions">
          <GfButton small :disabled="auxSaving || !auxForm.provider || !auxForm.model" @click="saveAux">
            {{ auxSaving ? '保存中…' : '保存辅助模型' }}
          </GfButton>
          <span v-if="auxSaveHint" class="hint-ok">{{ auxSaveHint }}</span>
          <span v-if="auxError" class="hint-err">{{ auxError }}</span>
        </div>
      </form>
    </GfCard>

    <!-- 配置抽屉 -->
    <div v-if="drawerOpen && activeProvider" class="drawer-backdrop" @click.self="closeDrawer">
      <aside class="drawer" role="dialog" aria-modal="true" :aria-label="`配置 ${activeProvider.name}`">
        <header class="drawer-hd">
          <div class="drawer-title">
            <span class="drawer-name">{{ activeProvider.name }}</span>
            <GfTag :tone="KIND_TONES[activeKind_]">{{ KIND_LABELS[activeKind_] }}</GfTag>
            <GfTag v-if="isConfigured(activeProvider.pid)" tone="bamboo">已配置</GfTag>
          </div>
          <button class="drawer-close" type="button" aria-label="关闭" @click="closeDrawer">×</button>
        </header>

        <form class="drawer-form" @submit.prevent="saveConfig">
          <label class="field">
            <span class="field-label">API Key</span>
            <input
              v-model="form.api_key"
              class="field-input"
              type="password"
              :disabled="saving"
              autocomplete="new-password"
              :placeholder="storedKeyTail ? '留空则保留已存密钥' : '输入 API Key'"
            />
            <span v-if="storedKeyTail" class="field-note">{{ storedKeyTail }}</span>
          </label>

          <label class="field">
            <span class="field-label">Base URL</span>
            <input
              v-model.trim="form.base_url"
              class="field-input"
              :disabled="saving"
              autocomplete="off"
              placeholder="https://…"
            />
          </label>

          <label class="field">
            <span class="field-label">模型</span>
            <input
              v-model.trim="form.model"
              class="field-input"
              :disabled="saving"
              list="provider-model-list"
              placeholder="选择推荐模型或自定义输入"
              autocomplete="off"
            />
            <datalist id="provider-model-list">
              <option v-for="m in activeModels" :key="m" :value="m" />
            </datalist>
          </label>

          <div class="switch-row">
            <label class="switch">
              <input v-model="form.enabled" type="checkbox" :disabled="saving" />
              <span class="switch-track"><span class="switch-knob"></span></span>
              <span class="switch-text">启用该供应商</span>
            </label>
          </div>

          <!-- OAuth 授权 -->
          <div v-if="activeKind_ === 'oauth'" class="oauth-block">
            <div class="oauth-head">
              <span class="oauth-title">授权登录</span>
              <GfTag :tone="oauthStatusTone">{{ oauthStatusLabel }}</GfTag>
            </div>
            <template v-if="oauth.verificationUri || oauth.userCode">
              <p class="oauth-line">
                请前往
                <a :href="oauth.verificationUri" target="_blank" rel="noopener noreferrer" class="oauth-link">
                  {{ oauth.verificationUri }}
                </a>
              </p>
              <p v-if="oauth.userCode" class="oauth-code">
                输入代码：<code>{{ oauth.userCode }}</code>
              </p>
            </template>
            <p v-if="oauth.hint" class="oauth-hint">{{ oauth.hint }}</p>
            <GfButton variant="ghost" small :disabled="oauthBusy || saving" @click="beginAuth">
              {{ oauthBusy ? '发起中…' : oauth.status === 'pending' ? '重新发起授权' : '授权登录' }}
            </GfButton>
          </div>

          <div class="drawer-actions">
            <button class="form-submit" type="submit" :disabled="saving || testing">
              {{ saving ? '保存中…' : '保存配置' }}
            </button>
            <GfButton variant="ghost" :disabled="saving || testing" @click="testConnection">
              {{ testing ? '测试中…' : '测试连通' }}
            </GfButton>
            <GfButton variant="ghost" :disabled="saving" @click="closeDrawer">取消</GfButton>
          </div>
          <span v-if="saveHint" class="hint-ok">{{ saveHint }}</span>
          <span v-if="testError" class="hint-err">{{ testError }}</span>
        </form>

        <div v-if="testResult" class="test-result" :class="{ ok: testOk, simulated: testIsSimulated }" aria-live="polite">
          <div class="tr-head">
            <GfTag :tone="testOk ? 'bamboo' : 'rouge'">{{ testOk ? '连通成功' : '连通失败' }}</GfTag>
            <GfTag v-if="testIsSimulated" tone="gold">模拟结果</GfTag>
          </div>
          <p class="tr-body">{{ testSummary }}</p>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.muted { color: var(--ink-soft); font-size: 13px; padding: 14px 0; font-family: var(--font-kai); letter-spacing: 2px; }

/* ── 统计带 ── */
.stat-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}

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
.notice-text { line-height: 1.6; }

/* ── 分组筛选 ── */
.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.kind-tabs { display: flex; flex-wrap: wrap; gap: 8px; }
.kind-tab {
  padding: 5px 16px;
  border-radius: 999px;
  border: 1px solid var(--gold-line);
  background: var(--card);
  color: var(--ink-soft);
  font-family: var(--font-kai);
  font-size: 12px;
  letter-spacing: 2px;
  transition: transform .18s ease, box-shadow .18s ease, background .18s ease, color .18s ease, border-color .18s ease;
}
.kind-tab:hover {
  transform: translateY(-2px);
  border-color: var(--rouge);
  color: var(--cinnabar);
  box-shadow: var(--shadow-glow-rouge);
}
.kind-tab.active {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-color: transparent;
  color: #FDF6E9;
  box-shadow: 0 2px 12px var(--cinnabar-glow), var(--shadow-card);
}
.filter-side { display: flex; align-items: center; gap: 10px; }

/* ── 供应商卡片网格 ── */
.provider-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(272px, 1fr));
  gap: 14px;
}
.provider-card {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: var(--shadow-card);
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.provider-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lift);
  border-color: var(--gold-line);
}
.provider-card.configured { border-color: color-mix(in srgb, var(--bamboo) 45%, transparent); }
.pc-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.pc-name {
  font-family: var(--font-kai);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 1px;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--line);
  border: 1px solid var(--line);
  transition: background .2s ease, box-shadow .2s ease;
}
.status-dot.on {
  background: var(--bamboo);
  border-color: var(--bamboo);
  box-shadow: 0 0 8px color-mix(in srgb, var(--bamboo) 55%, transparent);
}
.pc-kind { display: flex; flex-wrap: wrap; gap: 6px; }
.pc-url {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-muted);
  overflow-wrap: anywhere;
  line-height: 1.5;
}
.pc-models { display: flex; flex-wrap: wrap; gap: 6px; }
.pc-note { font-size: 11px; color: var(--ink-muted); letter-spacing: 1px; }

/* ── 表单元素（抽屉 / 辅助模型共用） ── */
.field { display: grid; gap: 6px; }
.field-label {
  color: var(--ink-muted);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 1px;
}
.field-input {
  min-width: 0;
  width: 100%;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 8px 12px;
  font: inherit;
  font-size: 12px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.field-input:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.field-input:disabled { opacity: .55; }
.field-note { font-size: 11px; color: var(--bamboo); letter-spacing: 1px; }

/* ── 开关 ── */
.switch-row { display: flex; flex-wrap: wrap; gap: 18px; }
.switch { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; }
.switch input { position: absolute; opacity: 0; width: 0; height: 0; }
.switch-track {
  width: 36px;
  height: 20px;
  border-radius: 999px;
  background: var(--line);
  border: 1px solid var(--line);
  display: inline-flex;
  align-items: center;
  padding: 2px;
  transition: background .2s ease, border-color .2s ease;
  flex-shrink: 0;
}
.switch-knob {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--card-solid);
  box-shadow: var(--shadow-card);
  transition: transform .2s ease;
}
.switch input:checked + .switch-track {
  background: var(--bamboo);
  border-color: var(--bamboo);
}
.switch input:checked + .switch-track .switch-knob { transform: translateX(16px); }
.switch input:focus-visible + .switch-track {
  outline: 2px solid var(--cinnabar);
  outline-offset: 2px;
}
.switch input:disabled + .switch-track { opacity: .55; }
.switch-text { font-size: 12px; color: var(--ink-soft); letter-spacing: 1px; }

/* ── 抽屉 ── */
.drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: color-mix(in srgb, var(--ink) 26%, transparent);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  display: flex;
  justify-content: flex-end;
  animation: fade-in .18s ease;
}
.drawer {
  width: min(440px, 94vw);
  height: 100%;
  overflow-y: auto;
  background: var(--card-solid);
  border-left: 1px solid var(--gold-line);
  box-shadow: var(--shadow-lift);
  padding: 22px 22px 30px;
  animation: slide-in .22s ease;
}
@keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes slide-in { from { transform: translateX(30px); opacity: .4; } to { transform: translateX(0); opacity: 1; } }
.drawer-hd {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line-soft);
  margin-bottom: 16px;
}
.drawer-title { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.drawer-name {
  font-family: var(--font-kai);
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 2px;
  color: var(--ink);
}
.drawer-close {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: var(--card);
  color: var(--ink-muted);
  font-size: 17px;
  line-height: 1;
  transition: border-color .18s ease, color .18s ease, transform .18s ease;
}
.drawer-close:hover { border-color: var(--rouge); color: var(--cinnabar); transform: rotate(90deg); }
.drawer-form { display: grid; gap: 14px; }
.drawer-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 4px; }

.form-submit {
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
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: 0 2px 12px var(--cinnabar-glow), var(--shadow-card);
  transition: transform .18s ease, box-shadow .18s ease;
}
.form-submit:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 4px 18px var(--cinnabar-glow), var(--shadow-glow-rouge); }
.form-submit:disabled { opacity: .55; cursor: not-allowed; transform: none; box-shadow: none; }

/* ── OAuth 区块 ── */
.oauth-block {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border: 1px dashed var(--gold-line);
  border-radius: var(--radius-small);
  background: color-mix(in srgb, var(--gold) 5%, transparent);
}
.oauth-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.oauth-title { font-family: var(--font-kai); font-size: 14px; letter-spacing: 2px; color: var(--ink); }
.oauth-line { font-size: 12px; color: var(--ink-soft); line-height: 1.7; overflow-wrap: anywhere; }
.oauth-link { color: var(--dai); border-bottom: 1px dashed var(--dai); }
.oauth-link:hover { color: var(--cinnabar); border-bottom-color: var(--cinnabar); }
.oauth-code { font-size: 12px; color: var(--ink-soft); }
.oauth-code code {
  font-family: var(--font-mono);
  font-size: 14px;
  letter-spacing: 2px;
  color: var(--cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 8%, transparent);
  padding: 2px 10px;
  border-radius: var(--radius-small);
}
.oauth-hint { font-size: 11px; color: var(--gold); letter-spacing: 1px; }

/* ── 测试结果 ── */
.test-result {
  margin-top: 16px;
  padding: 12px 14px;
  border-radius: var(--radius-small);
  border: 1px solid var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 6%, transparent);
}
.test-result.ok {
  border-color: color-mix(in srgb, var(--bamboo) 40%, transparent);
  background: color-mix(in srgb, var(--bamboo) 8%, transparent);
}
.tr-head { display: flex; gap: 8px; margin-bottom: 8px; }
.tr-body {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-soft);
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

/* ── 辅助模型 ── */
.aux-card { margin-bottom: 8px; }
.aux-desc { font-size: 12px; color: var(--ink-muted); letter-spacing: 1px; line-height: 1.7; margin-bottom: 14px; }
.aux-form {
  display: grid;
  grid-template-columns: minmax(150px, 1fr) minmax(170px, 1.2fr) minmax(220px, 2fr) auto;
  gap: 12px;
  align-items: end;
}
.aux-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.hint-ok { font-size: 11px; color: var(--bamboo); letter-spacing: 1px; }
.hint-err { font-size: 11px; color: var(--cinnabar-deep); letter-spacing: 1px; overflow-wrap: anywhere; }

@media (max-width: 900px) {
  .aux-form { grid-template-columns: repeat(2, minmax(150px, 1fr)); }
  .field--wide { grid-column: span 2; }
  .aux-actions { grid-column: span 2; }
}
@media (max-width: 620px) {
  .stat-row { grid-template-columns: 1fr; }
  .aux-form { grid-template-columns: 1fr; }
  .field--wide { grid-column: auto; }
  .aux-actions { grid-column: auto; }
  .drawer { width: 100vw; }
}
</style>

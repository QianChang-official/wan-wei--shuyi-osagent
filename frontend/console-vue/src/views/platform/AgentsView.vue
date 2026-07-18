<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { apiGet, apiPost, apiPut } from '@/api/platform'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import GfStat from '@/components/gf/GfStat.vue'
import InkDivider from '@/components/gf/InkDivider.vue'

/* ══ 契约类型（对应后端 platform_api/agents 模块约定） ══ */
type ThinkDepth = 'low' | 'medium' | 'high' | 'xhigh' | 'max' | 'ultracode'
type WorkGear = 'human_review' | 'sandbox' | 'device'
type RunStatus = 'queued' | 'running' | 'awaiting_review' | 'done' | 'failed'
type TeamMode = 'sequential' | 'parallel' | 'review_loop'
type TagTone = 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'

interface AgentPermissions {
  fs_read: boolean
  fs_write: boolean
  shell: boolean
  network: boolean
  git: boolean
}
interface AgentItem {
  id: string
  name: string
  role: string
  persona: string
  depth: ThinkDepth
  gear: WorkGear
  permissions: AgentPermissions
  provider_pid: string
  model: string
  goal: string
}
interface AgentTeam {
  id: string
  name: string
  members: string[]
  mode: TeamMode
  goal: string
}
interface AgentRun {
  id: string
  subject: string
  isTeam: boolean
  task: string
  goal: string
  depth: ThinkDepth
  gear: WorkGear
  status: RunStatus
  created_at: string
  note: string
  simulated: boolean
}
type AgentForm = Omit<AgentItem, 'id'>

/* ══ 共享枚举（与 backend deps.py 保持一致） ══ */
const DEPTHS: readonly ThinkDepth[] = ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode']
const DEPTH_LABELS: Record<ThinkDepth, string> = {
  low: '浅思',
  medium: '常思',
  high: '深思',
  xhigh: '极思',
  max: '穷思',
  ultracode: '超码',
}
const GEARS: readonly WorkGear[] = ['human_review', 'sandbox', 'device']
const GEAR_LABELS: Record<WorkGear, string> = {
  human_review: '人工审查',
  sandbox: '沙盒工作',
  device: '整台设备',
}
const GEAR_TONES: Record<WorkGear, TagTone> = {
  human_review: 'bamboo',
  sandbox: 'gold',
  device: 'rouge',
}
const GEAR_DESCS: Record<WorkGear, string> = {
  human_review: '每一步动作均需人工过目批准，最为稳妥。',
  sandbox: '动作限于沙箱之内，权限收敛、风险可控。',
  device: '动作直达整台设备，权限最大、风险最高，请谨慎授予。',
}
const RUN_STATUS_META: Record<RunStatus, { label: string; tone: TagTone }> = {
  queued: { label: '排队中', tone: 'ink' },
  running: { label: '运行中', tone: 'dai' },
  awaiting_review: { label: '待审查', tone: 'gold' },
  done: { label: '已完成', tone: 'bamboo' },
  failed: { label: '已失败', tone: 'rouge' },
}
const TEAM_MODE_META: Record<TeamMode, { label: string; desc: string }> = {
  sequential: { label: '顺序编排', desc: '成员依次接力，前者产出交予后者。' },
  parallel: { label: '并行编排', desc: '成员同时开工，结果汇总合并。' },
  review_loop: { label: '评审回路', desc: '实现与评审往复迭代，直至通过。' },
}
const PERMISSION_META: { key: keyof AgentPermissions; label: string; desc: string }[] = [
  { key: 'fs_read', label: '文件读取', desc: '读取本机文件内容' },
  { key: 'fs_write', label: '文件写入', desc: '新建或改写文件' },
  { key: 'shell', label: '命令执行', desc: '运行 shell 命令' },
  { key: 'network', label: '网络访问', desc: '发起出站网络请求' },
  { key: 'git', label: '版本管理', desc: '执行 git 提交与推送' },
]
const PERMISSION_MATRIX: { key: keyof AgentPermissions; label: string; cells: [string, string, string] }[] = [
  { key: 'fs_read', label: '文件读取', cells: ['每次读取前弹窗确认', '仅限工作目录沙箱内读取', '可读取设备任意路径'] },
  { key: 'fs_write', label: '文件写入', cells: ['每次写入前逐项审批', '仅限沙箱目录内写入', '可改写用户与系统任意文件'] },
  { key: 'shell', label: '命令执行', cells: ['命令逐条人工批准', '仅放行白名单内的受限命令', '完整 shell，任意命令直达设备'] },
  { key: 'network', label: '网络访问', cells: ['出站请求逐条确认', '仅白名单域名可访问', '不受限访问任意网络地址'] },
  { key: 'git', label: '版本管理', cells: ['提交与推送均需审批', '仅允许本地提交，禁止推送', '可推送远端乃至改写历史'] },
]

/* ══ 离线兜底示例数据（接口不可用时启用，并明确标注） ══ */
const SAMPLE_AGENTS: AgentItem[] = [
  {
    id: 'ag-wenxin', name: '文心', role: '架构师', persona: '沉静缜密，先画骨后落笔，方案必附权衡。',
    depth: 'high', gear: 'sandbox',
    permissions: { fs_read: true, fs_write: true, shell: false, network: false, git: true },
    provider_pid: 'kimi', model: 'kimi-k2', goal: '产出可评审的架构方案与拆分任务',
  },
  {
    id: 'ag-moyan', name: '墨研', role: '实现工程师', persona: '手快心细，代码先行，测试随行。',
    depth: 'ultracode', gear: 'sandbox',
    permissions: { fs_read: true, fs_write: true, shell: true, network: false, git: true },
    provider_pid: 'kimi', model: 'kimi-k2', goal: '把方案落成可运行的实现',
  },
  {
    id: 'ag-zhijian', name: '纸笺', role: '评审官', persona: '眼里揉不得沙，逐行挑错、按约验收。',
    depth: 'medium', gear: 'human_review',
    permissions: { fs_read: true, fs_write: false, shell: false, network: false, git: false },
    provider_pid: '', model: '', goal: '守住质量与权限边界',
  },
]
const SAMPLE_TEAMS: AgentTeam[] = [
  { id: 'tm-zizhu', name: '梓竹班', members: ['ag-wenxin', 'ag-moyan'], mode: 'sequential', goal: '从方案到实现的接力流水线' },
  { id: 'tm-meiying', name: '梅影会', members: ['ag-wenxin', 'ag-moyan', 'ag-zhijian'], mode: 'review_loop', goal: '实现与评审闭环，不出次品' },
]
const SAMPLE_RUNS: AgentRun[] = [
  {
    id: 'run-1042', subject: '墨研', isTeam: false, task: '重写 store 层缓存', goal: '读写延迟降低三成',
    depth: 'ultracode', gear: 'sandbox', status: 'running', created_at: new Date(Date.now() - 6 * 60_000).toISOString(), note: '', simulated: true,
  },
  {
    id: 'run-1041', subject: '文心', isTeam: false, task: '起草权限矩阵设计', goal: '覆盖五权三档',
    depth: 'high', gear: 'human_review', status: 'awaiting_review', created_at: new Date(Date.now() - 26 * 60_000).toISOString(), note: '方案已就绪，等待人工放行。', simulated: true,
  },
  {
    id: 'run-1039', subject: '梓竹班', isTeam: true, task: '整理周更 CHANGELOG', goal: '归档本周迭代',
    depth: 'medium', gear: 'sandbox', status: 'done', created_at: new Date(Date.now() - 2 * 3600_000).toISOString(), note: '', simulated: true,
  },
  {
    id: 'run-1038', subject: '纸笺', isTeam: false, task: '校验构建产物', goal: '确认产物可分发',
    depth: 'medium', gear: 'human_review', status: 'failed', created_at: new Date(Date.now() - 5 * 3600_000).toISOString(), note: '权限不足：shell 未开启。', simulated: true,
  },
]

/* ══ 归一化：对缺字段宽容，接口返回数组或 { items } 皆可 ══ */
function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' ? (v as Record<string, unknown>) : {}
}
function asList(raw: unknown): Record<string, unknown>[] {
  const src = Array.isArray(raw) ? raw : (Array.isArray(asRecord(raw).items) ? asRecord(raw).items : [])
  return (src as unknown[]).map(asRecord)
}
function pickStr(r: Record<string, unknown>, keys: string[], dft = ''): string {
  for (const k of keys) {
    const v = r[k]
    if (typeof v === 'string' && v.trim()) return v
  }
  return dft
}
function normDepth(v: unknown): ThinkDepth {
  return DEPTHS.includes(v as ThinkDepth) ? (v as ThinkDepth) : 'medium'
}
function normGear(v: unknown): WorkGear {
  return GEARS.includes(v as WorkGear) ? (v as WorkGear) : 'human_review'
}
function normStatus(v: unknown): RunStatus {
  const s = String(v ?? '')
  return s in RUN_STATUS_META ? (s as RunStatus) : 'queued'
}
function normMode(v: unknown): TeamMode {
  const s = String(v ?? '')
  return s in TEAM_MODE_META ? (s as TeamMode) : 'sequential'
}
function normPermissions(v: unknown): AgentPermissions {
  const r = asRecord(v)
  const b = (key: keyof AgentPermissions, dft: boolean) => (typeof r[key] === 'boolean' ? (r[key] as boolean) : dft)
  return {
    fs_read: b('fs_read', true),
    fs_write: b('fs_write', false),
    shell: b('shell', false),
    network: b('network', false),
    git: b('git', false),
  }
}
function normAgent(r: Record<string, unknown>, idx: number): AgentItem {
  return {
    id: pickStr(r, ['id', 'agent_id', 'pid'], `agent-${idx}`),
    name: pickStr(r, ['name', 'title'], '未名'),
    role: pickStr(r, ['role'], '通用智能体'),
    persona: pickStr(r, ['persona', 'bio', 'description']),
    depth: normDepth(r.depth),
    gear: normGear(r.gear),
    permissions: normPermissions(r.permissions),
    provider_pid: pickStr(r, ['provider_pid', 'provider']),
    model: pickStr(r, ['model']),
    goal: pickStr(r, ['goal', 'objective']),
  }
}
function normTeam(r: Record<string, unknown>, idx: number): AgentTeam {
  const rawMembers = Array.isArray(r.members) ? r.members : (Array.isArray(r.member_ids) ? r.member_ids : [])
  return {
    id: pickStr(r, ['id', 'team_id'], `team-${idx}`),
    name: pickStr(r, ['name', 'title'], '未名团队'),
    members: (rawMembers as unknown[]).map((m) => (typeof m === 'string' ? m : pickStr(asRecord(m), ['id', 'agent_id', 'name'], ''))).filter(Boolean),
    mode: normMode(r.mode ?? r.orchestration),
    goal: pickStr(r, ['goal', 'objective']),
  }
}
function normRun(r: Record<string, unknown>, idx: number): AgentRun {
  const teamName = pickStr(r, ['team_name'])
  const teamId = pickStr(r, ['team_id'])
  const isTeam = Boolean(teamName || teamId) || r.is_team === true
  return {
    id: pickStr(r, ['id', 'run_id'], `run-${idx}`),
    subject: teamName || pickStr(r, ['agent_name', 'name', 'agent_id'], teamId || '未名'),
    isTeam,
    task: pickStr(r, ['task', 'title']),
    goal: pickStr(r, ['goal', 'objective']),
    depth: normDepth(r.depth),
    gear: normGear(r.gear),
    status: normStatus(r.status),
    created_at: pickStr(r, ['created_at', 'started_at', 'updated_at']),
    note: pickStr(r, ['note', 'error', 'message', 'output']),
    simulated: r.simulated === true,
  }
}

/* ══ 状态 ══ */
const agents = ref<AgentItem[]>([])
const teams = ref<AgentTeam[]>([])
const runs = ref<AgentRun[]>([])
const loading = ref(true)
const error = ref('')
const note = ref('')
const agentsOffline = ref(false)
const teamsOffline = ref(false)
const runsOffline = ref(false)

const selectedId = ref<string | null>(null)
const editingId = ref<string | null>(null)
const saving = ref(false)
const form = ref<AgentForm>(emptyAgentForm())

const runType = ref<'agent' | 'team'>('agent')
const runTarget = ref('')
const runTask = ref('')
const runGoal = ref('')
const runDepth = ref<ThinkDepth>('medium')
const runGear = ref<WorkGear>('human_review')
const dispatching = ref(false)
const approvingId = ref('')

const teamModalOpen = ref(false)
const teamSaving = ref(false)
const teamEditingId = ref<string | null>(null)
const teamForm = ref<{ name: string; goal: string; mode: TeamMode; members: string[] }>({ name: '', goal: '', mode: 'sequential', members: [] })

/* ══ 派生 ══ */
const runningCount = computed(() => runs.value.filter((r) => r.status === 'running').length)
const awaitingCount = computed(() => runs.value.filter((r) => r.status === 'awaiting_review').length)
const offline = computed(() => agentsOffline.value || teamsOffline.value || runsOffline.value)
const isCreating = computed(() => editingId.value === null)
const runTargets = computed(() => (runType.value === 'agent' ? agents.value : teams.value))

function agentName(id: string): string {
  return agents.value.find((a) => a.id === id)?.name || id
}
function fmtTime(v: string): string {
  if (!v) return '—'
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString('zh-CN', { hour12: false })
}
function emptyAgentForm(): AgentForm {
  return {
    name: '',
    role: '',
    persona: '',
    depth: 'medium',
    gear: 'human_review',
    permissions: { fs_read: true, fs_write: false, shell: false, network: false, git: false },
    provider_pid: '',
    model: '',
    goal: '',
  }
}

/* ══ 加载 ══ */
async function loadAgents() {
  try {
    const raw = await apiGet<unknown>('/agents')
    agents.value = asList(raw).map(normAgent)
    agentsOffline.value = false
  } catch {
    agentsOffline.value = true
    if (!agents.value.length) agents.value = [...SAMPLE_AGENTS]
  }
}
async function loadTeams() {
  try {
    const raw = await apiGet<unknown>('/agents/teams')
    teams.value = asList(raw).map(normTeam)
    teamsOffline.value = false
  } catch {
    teamsOffline.value = true
    if (!teams.value.length) teams.value = [...SAMPLE_TEAMS]
  }
}
async function loadRuns() {
  try {
    const raw = await apiGet<unknown>('/agents/runs')
    runs.value = asList(raw).map(normRun)
    runsOffline.value = false
  } catch {
    runsOffline.value = true
    if (!runs.value.length) runs.value = [...SAMPLE_RUNS]
  }
}
async function loadAll() {
  loading.value = true
  error.value = ''
  await Promise.all([loadAgents(), loadTeams(), loadRuns()])
  loading.value = false
}

/* ══ 智能体选择与编辑 ══ */
function selectAgent(agent: AgentItem) {
  selectedId.value = agent.id
  editingId.value = agent.id
  form.value = { ...agent, permissions: { ...agent.permissions } }
  note.value = ''
  error.value = ''
}
function startNewAgent() {
  selectedId.value = null
  editingId.value = null
  form.value = emptyAgentForm()
  note.value = ''
  error.value = ''
}
function depthIndex(d: ThinkDepth): number {
  const i = DEPTHS.indexOf(d)
  return i < 0 ? 1 : i
}
function onAgentDepth(e: Event) {
  const v = Math.round(Number((e.target as HTMLInputElement).value))
  form.value.depth = DEPTHS[Math.min(5, Math.max(0, Number.isNaN(v) ? 1 : v))]
}
function onRunDepth(e: Event) {
  const v = Math.round(Number((e.target as HTMLInputElement).value))
  runDepth.value = DEPTHS[Math.min(5, Math.max(0, Number.isNaN(v) ? 1 : v))]
}
function setAgentGear(g: WorkGear) {
  form.value.gear = g
}
function setRunGear(g: WorkGear) {
  runGear.value = g
}

async function saveAgent() {
  if (saving.value) return
  const name = form.value.name.trim()
  if (!name) {
    error.value = '请先为智能体取名。'
    return
  }
  saving.value = true
  error.value = ''
  note.value = ''
  const payload = { ...form.value, name, role: form.value.role.trim() || '通用智能体' }
  const id = editingId.value
  try {
    if (agentsOffline.value) throw new Error('offline')
    if (id) await apiPut(`/agents/${encodeURIComponent(id)}`, payload)
    else await apiPost('/agents', payload)
    await loadAgents()
    note.value = id ? `「${name}」已保存。` : `「${name}」已入谱。`
    if (!id) {
      const created = agents.value.find((a) => a.name === name)
      if (created) selectAgent(created)
    }
  } catch (e) {
    if (agentsOffline.value) {
      // 离线兜底：仅写入当前页面状态，刷新后还原
      if (id) {
        agents.value = agents.value.map((a) => (a.id === id ? { ...payload, id } : a))
      } else {
        const localId = `local-${Date.now()}`
        agents.value = [...agents.value, { ...payload, id: localId }]
        selectedId.value = localId
        editingId.value = localId
      }
      note.value = '离线模式：改动仅暂存于本页，刷新后还原。'
    } else {
      error.value = e instanceof Error ? e.message : String(e)
    }
  } finally {
    saving.value = false
  }
}

/* ══ 发起编排 ══ */
async function dispatchRun() {
  if (dispatching.value) return
  const task = runTask.value.trim()
  if (!runTarget.value) {
    error.value = runType.value === 'agent' ? '请选择一位智能体。' : '请选择一支团队。'
    return
  }
  if (!task) {
    error.value = '请填写任务内容。'
    return
  }
  dispatching.value = true
  error.value = ''
  note.value = ''
  const payload = {
    ...(runType.value === 'agent' ? { agent_id: runTarget.value } : { team_id: runTarget.value }),
    task,
    goal: runGoal.value.trim(),
    depth: runDepth.value,
    gear: runGear.value,
  }
  const subject = runType.value === 'agent' ? agentName(runTarget.value) : (teams.value.find((t) => t.id === runTarget.value)?.name || runTarget.value)
  try {
    if (agentsOffline.value && teamsOffline.value) throw new Error('offline')
    await apiPost('/agents/run', payload)
    note.value = `已遣「${subject}」承办：${task}`
    runTask.value = ''
    runGoal.value = ''
    await loadRuns()
  } catch (e) {
    if (agentsOffline.value || teamsOffline.value || runsOffline.value) {
      runs.value = [
        {
          id: `local-run-${Date.now()}`,
          subject,
          isTeam: runType.value === 'team',
          task,
          goal: runGoal.value.trim(),
          depth: runDepth.value,
          gear: runGear.value,
          status: 'queued',
          created_at: new Date().toISOString(),
          note: '',
          simulated: true,
        },
        ...runs.value,
      ]
      runTask.value = ''
      runGoal.value = ''
      note.value = '离线模式：已生成一条模拟运行记录，不会真正执行。'
    } else {
      error.value = e instanceof Error ? e.message : String(e)
    }
  } finally {
    dispatching.value = false
  }
}

/* ══ 运行监视 ══ */
async function approveRun(run: AgentRun) {
  if (approvingId.value) return
  approvingId.value = run.id
  error.value = ''
  note.value = ''
  try {
    if (run.simulated || runsOffline.value) throw new Error('offline')
    await apiPost(`/agents/runs/${encodeURIComponent(run.id)}/approve`, {})
    await loadRuns()
    note.value = `已放行运行 ${run.id}。`
  } catch (e) {
    if (run.simulated || runsOffline.value) {
      runs.value = runs.value.map((r) => (r.id === run.id ? { ...r, status: 'done', note: '离线模式：本地模拟放行。' } : r))
      note.value = '离线模式：已在本地模拟放行。'
    } else {
      error.value = e instanceof Error ? e.message : String(e)
    }
  } finally {
    approvingId.value = ''
  }
}

/* ══ 团队管理 ══ */
const AVATAR_TONES = ['rouge', 'dai', 'bamboo', 'gold'] as const
function avatarTone(seed: string): (typeof AVATAR_TONES)[number] {
  let h = 0
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return AVATAR_TONES[h % AVATAR_TONES.length]
}
function openNewTeam() {
  teamEditingId.value = null
  teamForm.value = { name: '', goal: '', mode: 'sequential', members: [] }
  teamModalOpen.value = true
}
function openEditTeam(team: AgentTeam) {
  teamEditingId.value = team.id
  teamForm.value = { name: team.name, goal: team.goal, mode: team.mode, members: [...team.members] }
  teamModalOpen.value = true
}
function closeTeamModal() {
  if (teamSaving.value) return
  teamModalOpen.value = false
}
function toggleTeamMember(id: string) {
  const members = teamForm.value.members
  teamForm.value.members = members.includes(id) ? members.filter((m) => m !== id) : [...members, id]
}
function setTeamMode(mode: TeamMode) {
  teamForm.value.mode = mode
}
async function saveTeam() {
  if (teamSaving.value) return
  const name = teamForm.value.name.trim()
  if (!name) {
    error.value = '请先为团队取名。'
    return
  }
  if (!teamForm.value.members.length) {
    error.value = '团队至少需一名成员。'
    return
  }
  teamSaving.value = true
  error.value = ''
  note.value = ''
  const payload = { name, goal: teamForm.value.goal.trim(), mode: teamForm.value.mode, members: teamForm.value.members }
  const id = teamEditingId.value
  try {
    if (teamsOffline.value) throw new Error('offline')
    if (id) await apiPut(`/agents/teams/${encodeURIComponent(id)}`, payload)
    else await apiPost('/agents/teams', payload)
    await loadTeams()
    teamModalOpen.value = false
    note.value = id ? `团队「${name}」已保存。` : `团队「${name}」已建班。`
  } catch (e) {
    if (teamsOffline.value) {
      if (id) teams.value = teams.value.map((t) => (t.id === id ? { ...payload, id } : t))
      else teams.value = [...teams.value, { ...payload, id: `local-team-${Date.now()}` }]
      teamModalOpen.value = false
      note.value = '离线模式：团队改动仅暂存于本页，刷新后还原。'
    } else {
      error.value = e instanceof Error ? e.message : String(e)
    }
  } finally {
    teamSaving.value = false
  }
}

/* ══ 轮询：运行监视每 5 秒 ══ */
let timer: number | undefined
onMounted(async () => {
  await loadAll()
  timer = window.setInterval(loadRuns, 5000)
})
onUnmounted(() => {
  if (timer !== undefined) window.clearInterval(timer)
})
</script>

<template>
  <div class="agents-view">
    <PageHero
      seal="智"
      title="百工智府"
      en="AGENT ORCHESTRATION"
      sub="择智能体或班组，定深度、授档位、遣任务；运行全程可监视，待审一键放行。"
    />

    <!-- 概览统计 -->
    <div class="stat-row">
      <GfStat label="智能体" :value="agents.length" tone="dai" hint="在谱成员" />
      <GfStat label="团队" :value="teams.length" tone="bamboo" hint="已成班组" />
      <GfStat label="运行中" :value="runningCount" tone="rouge" hint="正在承办" />
      <GfStat label="待审查" :value="awaitingCount" tone="gold" hint="静候放行" />
    </div>

    <!-- 提示条 -->
    <div v-if="offline" class="notice warn" role="status">
      <span class="notice-text">后端接口暂不可达，当前展示本地示例数据，改动不会持久化。</span>
      <GfTag tone="gold">离线示例</GfTag>
    </div>
    <div v-if="error" class="notice error" role="alert" aria-live="polite">
      <span class="notice-text">{{ error }}</span>
      <GfButton variant="ghost" small @click="error = ''">知道了</GfButton>
    </div>
    <div v-if="note" class="notice ok" role="status" aria-live="polite">
      <span class="notice-text">{{ note }}</span>
      <GfButton variant="ghost" small @click="note = ''">收起</GfButton>
    </div>

    <!-- 发起编排 -->
    <GfCard title="发起编排" seal="遣" class="dispatch-bar">
      <div class="dispatch-grid">
        <div class="field field-target">
          <span class="field-label">承办者</span>
          <div class="seg">
            <button type="button" class="seg-item" :class="{ active: runType === 'agent' }" @click="runType = 'agent'; runTarget = ''">智能体</button>
            <button type="button" class="seg-item" :class="{ active: runType === 'team' }" @click="runType = 'team'; runTarget = ''">团队</button>
          </div>
          <select v-model="runTarget" class="input" :disabled="!runTargets.length">
            <option value="" disabled>{{ runType === 'agent' ? '择一智能体' : '择一团队' }}</option>
            <option v-for="t in runTargets" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </div>
        <label class="field field-task">
          <span class="field-label">任务</span>
          <input v-model="runTask" class="input" placeholder="例如：重构缓存层并补全测试" maxlength="200" />
        </label>
        <label class="field field-goal">
          <span class="field-label">目标</span>
          <input v-model="runGoal" class="input" placeholder="验收标准，可留空" maxlength="200" />
        </label>
        <div class="field field-depth">
          <span class="field-label">思考深度 · <b class="kai">{{ DEPTH_LABELS[runDepth] }}</b></span>
          <input type="range" min="0" max="5" step="1" :value="depthIndex(runDepth)" class="depth-range" @input="onRunDepth" />
        </div>
        <div class="field field-gear">
          <span class="field-label">工作档位</span>
          <div class="seg">
            <button
              v-for="g in GEARS" :key="g" type="button"
              class="seg-item" :class="{ active: runGear === g, danger: g === 'device' && runGear === g }"
              @click="setRunGear(g)"
            >{{ GEAR_LABELS[g] }}</button>
          </div>
        </div>
        <div class="field field-go">
          <GfButton :disabled="dispatching" @click="dispatchRun">{{ dispatching ? '遣派中…' : '发起编排' }}</GfButton>
        </div>
      </div>
    </GfCard>

    <!-- 三栏主区 -->
    <div class="tri-grid">
      <!-- 左：智能体列表 -->
      <GfCard title="智囊谱" seal="谱" class="col">
        <template #header>
          <span class="gf-card-seal">谱</span>
          <h3 class="gf-card-title">智囊谱</h3>
          <GfButton variant="ghost" small class="hd-action" @click="startNewAgent">新建</GfButton>
        </template>
        <div v-if="loading" class="muted">研墨中…</div>
        <template v-else>
          <ul v-if="agents.length" class="agent-list">
            <li v-for="agent in agents" :key="agent.id">
              <button
                type="button"
                class="agent-item" :class="{ active: selectedId === agent.id }"
                @click="selectAgent(agent)"
              >
                <span class="agent-avatar" :data-tone="avatarTone(agent.name)">{{ agent.name.slice(0, 1) }}</span>
                <span class="agent-main">
                  <span class="agent-name">{{ agent.name }}<i class="agent-role">{{ agent.role }}</i></span>
                  <span class="agent-tags">
                    <GfTag tone="dai">{{ DEPTH_LABELS[agent.depth] }}</GfTag>
                    <GfTag :tone="GEAR_TONES[agent.gear]">{{ GEAR_LABELS[agent.gear] }}</GfTag>
                  </span>
                </span>
              </button>
            </li>
          </ul>
          <GfEmpty v-else text="尚无智能体。点右上「新建」造第一位吧。" />
        </template>
      </GfCard>

      <!-- 中：详情编辑 -->
      <GfCard :title="isCreating ? '新造智能体' : `养性 · ${form.name || '未名'}`" seal="性" class="col">
        <form class="agent-form" @submit.prevent="saveAgent">
          <div class="form-row two">
            <label class="field">
              <span class="field-label">名称</span>
              <input v-model="form.name" class="input" required maxlength="24" placeholder="如：文心" />
            </label>
            <label class="field">
              <span class="field-label">角色</span>
              <input v-model="form.role" class="input" maxlength="24" placeholder="如：架构师" />
            </label>
          </div>
          <label class="field">
            <span class="field-label">人设</span>
            <textarea v-model="form.persona" class="input area" rows="2" maxlength="200" placeholder="性情、行事风格、口头禅…"></textarea>
          </label>
          <label class="field">
            <span class="field-label">目标</span>
            <input v-model="form.goal" class="input" maxlength="120" placeholder="这位智能体的默认验收目标" />
          </label>
          <div class="form-row two">
            <label class="field">
              <span class="field-label">provider_pid</span>
              <input v-model="form.provider_pid" class="input mono" maxlength="64" placeholder="模型接入配置 id" autocomplete="off" />
            </label>
            <label class="field">
              <span class="field-label">model</span>
              <input v-model="form.model" class="input mono" maxlength="64" placeholder="模型名" autocomplete="off" />
            </label>
          </div>

          <div class="field">
            <span class="field-label">思考深度 · <b class="kai">{{ DEPTH_LABELS[form.depth] }}</b></span>
            <input type="range" min="0" max="5" step="1" :value="depthIndex(form.depth)" class="depth-range" @input="onAgentDepth" />
            <div class="depth-ticks" aria-hidden="true">
              <span v-for="d in DEPTHS" :key="d" :class="{ on: d === form.depth }">{{ DEPTH_LABELS[d] }}</span>
            </div>
          </div>

          <div class="field">
            <span class="field-label">工作档位</span>
            <div class="seg">
              <button
                v-for="g in GEARS" :key="g" type="button"
                class="seg-item" :class="{ active: form.gear === g, danger: g === 'device' && form.gear === g }"
                @click="setAgentGear(g)"
              >{{ GEAR_LABELS[g] }}</button>
            </div>
            <p class="gear-hint" :class="{ danger: form.gear === 'device' }">{{ GEAR_DESCS[form.gear] }}</p>
          </div>

          <div class="field">
            <span class="field-label">权限五事</span>
            <ul class="perm-list">
              <li v-for="p in PERMISSION_META" :key="p.key">
                <label class="perm-item">
                  <span class="perm-text">
                    <b>{{ p.label }}</b>
                    <i>{{ p.desc }}</i>
                  </span>
                  <span class="switch" :class="{ on: form.permissions[p.key] }">
                    <input v-model="form.permissions[p.key]" type="checkbox" :aria-label="p.label" />
                    <span class="knob" aria-hidden="true"></span>
                  </span>
                </label>
              </li>
            </ul>
          </div>

          <div class="form-actions">
            <button class="form-submit" type="submit" :disabled="saving">{{ saving ? '保存中…' : isCreating ? '造此智能体' : '保存修改' }}</button>
            <button class="form-cancel" type="button" :disabled="saving" @click="startNewAgent">清空重填</button>
          </div>
        </form>
      </GfCard>

      <!-- 右：运行监视 -->
      <GfCard title="走马灯" seal="巡" class="col">
        <template #header>
          <span class="gf-card-seal">巡</span>
          <h3 class="gf-card-title">走马灯</h3>
          <GfTag tone="ink" class="hd-action">5s 轮询</GfTag>
        </template>
        <div v-if="loading" class="muted">研墨中…</div>
        <template v-else>
          <ul v-if="runs.length" class="run-list">
            <li v-for="run in runs" :key="run.id" class="run-item">
              <div class="run-head">
                <span class="run-subject">{{ run.subject }}<i v-if="run.isTeam" class="run-kind">班组</i></span>
                <span class="run-tags">
                  <GfTag v-if="run.simulated" tone="gold">模拟</GfTag>
                  <GfTag :tone="RUN_STATUS_META[run.status].tone">{{ RUN_STATUS_META[run.status].label }}</GfTag>
                </span>
              </div>
              <p class="run-task">{{ run.task || '（未述任务）' }}</p>
              <p v-if="run.goal" class="run-goal">目标：{{ run.goal }}</p>
              <div class="run-meta">
                <GfTag tone="dai">{{ DEPTH_LABELS[run.depth] }}</GfTag>
                <GfTag :tone="GEAR_TONES[run.gear]">{{ GEAR_LABELS[run.gear] }}</GfTag>
                <span class="run-time">{{ fmtTime(run.created_at) }}</span>
              </div>
              <p v-if="run.note" class="run-note" :class="{ danger: run.status === 'failed' }">{{ run.note }}</p>
              <div v-if="run.status === 'awaiting_review'" class="run-actions">
                <GfButton small :disabled="!!approvingId" @click="approveRun(run)">
                  {{ approvingId === run.id ? '放行中…' : '审查通过 · 放行' }}
                </GfButton>
              </div>
            </li>
          </ul>
          <GfEmpty v-else text="尚无运行记录。自上方「发起编排」遣出第一单。" />
        </template>
      </GfCard>
    </div>

    <InkDivider label="群英成班" />

    <!-- 团队管理区 -->
    <GfCard title="群英班" seal="班">
      <template #header>
        <span class="gf-card-seal">班</span>
        <h3 class="gf-card-title">群英班</h3>
        <GfButton variant="ghost" small class="hd-action" @click="openNewTeam">新建团队</GfButton>
      </template>
      <div v-if="teams.length" class="team-grid">
        <article v-for="team in teams" :key="team.id" class="team-card">
          <div class="team-head">
            <h4 class="team-name">{{ team.name }}</h4>
            <GfTag tone="gold">{{ TEAM_MODE_META[team.mode].label }}</GfTag>
          </div>
          <p class="team-mode-desc">{{ TEAM_MODE_META[team.mode].desc }}</p>
          <div class="team-members">
            <span
              v-for="m in team.members" :key="m"
              class="agent-avatar small" :data-tone="avatarTone(agentName(m))"
              :title="agentName(m)"
            >{{ agentName(m).slice(0, 1) }}</span>
            <span v-if="!team.members.length" class="muted-inline">尚无成员</span>
          </div>
          <p v-if="team.goal" class="team-goal">目标：{{ team.goal }}</p>
          <div class="team-actions">
            <GfButton variant="ghost" small @click="openEditTeam(team)">编辑</GfButton>
          </div>
        </article>
      </div>
      <GfEmpty v-else text="尚无团队。点右上「新建团队」起第一个班。" />
    </GfCard>

    <!-- 权限矩阵说明卡 -->
    <GfCard title="权限矩阵" seal="矩" class="matrix-card">
      <p class="matrix-intro">五事权限随档位层层放开：人工审查逐条过目，沙盒工作圈地为牢，整台设备长驱直入。</p>
      <div class="table-wrap">
        <table class="matrix-table">
          <thead>
            <tr>
              <th scope="col">权限</th>
              <th scope="col">人工审查</th>
              <th scope="col">沙盒工作</th>
              <th scope="col" class="th-danger">整台设备</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in PERMISSION_MATRIX" :key="row.key">
              <th scope="row">{{ row.label }}</th>
              <td v-for="(cell, i) in row.cells" :key="i" :class="{ 'cell-danger': i === 2 }">{{ cell }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="notice error matrix-warn" role="note">
        <span class="notice-text">警示：「整台设备」档位下，权限将直接作用于宿主机——任意路径读写、任意命令执行、任意网络访问皆不再设防。仅授予完全可信的智能体，并配合人工审查其关键动作。</span>
      </div>
    </GfCard>

    <!-- 团队编辑弹层 -->
    <div v-if="teamModalOpen" class="modal-mask" @click.self="closeTeamModal">
      <div class="modal" role="dialog" aria-modal="true" :aria-label="teamEditingId ? '编辑团队' : '新建团队'">
        <h3 class="modal-title">{{ teamEditingId ? '编辑团队' : '新建团队' }}</h3>
        <label class="field">
          <span class="field-label">团队名称</span>
          <input v-model="teamForm.name" class="input" maxlength="24" placeholder="如：梓竹班" />
        </label>
        <label class="field">
          <span class="field-label">团队目标</span>
          <input v-model="teamForm.goal" class="input" maxlength="120" placeholder="这班人马为何而立" />
        </label>
        <div class="field">
          <span class="field-label">编排模式</span>
          <div class="seg">
            <button
              v-for="(meta, mode) in TEAM_MODE_META" :key="mode" type="button"
              class="seg-item" :class="{ active: teamForm.mode === mode }"
              @click="setTeamMode(mode)"
            >{{ meta.label }}</button>
          </div>
          <p class="gear-hint">{{ TEAM_MODE_META[teamForm.mode].desc }}</p>
        </div>
        <div class="field">
          <span class="field-label">团队成员（{{ teamForm.members.length }}）</span>
          <ul v-if="agents.length" class="member-pick">
            <li v-for="agent in agents" :key="agent.id">
              <button
                type="button"
                class="member-chip" :class="{ on: teamForm.members.includes(agent.id) }"
                @click="toggleTeamMember(agent.id)"
              >
                <span class="agent-avatar mini" :data-tone="avatarTone(agent.name)">{{ agent.name.slice(0, 1) }}</span>
                {{ agent.name }}
              </button>
            </li>
          </ul>
          <p v-else class="muted-inline">尚无智能体可选，请先在左侧「智囊谱」新建。</p>
        </div>
        <div class="form-actions">
          <button class="form-submit" type="button" :disabled="teamSaving" @click="saveTeam">{{ teamSaving ? '保存中…' : '保存团队' }}</button>
          <button class="form-cancel" type="button" :disabled="teamSaving" @click="closeTeamModal">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agents-view { padding-bottom: 28px; }

/* ── 概览统计 ── */
.stat-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }

/* ── 提示条 ── */
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
.notice.warn { color: color-mix(in srgb, var(--gold) 80%, var(--ink)); border-color: var(--gold-line); background: color-mix(in srgb, var(--gold) 8%, transparent); }
.notice.error { color: var(--cinnabar-deep); border-color: var(--line-cinnabar); background: color-mix(in srgb, var(--cinnabar) 7%, transparent); }
.notice.ok { color: color-mix(in srgb, var(--bamboo) 70%, var(--ink)); border-color: color-mix(in srgb, var(--bamboo) 40%, transparent); background: color-mix(in srgb, var(--bamboo) 9%, transparent); }
.notice-text { line-height: 1.6; }

/* ── 发起编排条 ── */
.dispatch-bar { margin-bottom: 20px; }
.dispatch-grid { display: grid; grid-template-columns: 220px 1.4fr 1fr 200px 230px auto; gap: 14px; align-items: end; }
.field { display: grid; gap: 6px; align-content: start; }
.field-label { color: var(--ink-muted); font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px; }
.kai { font-family: var(--font-kai); color: var(--gold); letter-spacing: 2px; }

.input {
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
.input:focus { outline: none; border-color: var(--cinnabar); box-shadow: 0 0 0 3px var(--rouge-glow); }
.input:disabled { opacity: .55; }
.input.mono { font-family: var(--font-mono); font-size: 11px; }
.area { resize: vertical; min-height: 52px; }
select.input { appearance: auto; cursor: pointer; }

/* ── 分段选择器 ── */
.seg {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--gold-line);
  border-radius: 999px;
  background: color-mix(in srgb, var(--gold) 6%, transparent);
}
.seg-item {
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--ink-soft);
  padding: 5px 13px;
  font-size: 12px;
  font-family: var(--font-kai);
  letter-spacing: 1px;
  transition: background .18s ease, color .18s ease, box-shadow .18s ease;
}
.seg-item:hover { color: var(--cinnabar); }
.seg-item.active {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: 0 2px 10px var(--cinnabar-glow);
}
.seg-item.active.danger {
  background: var(--card);
  border-color: var(--cinnabar);
  color: var(--cinnabar);
  box-shadow: 0 0 0 2px var(--cinnabar-glow);
}

/* ── 深度滑档 ── */
.depth-range { width: 100%; accent-color: var(--cinnabar); cursor: pointer; }
.depth-ticks { display: flex; justify-content: space-between; margin-top: 2px; }
.depth-ticks span { font-family: var(--font-kai); font-size: 11px; letter-spacing: 1px; color: var(--ink-muted); transition: color .18s ease; }
.depth-ticks span.on { color: var(--cinnabar); font-weight: 700; }
.gear-hint { font-size: 11px; color: var(--ink-muted); line-height: 1.6; }
.gear-hint.danger { color: var(--cinnabar); }

/* ── 三栏主区 ── */
.tri-grid { display: grid; grid-template-columns: 300px minmax(0, 1fr) 350px; gap: 16px; align-items: start; }
.col { min-width: 0; }
.hd-action { margin-left: auto; }
.muted { color: var(--ink-soft); font-size: 13px; padding: 14px 0; font-family: var(--font-kai); letter-spacing: 2px; }
.muted-inline { font-size: 12px; color: var(--ink-muted); }

/* ── 左栏：智能体列表 ── */
.agent-list { list-style: none; display: grid; gap: 10px; }
.agent-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  text-align: left;
  padding: 10px 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-card);
  background: color-mix(in srgb, var(--card-solid) 55%, transparent);
  cursor: pointer;
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease, background .18s ease;
}
.agent-item:hover { transform: translateY(-2px); border-color: var(--gold-line); box-shadow: var(--shadow-card); }
.agent-item.active { border-color: var(--rouge); background: color-mix(in srgb, var(--rouge) 8%, transparent); box-shadow: var(--shadow-glow-rouge); }
.agent-avatar {
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  font-family: var(--font-kai);
  font-size: 16px;
  font-weight: 700;
  color: #FDF6E9;
  background: var(--dai);
  box-shadow: var(--shadow-card);
}
.agent-avatar[data-tone='rouge'] { background: linear-gradient(135deg, var(--rouge), var(--cinnabar)); }
.agent-avatar[data-tone='dai'] { background: linear-gradient(135deg, var(--dai), var(--dai-deep)); }
.agent-avatar[data-tone='bamboo'] { background: linear-gradient(135deg, var(--bamboo), color-mix(in srgb, var(--bamboo) 70%, var(--ink))); }
.agent-avatar[data-tone='gold'] { background: linear-gradient(135deg, var(--gold), color-mix(in srgb, var(--gold) 70%, var(--ink))); }
.agent-avatar.small { width: 30px; height: 30px; font-size: 13px; }
.agent-avatar.mini { width: 20px; height: 20px; font-size: 11px; box-shadow: none; }
.agent-main { display: grid; gap: 6px; min-width: 0; }
.agent-name { font-family: var(--font-kai); font-size: 15px; font-weight: 700; letter-spacing: 2px; color: var(--ink); display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.agent-role { font-style: normal; font-family: var(--font-sans); font-size: 11px; font-weight: 400; letter-spacing: 1px; color: var(--ink-muted); }
.agent-tags { display: flex; gap: 6px; flex-wrap: wrap; }

/* ── 中栏：编辑表单 ── */
.agent-form { display: grid; gap: 14px; }
.form-row.two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.perm-list { list-style: none; display: grid; gap: 8px; }
.perm-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: color-mix(in srgb, var(--card-solid) 45%, transparent);
  cursor: pointer;
  transition: border-color .18s ease;
}
.perm-item:hover { border-color: var(--gold-line); }
.perm-text { display: grid; gap: 2px; }
.perm-text b { font-size: 12px; color: var(--ink); letter-spacing: 1px; }
.perm-text i { font-style: normal; font-size: 11px; color: var(--ink-muted); }
.switch { position: relative; flex-shrink: 0; width: 40px; height: 22px; border-radius: 999px; background: var(--line); transition: background .2s ease; }
.switch input { position: absolute; inset: 0; opacity: 0; cursor: pointer; margin: 0; }
.switch .knob { position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%; background: var(--card-solid); box-shadow: var(--shadow-card); transition: transform .2s ease; pointer-events: none; }
.switch.on { background: var(--bamboo); }
.switch.on .knob { transform: translateX(18px); }
.form-actions { display: flex; gap: 10px; justify-content: flex-end; flex-wrap: wrap; }
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
.form-submit { background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep)); color: #FDF6E9; box-shadow: 0 2px 12px var(--cinnabar-glow), var(--shadow-card); }
.form-submit:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 4px 18px var(--cinnabar-glow), var(--shadow-glow-rouge); }
.form-cancel { background: var(--card); border-color: var(--gold-line); color: var(--ink-soft); }
.form-cancel:hover:not(:disabled) { transform: translateY(-2px); border-color: var(--rouge); color: var(--cinnabar); box-shadow: var(--shadow-glow-rouge); }
.form-submit:disabled, .form-cancel:disabled { opacity: .55; cursor: not-allowed; transform: none; box-shadow: none; }

/* ── 右栏：运行监视 ── */
.run-list { list-style: none; display: grid; gap: 12px; max-height: 640px; overflow-y: auto; padding-right: 4px; }
.run-item {
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-card);
  background: color-mix(in srgb, var(--card-solid) 55%, transparent);
  padding: 12px 14px;
  display: grid;
  gap: 7px;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.run-item:hover { border-color: var(--gold-line); box-shadow: var(--shadow-card); }
.run-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.run-subject { font-family: var(--font-kai); font-size: 14px; font-weight: 700; letter-spacing: 2px; color: var(--ink); display: flex; align-items: baseline; gap: 8px; }
.run-kind { font-style: normal; font-family: var(--font-sans); font-size: 10px; font-weight: 400; color: var(--gold); border: 1px solid var(--gold-line); border-radius: 999px; padding: 0 8px; }
.run-tags { display: flex; gap: 6px; }
.run-task { font-size: 12px; color: var(--ink); line-height: 1.6; overflow-wrap: anywhere; }
.run-goal { font-size: 11px; color: var(--ink-muted); overflow-wrap: anywhere; }
.run-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.run-time { margin-left: auto; font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); }
.run-note { font-size: 11px; color: var(--ink-soft); border-left: 2px solid var(--gold-line); padding-left: 8px; line-height: 1.6; }
.run-note.danger { color: var(--cinnabar); border-left-color: var(--cinnabar); }
.run-actions { display: flex; justify-content: flex-end; }

/* ── 团队管理 ── */
.team-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
.team-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  box-shadow: var(--shadow-card);
  padding: 14px;
  display: grid;
  gap: 8px;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.team-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lift); border-color: var(--gold-line); }
.team-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.team-name { font-family: var(--font-kai); font-size: 16px; letter-spacing: 2px; color: var(--ink); }
.team-mode-desc { font-size: 11px; color: var(--ink-muted); line-height: 1.6; }
.team-members { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.team-goal { font-size: 11px; color: var(--ink-soft); overflow-wrap: anywhere; }
.team-actions { display: flex; justify-content: flex-end; }

/* ── 权限矩阵 ── */
.matrix-card { margin-top: 20px; }
.matrix-intro { font-size: 12px; color: var(--ink-soft); margin-bottom: 12px; line-height: 1.7; }
.table-wrap { overflow-x: auto; border-radius: var(--radius-small); }
.matrix-table { width: 100%; min-width: 640px; border-collapse: collapse; }
.matrix-table th, .matrix-table td { border-bottom: 1px solid var(--line-soft); padding: 10px 12px; text-align: left; font-size: 12px; vertical-align: top; }
.matrix-table thead th { background: var(--bg-soft); color: var(--gold); font-family: var(--font-kai); letter-spacing: 2px; }
.matrix-table thead .th-danger { color: var(--cinnabar); }
.matrix-table tbody th { color: var(--ink); font-family: var(--font-kai); letter-spacing: 1px; white-space: nowrap; }
.matrix-table td { color: var(--ink-soft); line-height: 1.6; }
.matrix-table tbody tr { transition: background .18s ease; }
.matrix-table tbody tr:hover { background: color-mix(in srgb, var(--rouge) 6%, transparent); }
.cell-danger { color: var(--cinnabar) !important; background: color-mix(in srgb, var(--cinnabar) 6%, transparent); }
.matrix-warn { margin: 14px 0 0; }

/* ── 弹层 ── */
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--ink) 32%, transparent);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  padding: 20px;
}
.modal {
  width: min(520px, 100%);
  max-height: 86vh;
  overflow-y: auto;
  background: var(--card-solid);
  border: 1px solid var(--gold-line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-lift);
  padding: 22px;
  display: grid;
  gap: 14px;
}
.modal-title { font-family: var(--font-kai); font-size: 20px; letter-spacing: 3px; color: var(--ink); }
.member-pick { list-style: none; display: flex; flex-wrap: wrap; gap: 8px; }
.member-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 12px 5px 6px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--card);
  color: var(--ink-soft);
  font-size: 12px;
  font-family: var(--font-kai);
  letter-spacing: 1px;
  cursor: pointer;
  transition: border-color .18s ease, background .18s ease, color .18s ease, box-shadow .18s ease;
}
.member-chip:hover { border-color: var(--rouge); color: var(--cinnabar); }
.member-chip.on { border-color: var(--cinnabar); background: color-mix(in srgb, var(--cinnabar) 8%, transparent); color: var(--cinnabar); box-shadow: 0 0 0 2px var(--rouge-glow); }

/* ── 响应式 ── */
@media (max-width: 1320px) {
  .dispatch-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .field-go { grid-column: 1 / -1; justify-self: end; }
}
@media (max-width: 1180px) {
  .tri-grid { grid-template-columns: 1fr; }
  .run-list { max-height: none; }
}
@media (max-width: 760px) {
  .stat-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .dispatch-grid { grid-template-columns: 1fr; }
  .field-go { justify-self: stretch; }
  .form-row.two { grid-template-columns: 1fr; }
}
</style>

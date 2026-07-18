<script setup lang="ts">
/**
 * V4 项目空间 — 项目/任务空间卡片、tree/main/perch 三态分支泳道、
 * 自定义 git 提交模板与提交区、GitHub / Linear 账号绑定。
 * 后端契约：/platform/spaces/*；缺字段容错 + 离线兜底示例数据。
 */
import { computed, onMounted, ref, shallowRef } from 'vue'
import { apiGet, apiPost, apiPut } from '@/api/platform'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import InkDivider from '@/components/gf/InkDivider.vue'

/* ── 类型（全部字段可选，前端容错） ── */
interface SpaceProject {
  id?: string
  name?: string
  kind?: string
  desc?: string
  root_path?: string
  archived?: boolean
  source?: string
}
interface BranchState {
  name?: string
  ahead?: number
  behind?: number
  dirty?: boolean
  last_commit?: string
}
interface SpaceTree {
  source?: string
  branches?: BranchState[] | Record<string, BranchState>
  main?: BranchState
  tree?: BranchState
  perch?: BranchState
}
interface CommitTemplate {
  template?: string
  types?: string[]
  require_scope?: boolean
  source?: string
}
interface CommitResult {
  dry_run?: boolean
  commands?: string[]
  message?: string
  branch?: string
  simulated?: boolean
  source?: string
}
interface Integration {
  kind?: string
  bound?: boolean
  account?: string
  scopes?: string[]
  source?: string
}
type SpaceKind = 'project' | 'task'

/* ── 离线兜底示例数据 ── */
const SAMPLE_PROJECTS: SpaceProject[] = [
  { id: 'sample-os', name: '宛委·万枢桌面端', kind: 'project', desc: '麒麟 Linux 桌面协作平台主体工程', root_path: '/srv/wanwei/osagent', archived: false, source: 'sample' },
  { id: 'sample-console', name: '控制台前端', kind: 'project', desc: 'Vue3 + TS 国风双主题控制台', root_path: '/srv/wanwei/console-vue', archived: false, source: 'sample' },
  { id: 'sample-legacy', name: '旧版归档仓', kind: 'project', desc: '已封存的一代原型', root_path: '/srv/wanwei/legacy', archived: true, source: 'sample' },
  { id: 'sample-task-a', name: '分支泳道联调', kind: 'task', desc: 'tree/main/perch 三态合流验证', root_path: '/srv/wanwei/osagent', archived: false, source: 'sample' },
  { id: 'sample-task-b', name: '提交模板梳理', kind: 'task', desc: '自定义 git 提交规范落地', root_path: '/srv/wanwei/osagent', archived: false, source: 'sample' },
]
const SAMPLE_TREE: SpaceTree = {
  source: 'simulated',
  branches: {
    main: { name: 'main', ahead: 0, behind: 0, dirty: false, last_commit: 'chore: 主干受保护' },
    tree: { name: 'tree', ahead: 3, behind: 1, dirty: false, last_commit: 'feat(spaces): 集成树合入' },
    perch: { name: 'perch', ahead: 7, behind: 2, dirty: true, last_commit: 'wip: 栖枝实验进行中' },
  },
}
const SAMPLE_TEMPLATE: CommitTemplate = {
  template: '{type}({scope}): {summary}',
  types: ['feat', 'fix', 'docs', 'refactor', 'test', 'chore'],
  require_scope: true,
  source: 'sample',
}
const SAMPLE_INTEGRATIONS: Integration[] = [
  { kind: 'github', bound: false, account: '', scopes: [], source: 'sample' },
  { kind: 'linear', bound: false, account: '', scopes: [], source: 'sample' },
]

/* ── 空间列表状态 ── */
const activeTab = shallowRef<SpaceKind>('project')
const projects = shallowRef<SpaceProject[]>([])
const loading = shallowRef(true)
const offline = shallowRef(false)
const error = shallowRef('')

const filteredProjects = computed(() =>
  projects.value.filter((p) => (p.kind ?? 'project') === activeTab.value),
)

function asList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[]
  const items = (data as { items?: unknown } | null)?.items
  return Array.isArray(items) ? (items as T[]) : []
}

async function loadProjects() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiGet<unknown>('/spaces/projects')
    const list = asList<SpaceProject>(data)
    if (!list.length) throw new Error('empty')
    projects.value = list
    offline.value = list.some((p) => p.source === 'simulated' || p.source === 'sample')
  } catch {
    projects.value = SAMPLE_PROJECTS
    offline.value = true
  } finally {
    loading.value = false
  }
}

/* ── 新建项目弹层 ── */
const showCreate = shallowRef(false)
const creating = shallowRef(false)
const createError = shallowRef('')
const createForm = ref({ name: '', desc: '', root_path: '', kind: 'project' as SpaceKind })

function openCreate() {
  createForm.value = { name: '', desc: '', root_path: '', kind: activeTab.value }
  createError.value = ''
  showCreate.value = true
}

async function submitCreate() {
  if (creating.value) return
  creating.value = true
  createError.value = ''
  try {
    await apiPost('/spaces/projects', { ...createForm.value })
    showCreate.value = false
    await loadProjects()
  } catch (e) {
    createError.value = e instanceof Error ? e.message : String(e)
  } finally {
    creating.value = false
  }
}

/* ── 项目详情抽屉 ── */
const activeProject = shallowRef<SpaceProject | null>(null)
const drawerTree = shallowRef<SpaceTree | null>(null)
const treeOffline = shallowRef(false)
const treeLoading = shallowRef(false)

const laneDefs = [
  { key: 'main', label: 'main · 主干', desc: '主干受保护', tone: 'gold' as const },
  { key: 'tree', label: 'tree · 集成树', desc: '集成分支', tone: 'bamboo' as const },
  { key: 'perch', label: 'perch · 栖枝', desc: '实验分支', tone: 'rouge' as const },
]

const lanes = computed(() =>
  laneDefs.map((def) => {
    const t = drawerTree.value
    let state: BranchState = {}
    const raw = t?.branches
    if (raw && !Array.isArray(raw) && raw[def.key]) {
      state = raw[def.key]
    } else if (Array.isArray(raw)) {
      state = raw.find((b) => b?.name === def.key) ?? {}
    } else {
      state = (t as Record<string, BranchState> | null)?.[def.key] ?? {}
    }
    return { ...def, state }
  }),
)

async function openDrawer(project: SpaceProject) {
  activeProject.value = project
  drawerTree.value = null
  commitResult.value = null
  commitError.value = ''
  if (!project.id) return
  treeLoading.value = true
  try {
    const data = await apiGet<SpaceTree>(`/spaces/${project.id}/tree`)
    drawerTree.value = data && typeof data === 'object' ? data : SAMPLE_TREE
    treeOffline.value = data?.source === 'simulated'
  } catch {
    drawerTree.value = SAMPLE_TREE
    treeOffline.value = true
  } finally {
    treeLoading.value = false
  }
  await loadTemplate(project.id)
}

function closeDrawer() {
  activeProject.value = null
}

/* ── 提交模板 ── */
const templateForm = ref<CommitTemplate>({ template: '', types: [], require_scope: false })
const templateLoading = shallowRef(false)
const templateSaving = shallowRef(false)
const templateMsg = shallowRef('')
const typeInput = shallowRef('')

async function loadTemplate(id: string) {
  templateLoading.value = true
  templateMsg.value = ''
  try {
    const data = await apiGet<CommitTemplate>(`/spaces/${id}/commit-template`)
    templateForm.value = {
      template: data?.template ?? '',
      types: Array.isArray(data?.types) ? [...data.types] : [],
      require_scope: !!data?.require_scope,
    }
  } catch {
    templateForm.value = { ...SAMPLE_TEMPLATE, types: [...(SAMPLE_TEMPLATE.types ?? [])] }
    templateMsg.value = '离线示例模板（保存需后端在线）'
  } finally {
    templateLoading.value = false
  }
}

function addType() {
  const t = typeInput.value.trim()
  if (t && !(templateForm.value.types ?? []).includes(t)) {
    templateForm.value.types = [...(templateForm.value.types ?? []), t]
  }
  typeInput.value = ''
}

function removeType(t: string) {
  templateForm.value.types = (templateForm.value.types ?? []).filter((x) => x !== t)
}

async function saveTemplate() {
  if (templateSaving.value || !activeProject.value?.id) return
  templateSaving.value = true
  templateMsg.value = ''
  try {
    await apiPut(`/spaces/${activeProject.value.id}/commit-template`, {
      template: templateForm.value.template ?? '',
      types: templateForm.value.types ?? [],
      require_scope: !!templateForm.value.require_scope,
    })
    templateMsg.value = '模板已保存'
  } catch (e) {
    templateMsg.value = `保存失败：${e instanceof Error ? e.message : String(e)}`
  } finally {
    templateSaving.value = false
  }
}

/* ── 提交区 ── */
const commitForm = ref({ branch: 'tree', message: '', dry_run: true })
const committing = shallowRef(false)
const commitError = shallowRef('')
const commitResult = shallowRef<CommitResult | null>(null)

const commitHint = computed(() => {
  const types = templateForm.value.types ?? []
  if (!types.length) return ''
  const scope = templateForm.value.require_scope ? '(scope)' : '(scope，可省)'
  return `按模板校验：${types.join('/')}${scope}: 摘要`
})

const commitValid = computed(() => {
  const msg = commitForm.value.message.trim()
  if (!msg) return false
  const types = templateForm.value.types ?? []
  if (!types.length) return true
  const scopePart = templateForm.value.require_scope ? '\\([^()\\s]+\\)' : '(\\([^()\\s]+\\))?'
  const re = new RegExp(`^(${types.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})${scopePart}: .+`)
  return re.test(msg)
})

async function submitCommit() {
  if (committing.value || !activeProject.value?.id || !commitValid.value) return
  committing.value = true
  commitError.value = ''
  try {
    const data = await apiPost<CommitResult>(`/spaces/${activeProject.value.id}/commit`, {
      branch: commitForm.value.branch,
      message: commitForm.value.message.trim(),
      dry_run: commitForm.value.dry_run,
    })
    commitResult.value = data && typeof data === 'object' ? data : { commands: [], dry_run: commitForm.value.dry_run }
  } catch (e) {
    commitError.value = e instanceof Error ? e.message : String(e)
    commitResult.value = null
  } finally {
    committing.value = false
  }
}

/* ── 账号绑定 ── */
const integrations = shallowRef<Integration[]>([])
const intgOffline = shallowRef(false)
const intgBusy = shallowRef('')
const intgMsg = shallowRef<Record<string, string>>({})
const tokenInput = ref<Record<string, string>>({})

const integrationCards = computed(() => {
  const byKind = new Map(integrations.value.map((i) => [i.kind ?? '', i]))
  return (['github', 'linear'] as const).map((kind) => ({
    kind,
    label: kind === 'github' ? 'GitHub' : 'Linear',
    data: byKind.get(kind) ?? { kind, bound: false },
  }))
})

async function loadIntegrations() {
  try {
    const data = await apiGet<unknown>('/spaces/integrations')
    const list = asList<Integration>(data)
    if (!list.length) throw new Error('empty')
    integrations.value = list
    intgOffline.value = list.some((i) => i.source === 'simulated' || i.source === 'sample')
  } catch {
    integrations.value = SAMPLE_INTEGRATIONS
    intgOffline.value = true
  }
}

async function bindIntegration(kind: string) {
  const token = (tokenInput.value[kind] ?? '').trim()
  if (!token || intgBusy.value) {
    intgMsg.value = { ...intgMsg.value, [kind]: token ? '' : '请先填写 token' }
    if (!token) return
  }
  intgBusy.value = kind
  intgMsg.value = { ...intgMsg.value, [kind]: '' }
  try {
    await apiPost(`/spaces/integrations/${kind}/bind`, { token })
    tokenInput.value = { ...tokenInput.value, [kind]: '' }
    intgMsg.value = { ...intgMsg.value, [kind]: '绑定成功' }
    await loadIntegrations()
  } catch (e) {
    intgMsg.value = { ...intgMsg.value, [kind]: `绑定失败：${e instanceof Error ? e.message : String(e)}` }
  } finally {
    intgBusy.value = ''
  }
}

async function unbindIntegration(kind: string) {
  if (intgBusy.value) return
  intgBusy.value = kind
  intgMsg.value = { ...intgMsg.value, [kind]: '' }
  try {
    await apiPost(`/spaces/integrations/${kind}/unbind`, {})
    intgMsg.value = { ...intgMsg.value, [kind]: '已解绑' }
    await loadIntegrations()
  } catch (e) {
    intgMsg.value = { ...intgMsg.value, [kind]: `解绑失败：${e instanceof Error ? e.message : String(e)}` }
  } finally {
    intgBusy.value = ''
  }
}

async function testIntegration(kind: string) {
  if (intgBusy.value) return
  intgBusy.value = kind
  intgMsg.value = { ...intgMsg.value, [kind]: '' }
  try {
    const data = await apiPost<{ ok?: boolean; message?: string }>(`/spaces/integrations/${kind}/test`, {})
    intgMsg.value = { ...intgMsg.value, [kind]: data?.message ?? (data?.ok ? '连通正常' : '测试未通过') }
  } catch (e) {
    intgMsg.value = { ...intgMsg.value, [kind]: `测试失败：${e instanceof Error ? e.message : String(e)}` }
  } finally {
    intgBusy.value = ''
  }
}

onMounted(() => {
  loadProjects()
  loadIntegrations()
})
</script>

<template>
  <div class="spaces-view">
    <PageHero
      seal="枢"
      title="项目空间"
      en="WORK SPACES"
      sub="项目与任务双空间 · tree/main/perch 三态分支 · 自定义提交规范 · 外部账号绑定。"
    />

    <!-- 顶部 tab -->
    <div class="tab-bar" role="tablist">
      <button
        v-for="tab in ([['project', '项目空间'], ['task', '任务空间']] as const)"
        :key="tab[0]"
        class="tab-btn"
        :class="{ active: activeTab === tab[0] }"
        role="tab"
        :aria-selected="activeTab === tab[0]"
        type="button"
        @click="activeTab = tab[0]"
      >{{ tab[1] }}</button>
      <GfTag v-if="offline" tone="gold" class="offline-tag">离线示例数据</GfTag>
      <GfButton small class="tab-new" @click="openCreate">新建{{ activeTab === 'project' ? '项目' : '任务' }}</GfButton>
    </div>

    <!-- 卡片网格 -->
    <div v-if="loading" class="muted">研墨中…</div>
    <template v-else>
      <div v-if="filteredProjects.length" class="proj-grid">
        <GfCard v-for="p in filteredProjects" :key="p.id ?? p.name" :pad="true" class="proj-card">
          <div class="proj-head">
            <h3 class="proj-name">{{ p.name ?? '未命名' }}</h3>
            <GfTag :tone="(p.kind ?? 'project') === 'task' ? 'dai' : 'rouge'">
              {{ (p.kind ?? 'project') === 'task' ? '任务' : '项目' }}
            </GfTag>
          </div>
          <p class="proj-desc">{{ p.desc || '（暂无描述）' }}</p>
          <p class="proj-path"><code>{{ p.root_path || '—' }}</code></p>
          <div class="proj-foot">
            <GfTag :tone="p.archived ? 'ink' : 'bamboo'">{{ p.archived ? '已归档' : '进行中' }}</GfTag>
            <GfButton variant="ghost" small @click="openDrawer(p)">详情</GfButton>
          </div>
        </GfCard>
      </div>
      <GfEmpty v-else :text="`尚无${activeTab === 'project' ? '项目' : '任务'}空间，点击右上角新建。`" />
    </template>

    <InkDivider label="账号绑定" />

    <!-- 账号绑定区 -->
    <div class="intg-grid">
      <GfCard v-for="card in integrationCards" :key="card.kind" :title="card.label" :seal="card.kind === 'github' ? 'GH' : 'LN'">
        <div class="intg-body">
          <template v-if="card.data.bound">
            <div class="intg-row">
              <span class="intg-label">账号</span>
              <span class="intg-value">{{ card.data.account || '—' }}</span>
              <GfTag tone="bamboo">已绑定</GfTag>
            </div>
            <div class="intg-row">
              <span class="intg-label">scopes</span>
              <span class="intg-value scopes">
                <template v-if="(card.data.scopes ?? []).length">
                  <GfTag v-for="s in card.data.scopes" :key="s" tone="ink">{{ s }}</GfTag>
                </template>
                <template v-else>—</template>
              </span>
            </div>
            <div class="intg-actions">
              <GfButton variant="ghost" small :disabled="!!intgBusy" @click="testIntegration(card.kind)">
                {{ intgBusy === card.kind ? '测试中…' : '测试' }}
              </GfButton>
              <GfButton variant="danger" small :disabled="!!intgBusy" @click="unbindIntegration(card.kind)">解绑</GfButton>
            </div>
          </template>
          <template v-else>
            <div class="intg-row">
              <GfTag tone="ink">未绑定</GfTag>
              <GfTag v-if="intgOffline" tone="gold">示例</GfTag>
            </div>
            <label class="intg-token">
              <span>访问 token</span>
              <input
                v-model="tokenInput[card.kind]"
                type="password"
                autocomplete="new-password"
                :placeholder="`${card.label} personal access token`"
              />
            </label>
            <div class="intg-actions">
              <GfButton small :disabled="!!intgBusy" @click="bindIntegration(card.kind)">
                {{ intgBusy === card.kind ? '绑定中…' : '绑定' }}
              </GfButton>
              <GfButton variant="ghost" small :disabled="!!intgBusy || !(card.data.bound)" @click="testIntegration(card.kind)">测试</GfButton>
            </div>
          </template>
          <p v-if="intgMsg[card.kind]" class="intg-msg" aria-live="polite">{{ intgMsg[card.kind] }}</p>
        </div>
      </GfCard>
    </div>

    <!-- 新建项目弹层 -->
    <div v-if="showCreate" class="overlay" role="dialog" aria-modal="true" @click.self="showCreate = false">
      <GfCard :title="`新建${createForm.kind === 'project' ? '项目' : '任务'}空间`" seal="新" class="modal">
        <form class="create-form" @submit.prevent="submitCreate">
          <label>名称<input v-model.trim="createForm.name" required :disabled="creating" autocomplete="off" /></label>
          <label>描述<input v-model.trim="createForm.desc" :disabled="creating" autocomplete="off" /></label>
          <label>根路径 root_path<input v-model.trim="createForm.root_path" required :disabled="creating" autocomplete="off" placeholder="/srv/..." /></label>
          <label>类型
            <select v-model="createForm.kind" :disabled="creating">
              <option value="project">项目</option>
              <option value="task">任务</option>
            </select>
          </label>
          <p v-if="createError" class="form-error" role="alert">{{ createError }}</p>
          <div class="form-actions">
            <button class="form-submit" type="submit" :disabled="creating">{{ creating ? '创建中…' : '创建' }}</button>
            <button class="form-cancel" type="button" :disabled="creating" @click="showCreate = false">取消</button>
          </div>
        </form>
      </GfCard>
    </div>

    <!-- 项目详情抽屉 -->
    <div v-if="activeProject" class="overlay overlay--right" role="dialog" aria-modal="true" @click.self="closeDrawer">
      <aside class="drawer">
        <header class="drawer-head">
          <div>
            <h2 class="drawer-title">{{ activeProject.name ?? '项目详情' }}</h2>
            <p class="drawer-path"><code>{{ activeProject.root_path || '—' }}</code></p>
          </div>
          <GfButton variant="ghost" small @click="closeDrawer">收起</GfButton>
        </header>

        <!-- 三态分支泳道 -->
        <section class="drawer-sec">
          <div class="sec-title">
            <span>三态分支</span>
            <GfTag v-if="treeOffline" tone="gold">simulated · 模拟数据</GfTag>
          </div>
          <div v-if="treeLoading" class="muted">研墨中…</div>
          <div v-else class="lane-row">
            <div v-for="lane in lanes" :key="lane.key" class="lane" :data-key="lane.key">
              <div class="lane-head">
                <GfTag :tone="lane.tone">{{ lane.label }}</GfTag>
                <GfTag v-if="lane.key === 'main'" tone="ink">受保护</GfTag>
                <GfTag v-if="lane.state.dirty" tone="rouge">dirty</GfTag>
              </div>
              <p class="lane-desc">{{ lane.desc }}</p>
              <div class="lane-nums">
                <span class="lane-num">领先 <b>+{{ lane.state.ahead ?? 0 }}</b></span>
                <span class="lane-num">落后 <b>−{{ lane.state.behind ?? 0 }}</b></span>
              </div>
              <p class="lane-commit">{{ lane.state.last_commit || '—' }}</p>
            </div>
          </div>
        </section>

        <!-- 提交模板 -->
        <section class="drawer-sec">
          <div class="sec-title"><span>提交模板</span></div>
          <div v-if="templateLoading" class="muted">研墨中…</div>
          <template v-else>
            <label class="tpl-field">
              <span>模板字符串</span>
              <input v-model.trim="templateForm.template" :disabled="templateSaving" placeholder="{type}({scope}): {summary}" autocomplete="off" />
            </label>
            <div class="tpl-types">
              <GfTag v-for="t in templateForm.types ?? []" :key="t" tone="dai" class="tpl-type">
                {{ t }}
                <button class="type-x" type="button" title="移除" @click="removeType(t)">×</button>
              </GfTag>
              <span class="type-add">
                <input v-model.trim="typeInput" placeholder="新增 type" autocomplete="off" @keyup.enter.prevent="addType" />
                <GfButton variant="ghost" small @click="addType">添加</GfButton>
              </span>
            </div>
            <label class="tpl-scope">
              <input v-model="templateForm.require_scope" type="checkbox" :disabled="templateSaving" />
              要求 scope（require_scope）
            </label>
            <div class="tpl-actions">
              <GfButton small :disabled="templateSaving" @click="saveTemplate">{{ templateSaving ? '保存中…' : '保存模板' }}</GfButton>
              <span v-if="templateMsg" class="tpl-msg" aria-live="polite">{{ templateMsg }}</span>
            </div>
          </template>
        </section>

        <!-- 提交区 -->
        <section class="drawer-sec">
          <div class="sec-title"><span>自定义提交</span></div>
          <div class="commit-grid">
            <label class="commit-field">
              <span>分支</span>
              <select v-model="commitForm.branch" :disabled="committing">
                <option value="tree">tree · 集成树</option>
                <option value="main">main · 主干</option>
                <option value="perch">perch · 栖枝</option>
              </select>
            </label>
            <label class="commit-field commit-field--wide">
              <span>提交信息</span>
              <input v-model="commitForm.message" :disabled="committing" autocomplete="off" placeholder="feat(spaces): 示例提交" />
            </label>
          </div>
          <p v-if="commitHint" class="commit-hint" :class="{ bad: commitForm.message.trim() && !commitValid }">
            {{ commitForm.message.trim() && !commitValid ? '格式不符：' : '' }}{{ commitHint }}
          </p>
          <label class="tpl-scope">
            <input v-model="commitForm.dry_run" type="checkbox" :disabled="committing" />
            dry_run 预演（默认开启，只展示将执行的命令）
          </label>
          <div class="tpl-actions">
            <GfButton small :disabled="committing || !commitValid" @click="submitCommit">
              {{ committing ? '提交中…' : commitForm.dry_run ? '预演提交' : '执行提交' }}
            </GfButton>
            <span v-if="commitError" class="form-error">{{ commitError }}</span>
          </div>
          <div v-if="commitResult" class="commit-result">
            <div class="sec-title">
              <span>{{ commitResult.dry_run !== false ? '将执行的命令' : '执行结果' }}</span>
              <GfTag v-if="commitResult.simulated || commitResult.source === 'simulated'" tone="gold">simulated</GfTag>
            </div>
            <pre>{{ (commitResult.commands ?? []).length ? commitResult.commands!.join('\n') : '（后端未返回命令列表）' }}</pre>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.spaces-view { padding-bottom: 24px; }
.muted { color: var(--ink-soft); font-size: 13px; padding: 14px 0; font-family: var(--font-kai); letter-spacing: 2px; }

/* ── 顶部 tab ── */
.tab-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; flex-wrap: wrap; }
.tab-btn {
  padding: 7px 22px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--card);
  color: var(--ink-soft);
  font-family: var(--font-kai);
  font-size: 14px;
  letter-spacing: 3px;
  cursor: pointer;
  transition: all .18s ease;
}
.tab-btn:hover { border-color: var(--gold-line); transform: translateY(-1px); }
.tab-btn.active {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  border-color: transparent;
  box-shadow: 0 2px 12px var(--cinnabar-glow);
}
.offline-tag { margin-left: 4px; }
.tab-new { margin-left: auto; }

/* ── 卡片网格 ── */
.proj-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.proj-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.proj-name { font-family: var(--font-kai); font-size: 18px; letter-spacing: 2px; color: var(--ink); font-weight: 700; overflow-wrap: anywhere; }
.proj-desc { margin-top: 8px; font-size: 12px; color: var(--ink-soft); line-height: 1.7; min-height: 20px; }
.proj-path { margin-top: 8px; }
code { font-family: var(--font-mono); font-size: 11px; color: var(--dai); overflow-wrap: anywhere; }
.proj-foot { margin-top: 12px; display: flex; align-items: center; justify-content: space-between; gap: 8px; }

/* ── 账号绑定 ── */
.intg-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.intg-body { display: grid; gap: 12px; }
.intg-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.intg-label { font-size: 11px; letter-spacing: 2px; color: var(--ink-muted); }
.intg-value { font-size: 13px; color: var(--ink); overflow-wrap: anywhere; }
.intg-value.scopes { display: inline-flex; gap: 6px; flex-wrap: wrap; }
.intg-token { display: grid; gap: 6px; font-size: 11px; letter-spacing: 1px; color: var(--ink-muted); }
.intg-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.intg-msg { font-size: 12px; color: var(--ink-soft); line-height: 1.6; }

/* ── 弹层 / 抽屉 ── */
.overlay {
  position: fixed;
  inset: 0;
  background: color-mix(in srgb, var(--ink) 30%, transparent);
  backdrop-filter: blur(3px);
  display: grid;
  place-items: center;
  z-index: 60;
  padding: 24px;
}
.overlay--right { place-items: stretch end; padding: 0; }
.modal { width: min(520px, 100%); }
.create-form { display: grid; gap: 12px; }
label { display: grid; gap: 6px; color: var(--ink-muted); font-size: 11px; letter-spacing: 1px; }
input, select {
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
input:focus, select:focus { outline: none; border-color: var(--cinnabar); box-shadow: 0 0 0 3px var(--rouge-glow); }
input:disabled, select:disabled { opacity: .55; }
.form-error { font-size: 12px; color: var(--cinnabar-deep); }
.form-actions { display: flex; gap: 8px; justify-content: flex-end; }
.form-submit, .form-cancel {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 8px 20px; border-radius: 999px; border: 1px solid transparent;
  font-size: 13px; letter-spacing: 2px; font-family: var(--font-kai); cursor: pointer;
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.form-submit { background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep)); color: #FDF6E9; box-shadow: 0 2px 12px var(--cinnabar-glow), var(--shadow-card); }
.form-submit:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 4px 18px var(--cinnabar-glow); }
.form-cancel { background: var(--card); border-color: var(--gold-line); color: var(--ink-soft); }
.form-cancel:hover:not(:disabled) { transform: translateY(-2px); border-color: var(--rouge); color: var(--cinnabar); }
.form-submit:disabled, .form-cancel:disabled { opacity: .55; cursor: not-allowed; transform: none; box-shadow: none; }

.drawer {
  width: min(560px, 100%);
  height: 100%;
  overflow-y: auto;
  background: var(--card-solid);
  border-left: 1px solid var(--gold-line);
  box-shadow: var(--shadow-lift);
  padding: 22px 24px 40px;
}
.drawer-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 18px; }
.drawer-title { font-family: var(--font-kai); font-size: 24px; letter-spacing: 3px; color: var(--ink); font-weight: 700; }
.drawer-path { margin-top: 6px; }
.drawer-sec { margin-bottom: 22px; padding-top: 16px; border-top: 1px solid var(--line-soft); }
.sec-title { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-family: var(--font-kai); font-size: 15px; letter-spacing: 3px; color: var(--ink); font-weight: 700; }

/* ── 泳道 ── */
.lane-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.lane {
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  box-shadow: var(--shadow-card);
  padding: 12px;
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
}
.lane:hover { transform: translateY(-3px); box-shadow: var(--shadow-lift); border-color: var(--gold-line); }
.lane-head { display: flex; gap: 6px; flex-wrap: wrap; }
.lane-desc { margin-top: 8px; font-size: 11px; color: var(--ink-muted); letter-spacing: 1px; }
.lane-nums { margin-top: 10px; display: flex; flex-direction: column; gap: 4px; }
.lane-num { font-size: 11px; color: var(--ink-soft); }
.lane-num b { font-family: var(--font-mono); color: var(--ink); }
.lane-commit { margin-top: 10px; font-size: 11px; color: var(--dai); font-family: var(--font-mono); overflow-wrap: anywhere; }

/* ── 模板 / 提交 ── */
.tpl-field { margin-bottom: 12px; }
.tpl-types { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.tpl-type { display: inline-flex; align-items: center; gap: 4px; }
.type-x {
  border: none; background: none; color: inherit; cursor: pointer;
  font-size: 13px; line-height: 1; padding: 0 2px;
}
.type-add { display: inline-flex; align-items: center; gap: 6px; }
.type-add input { width: 110px; padding: 4px 10px; font-size: 11px; }
.tpl-scope { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ink-soft); margin-bottom: 12px; }
.tpl-scope input { width: 15px; height: 15px; accent-color: var(--bamboo); }
.tpl-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.tpl-msg { font-size: 12px; color: var(--ink-soft); }

.commit-grid { display: grid; grid-template-columns: 160px 1fr; gap: 12px; margin-bottom: 10px; }
.commit-field--wide { min-width: 0; }
.commit-hint { font-size: 11px; color: var(--ink-muted); letter-spacing: 1px; margin-bottom: 10px; }
.commit-hint.bad { color: var(--cinnabar-deep); }
.commit-result pre {
  margin-top: 4px;
  padding: 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--bg-soft);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--ink-soft);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.7;
  min-height: 48px;
}

@media (max-width: 980px) {
  .proj-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 720px) {
  .proj-grid, .intg-grid { grid-template-columns: 1fr; }
  .lane-row { grid-template-columns: 1fr; }
  .commit-grid { grid-template-columns: 1fr; }
  .tab-new { margin-left: 0; }
}
</style>

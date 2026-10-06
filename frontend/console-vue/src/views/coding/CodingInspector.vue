<!--
 Copyright (c) 2026 QianChang-official

 宛委·枢忆 is licensed under Mulan PSL v2.
 You can use this software according to the terms of the Mulan PSL v2.
 You may obtain a copy of Mulan PSL v2 at:
 http://license.coscl.org.cn/MulanPSL2

 THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
 EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
 MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
 See the Mulan PSL v2 for more details.
-->

<script setup lang="ts">
/** CodingInspector — 右栏：审批 / 工具台 / 待办 / 可审计记忆 / 子智能体 / 策略 */
import { computed, reactive, ref } from 'vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import type { CodingOverview, MemoryItem, PolicyMatrix, SessionDetail, SkillSpec, SubagentRole, ToolSpec } from '@/api/coding'

const props = defineProps<{
  detail: SessionDetail | null
  tools: ToolSpec[]
  skills: SkillSpec[]
  roles: SubagentRole[]
  policy: PolicyMatrix | null
  memory: { items: MemoryItem[]; summary: Record<string, number>; available: boolean }
  overview: CodingOverview | null
  busy: Record<string, boolean>
  toolResult: { status: string; summary: string; output: unknown } | null
  /** 最近一次遗忘操作的删除取证，由 useCoding 提供 */
  forgetEvidence?: Record<string, unknown> | null
}>()

const emit = defineEmits<{
  (e: 'approve', approvalId: string, approved: boolean): void
  (e: 'invoke-tool', toolId: string, params: Record<string, unknown>): void
  (e: 'add-todos', items: string[]): void
  (e: 'update-todo', id: string, state: string): void
  (e: 'run-subagent', role: string, task: string): void
  (e: 'write-memory', kind: string, title: string, text: string): void
  (e: 'forget-memory', capsuleId: string): void
}>()

type TabId = 'approvals' | 'tools' | 'todos' | 'memory' | 'subagents' | 'policy'
const tab = ref<TabId>('approvals')

const pendingApprovals = computed(() => (props.detail?.approvals || []).filter((a) => a.status === 'pending'))
const resolvedApprovals = computed(() => (props.detail?.approvals || []).filter((a) => a.status !== 'pending'))
const todos = computed(() => props.detail?.todos || [])

const TABS = computed(() => [
  { id: 'approvals' as TabId, label: '审批', badge: pendingApprovals.value.length },
  { id: 'tools' as TabId, label: '工具台', badge: 0 },
  { id: 'todos' as TabId, label: '待办', badge: todos.value.filter((t) => t.state !== 'done').length },
  { id: 'memory' as TabId, label: '记忆', badge: props.memory.items.length },
  { id: 'subagents' as TabId, label: '子智能体', badge: props.detail?.subagents?.length || 0 },
  { id: 'policy' as TabId, label: '策略', badge: 0 },
])

/* ── 工具台 ── */
const selectedTool = ref<string>('')
const toolParams = reactive<Record<string, string>>({})

const currentTool = computed(() => props.tools.find((t) => t.id === selectedTool.value) || null)

function pickTool(id: string) {
  selectedTool.value = id
  for (const k of Object.keys(toolParams)) delete toolParams[k]
  const spec = props.tools.find((t) => t.id === id)
  if (spec) for (const key of Object.keys(spec.parameters)) toolParams[key] = ''
}

function coerce(typeHint: string, raw: string): unknown {
  if (typeHint.startsWith('bool')) return raw === 'true' || raw === 'on'
  if (typeHint.startsWith('int')) return Number(raw)
  return raw
}

function submitTool() {
  const spec = currentTool.value
  if (!spec) return
  const params: Record<string, unknown> = {}
  for (const [key, hint] of Object.entries(spec.parameters)) {
    const raw = (toolParams[key] ?? '').trim()
    if (raw === '') continue // 空值不提交，交由后端按可选参数处理
    params[key] = coerce(hint, raw)
  }
  emit('invoke-tool', spec.id, params)
}

/* ── 待办 ── */
const todoInput = ref('')
function submitTodos() {
  const items = todoInput.value.split('\n').map((s) => s.trim()).filter(Boolean)
  if (!items.length) return
  emit('add-todos', items)
  todoInput.value = ''
}

/* ── 记忆 ── */
const memKind = ref('decision')
const memTitle = ref('')
const memText = ref('')
function submitMemory() {
  if (!memText.value.trim()) return
  emit('write-memory', memKind.value, memTitle.value, memText.value)
  memTitle.value = ''
  memText.value = ''
}
function doForget(id: string) {
  emit('forget-memory', id)
}

/* ── 子智能体 ── */
const subRole = ref('explorer')
const subTask = ref('')
function submitSubagent() {
  if (!subTask.value.trim()) return
  emit('run-subagent', subRole.value, subTask.value)
  subTask.value = ''
}

const KIND_LABEL: Record<string, string> = {
  decision: '决策', pitfall: '踩坑', convention: '约定', context: '背景',
}
const TODO_STATES = ['pending', 'doing', 'done', 'blocked']
const TODO_LABEL: Record<string, string> = { pending: '未开始', doing: '进行中', done: '已完成', blocked: '受阻' }
const DECISION_TONE: Record<string, string> = { allow: 'bamboo', ask: 'gold', deny: 'rouge' }
const DECISION_LABEL: Record<string, string> = { allow: '放行', ask: '待审', deny: '拒绝' }

function cellTone(decision: string | undefined): 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink' {
  const tone = DECISION_TONE[decision || ''] || 'ink'
  return tone as 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
}
function cellLabel(decision: string | undefined): string {
  return DECISION_LABEL[decision || ''] || '—'
}
</script>

<template>
  <aside class="ins">
    <nav class="ins-tabs">
      <button
        v-for="t in TABS"
        :key="t.id"
        type="button"
        class="ins-tab"
        :class="{ 'ins-tab--on': tab === t.id }"
        @click="tab = t.id"
      >
        {{ t.label }}
        <span v-if="t.badge" class="ins-badge">{{ t.badge }}</span>
      </button>
    </nav>

    <div class="ins-body">
      <!-- 审批 -->
      <template v-if="tab === 'approvals'">
        <GfEmpty v-if="!pendingApprovals.length && !resolvedApprovals.length" text="暂无审批请求" />
        <article v-for="a in pendingApprovals" :key="a.id" class="ins-card ins-card--warn">
          <header class="ins-card-hd">
            <GfTag tone="gold">{{ a.risk === 'high' ? '高风险' : '中风险' }}</GfTag>
            <code class="ins-card-tool">{{ a.tool_id }}</code>
          </header>
          <p class="ins-card-text">{{ a.summary }}</p>
          <pre class="ins-card-pre">{{ JSON.stringify(a.params, null, 2) }}</pre>
          <div class="ins-card-ft">
            <button class="ins-btn ins-btn--ok" type="button" :disabled="busy.approval" @click="emit('approve', a.id, true)">放行</button>
            <button class="ins-btn ins-btn--no" type="button" :disabled="busy.approval" @click="emit('approve', a.id, false)">拒绝</button>
          </div>
        </article>
        <article v-for="a in resolvedApprovals" :key="a.id" class="ins-card">
          <header class="ins-card-hd">
            <GfTag :tone="a.status === 'approved' ? 'bamboo' : 'ink'">
              {{ a.status === 'approved' ? '已放行' : '已拒绝' }}
            </GfTag>
            <code class="ins-card-tool">{{ a.tool_id }}</code>
          </header>
          <p class="ins-card-text">{{ a.summary }}</p>
        </article>
      </template>

      <!-- 工具台 -->
      <template v-else-if="tab === 'tools'">
        <div class="ins-grid">
          <button
            v-for="t in tools"
            :key="t.id"
            type="button"
            class="ins-tool"
            :class="{ 'ins-tool--on': selectedTool === t.id }"
            @click="pickTool(t.id)"
          >
            <span class="ins-tool-name">{{ t.name_cn }}</span>
            <GfTag :tone="t.risk === 'low' ? 'bamboo' : (t.risk === 'high' ? 'rouge' : 'gold')">
              {{ t.risk_label }}
            </GfTag>
          </button>
        </div>
        <div v-if="currentTool" class="ins-form">
          <p class="ins-tool-desc">{{ currentTool.description }}</p>
          <label v-for="(hint, key) in currentTool.parameters" :key="key" class="ins-field">
            <span class="ins-field-label">{{ key }} <em>{{ hint }}</em></span>
            <input v-model="toolParams[key]" class="ins-input" :placeholder="String(hint)" />
          </label>
          <p v-if="!Object.keys(currentTool.parameters).length" class="ins-muted">该工具无需参数</p>
          <button class="ins-btn ins-btn--primary" type="button" :disabled="busy.tool" @click="submitTool">
            {{ busy.tool ? '调用中…' : '调用工具' }}
          </button>
          <div v-if="toolResult" class="ins-result" :data-status="toolResult.status">
            <strong>{{ toolResult.summary }}</strong>
            <pre>{{ JSON.stringify(toolResult.output, null, 2) }}</pre>
          </div>
        </div>
      </template>

      <!-- 待办 -->
      <template v-else-if="tab === 'todos'">
        <div class="ins-form">
          <textarea
            v-model="todoInput"
            class="ins-input ins-textarea"
            rows="3"
            placeholder="每行一条待办，例如：&#10;补 subtract 的单元测试&#10;更新 README 用法"
          />
          <button class="ins-btn ins-btn--primary" type="button" @click="submitTodos">添加待办</button>
        </div>
        <GfEmpty v-if="!todos.length" text="暂无待办" />
        <ul v-else class="ins-todos">
          <li v-for="t in todos" :key="t.id" class="ins-todo" :data-state="t.state">
            <span class="ins-todo-text" :class="{ 'is-done': t.state === 'done' }">{{ t.text }}</span>
            <select
              class="ins-select"
              :value="t.state"
              @change="emit('update-todo', t.id, ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="s in TODO_STATES" :key="s" :value="s">{{ TODO_LABEL[s] }}</option>
            </select>
          </li>
        </ul>
      </template>

      <!-- 记忆 -->
      <template v-else-if="tab === 'memory'">
        <div class="ins-form">
          <div class="ins-row">
            <select v-model="memKind" class="ins-select">
              <option v-for="(label, k) in KIND_LABEL" :key="k" :value="k">{{ label }}</option>
            </select>
            <input v-model="memTitle" class="ins-input" placeholder="标题（可选）" maxlength="80" />
          </div>
          <textarea v-model="memText" class="ins-input ins-textarea" rows="3" placeholder="要沉淀的决策 / 踩坑 / 约定" />
          <button class="ins-btn ins-btn--primary" type="button" :disabled="busy.memory" @click="submitMemory">
            {{ busy.memory ? '写入中…' : '写入可审计记忆' }}
          </button>
        </div>

        <p v-if="!memory.available" class="ins-warn">记忆库当前不可用，写入会如实失败（不会假装成功）。</p>
        <GfEmpty v-if="!memory.items.length" text="本会话尚无记忆" />
        <ul v-else class="ins-mems">
          <li v-for="m in memory.items" :key="m.capsule_id" class="ins-mem">
            <header class="ins-mem-hd">
              <GfTag :tone="m.kind === 'decision' ? 'dai' : (m.kind === 'pitfall' ? 'rouge' : 'gold')">
                {{ m.kind_label }}
              </GfTag>
              <span class="ins-mem-title">{{ m.title }}</span>
              <GfTag tone="ink">{{ m.lifecycle }}</GfTag>
            </header>
            <p class="ins-mem-text">{{ m.text }}</p>
            <footer class="ins-mem-ft">
              <code class="ins-mem-id">{{ m.capsule_id }}</code>
              <button class="ins-btn ins-btn--no ins-btn--sm" type="button" @click="doForget(m.capsule_id)">
                遗忘并取证
              </button>
            </footer>
          </li>
        </ul>
        <div v-if="forgetEvidence" class="ins-result" data-status="ok">
          <strong>删除取证结果</strong>
          <pre>{{ JSON.stringify(forgetEvidence, null, 2) }}</pre>
        </div>
      </template>

      <!-- 子智能体 -->
      <template v-else-if="tab === 'subagents'">
        <div class="ins-grid">
          <button
            v-for="r in roles"
            :key="r.role"
            type="button"
            class="ins-tool"
            :class="{ 'ins-tool--on': subRole === r.role }"
            @click="subRole = r.role"
          >
            <span class="ins-tool-name">{{ r.label }}</span>
            <GfTag :tone="r.readonly ? 'bamboo' : 'gold'">{{ r.readonly ? '只读' : '可写' }}</GfTag>
          </button>
        </div>
        <div class="ins-form">
          <p class="ins-muted">{{ roles.find((r) => r.role === subRole)?.mission }}</p>
          <textarea v-model="subTask" class="ins-input ins-textarea" rows="3" placeholder="委派给子智能体的具体任务" />
          <button class="ins-btn ins-btn--primary" type="button" :disabled="busy.subagent" @click="submitSubagent">
            {{ busy.subagent ? '委派中…' : '委派并执行' }}
          </button>
        </div>
        <article v-for="s in (detail?.subagents || []).slice().reverse()" :key="s.id" class="ins-card">
          <header class="ins-card-hd">
            <GfTag :tone="s.status === 'done' ? 'bamboo' : (s.status === 'failed' ? 'rouge' : 'gold')">
              {{ s.role_label }}
            </GfTag>
            <span class="ins-card-text">{{ s.task }}</span>
          </header>
          <p class="ins-card-text">{{ s.findings?.summary || s.error || '（无产出）' }}</p>
        </article>
      </template>

      <!-- 策略 -->
      <template v-else>
        <section v-if="overview" class="ins-panel">
          <h4 class="ins-panel-title">框架能力</h4>
          <ul class="ins-caps">
            <li v-for="c in overview.capabilities" :key="c.id">
              <span class="ins-cap-dot" />{{ c.label }}
              <GfTag tone="bamboo">{{ c.status }}</GfTag>
            </li>
          </ul>
          <p class="ins-muted">
            工具 {{ overview.counts.tools }} · 技能 {{ overview.counts.skills }} · 子智能体角色 {{ overview.counts.subagent_roles }}
            · 模型网关 {{ overview.llm.available ? '可用' : '未配置（回退启发式）' }}
          </p>
        </section>
        <section v-if="policy" class="ins-panel">
          <h4 class="ins-panel-title">权限 × 风险裁决矩阵</h4>
          <table class="ins-table">
            <thead>
              <tr><th>档位</th><th v-for="r in policy.risks" :key="r.id">{{ r.label }}风险</th></tr>
            </thead>
            <tbody>
              <tr v-for="m in policy.modes" :key="m.id">
                <td>{{ m.label }}</td>
                <td v-for="r in policy.risks" :key="r.id">
                  <GfTag :tone="cellTone(policy.matrix[m.id]?.[r.id])">
                    {{ cellLabel(policy.matrix[m.id]?.[r.id]) }}
                  </GfTag>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
        <section class="ins-panel">
          <h4 class="ins-panel-title">已加载技能</h4>
          <ul class="ins-caps">
            <li v-for="s in skills" :key="s.id">
              <span class="ins-cap-dot" />{{ s.name }}
              <GfTag :tone="s.source === 'workspace' ? 'gold' : 'ink'">{{ s.source === 'workspace' ? '工作区' : '内置' }}</GfTag>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.ins {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-left: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg-soft) 42%, transparent);
}
.ins-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 10px 10px 8px;
  border-bottom: 1px solid var(--line-soft);
}
.ins-tab {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--ink-muted);
  font-size: 12px;
  letter-spacing: .5px;
  transition: all .16s ease;
}
.ins-tab:hover { color: var(--ink); background: var(--line-soft); }
.ins-tab--on {
  color: var(--cinnabar-deep);
  border-color: var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 10%, transparent);
}
.ins-badge {
  min-width: 15px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--cinnabar);
  color: #FDF6E9;
  font-size: 10px;
  line-height: 15px;
  text-align: center;
}

.ins-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 12px; display: grid; gap: 10px; align-content: start; }

.ins-card {
  display: grid;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
}
.ins-card--warn { border-color: var(--gold-line); background: color-mix(in srgb, var(--gold) 7%, var(--card)); }
.ins-card-hd { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ins-card-tool { font-family: var(--font-mono); font-size: 11px; color: var(--ink-soft); }
.ins-card-text { font-size: 12px; line-height: 1.65; color: var(--ink-soft); }
.ins-card-pre {
  padding: 8px;
  max-height: 160px;
  overflow: auto;
  border-radius: var(--radius-small);
  background: var(--bg-soft);
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.55;
  color: var(--ink-muted);
  white-space: pre-wrap;
  word-break: break-word;
}
.ins-card-ft { display: flex; gap: 8px; }

.ins-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.ins-tool {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card-solid);
  transition: all .16s ease;
}
.ins-tool:hover { border-color: var(--gold-line); }
.ins-tool--on { border-color: var(--rouge); box-shadow: 0 0 0 2px var(--rouge-glow); }
.ins-tool-name { font-size: 12.5px; color: var(--ink); }

.ins-form { display: grid; gap: 8px; padding: 11px 12px; border: 1px solid var(--line-soft); border-radius: var(--radius-small); background: var(--card); }
.ins-tool-desc { font-size: 11.5px; line-height: 1.65; color: var(--ink-muted); }
.ins-field { display: grid; gap: 4px; }
.ins-field-label { font-size: 11px; color: var(--ink-soft); }
.ins-field-label em { font-style: normal; color: var(--ink-muted); font-family: var(--font-mono); font-size: 10px; }
.ins-input, .ins-select {
  width: 100%;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card-solid);
  color: var(--ink);
  font-size: 12.5px;
}
.ins-input:focus, .ins-select:focus { outline: none; border-color: var(--rouge); box-shadow: 0 0 0 3px var(--rouge-glow); }
.ins-textarea { resize: vertical; line-height: 1.6; }
.ins-row { display: grid; grid-template-columns: 100px 1fr; gap: 8px; }
.ins-select { cursor: pointer; }

.ins-btn {
  padding: 7px 14px;
  border-radius: var(--radius-small);
  border: 1px solid var(--line);
  background: var(--card-solid);
  color: var(--ink-soft);
  font-size: 12px;
  letter-spacing: .5px;
  transition: all .16s ease;
}
.ins-btn:hover:not(:disabled) { border-color: var(--gold-line); color: var(--ink); }
.ins-btn:disabled { opacity: .5; cursor: not-allowed; }
.ins-btn--primary { border-color: transparent; background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep)); color: #FDF6E9; }
.ins-btn--ok { border-color: color-mix(in srgb, var(--bamboo) 50%, transparent); color: color-mix(in srgb, var(--bamboo) 70%, var(--ink)); }
.ins-btn--no { border-color: color-mix(in srgb, var(--cinnabar) 40%, transparent); color: var(--cinnabar-deep); }
.ins-btn--sm { padding: 4px 10px; font-size: 11px; }

.ins-result {
  display: grid;
  gap: 6px;
  padding: 9px 10px;
  border-radius: var(--radius-small);
  border: 1px solid var(--line-soft);
  background: var(--bg-soft);
  font-size: 11.5px;
}
.ins-result[data-status='ok'] { border-color: color-mix(in srgb, var(--bamboo) 40%, transparent); }
.ins-result[data-status='denied'], .ins-result[data-status='error'] { border-color: var(--line-cinnabar); }
.ins-result strong { font-size: 11.5px; color: var(--ink); }
.ins-result pre {
  max-height: 220px;
  overflow: auto;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.55;
  color: var(--ink-muted);
  white-space: pre-wrap;
  word-break: break-word;
}

.ins-todos { display: grid; gap: 5px; }
.ins-todo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--card);
}
.ins-todo[data-state='done'] { opacity: .68; }
.ins-todo-text { flex: 1 1 auto; font-size: 12.5px; color: var(--ink); }
.ins-todo-text.is-done { text-decoration: line-through; color: var(--ink-muted); }

.ins-mems { display: grid; gap: 8px; }
.ins-mem { display: grid; gap: 6px; padding: 10px 11px; border: 1px solid var(--line); border-radius: var(--radius-small); background: var(--card); }
.ins-mem-hd { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.ins-mem-title { flex: 1 1 auto; font-size: 12.5px; font-weight: 600; color: var(--ink); }
.ins-mem-text { font-size: 11.5px; line-height: 1.65; color: var(--ink-soft); word-break: break-word; }
.ins-mem-ft { display: flex; align-items: center; gap: 8px; }
.ins-mem-id { flex: 1 1 auto; font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); overflow: hidden; text-overflow: ellipsis; }

.ins-panel { display: grid; gap: 8px; padding: 11px 12px; border: 1px solid var(--line-soft); border-radius: var(--radius-small); background: var(--card); }
.ins-panel-title { font-family: var(--font-kai); font-size: 13px; letter-spacing: 2px; color: var(--ink-soft); }
.ins-caps { display: grid; gap: 5px; }
.ins-caps li { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--ink-soft); }
.ins-cap-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--gold); flex: 0 0 auto; }
.ins-muted { font-size: 11px; line-height: 1.7; color: var(--ink-muted); }
.ins-warn { font-size: 11.5px; color: var(--cinnabar); line-height: 1.6; }
.ins-table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
.ins-table th, .ins-table td { padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--line-soft); }
.ins-table th { color: var(--ink-muted); font-weight: 500; }
</style>

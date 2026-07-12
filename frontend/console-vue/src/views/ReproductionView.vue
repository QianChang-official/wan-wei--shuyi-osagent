<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { api } from '@/api/client'

const loading = shallowRef(true)
const error = shallowRef('')
const systems = shallowRef<any>({ items: [], summary: {} })
const workbench = shallowRef<any>({ cases: [], metrics: {}, failure_diagnosis: {} })
const graph = shallowRef<any>({ nodes: [], edges: [] })
const hippoResult = shallowRef<any>(null)
const retention = shallowRef<any>({ items: [] })
const retentionResult = shallowRef<any>(null)
const evaluator = shallowRef<any>({ failure_taxonomy: [] })
const reflexionResult = shallowRef<any>(null)
const tools = shallowRef<any>({ items: [] })
const toolResult = shallowRef<any>(null)
const memcube = shallowRef<any>({ fields: {} })
const tiers = shallowRef<any>({})
const locomo = shallowRef<any>({ sessions: [] })
const stream = shallowRef<any>({})

const hippoQuery = shallowRef('引用 规范')
const retentionAction = shallowRef('recall')
const toolName = shallowRef('memory.retrieve')
const reflexionNotes = shallowRef('evidence cards present; goal achieved')

const partialCount = computed(() => systems.value.items?.filter((item: any) => item.status === 'partial').length ?? 0)
const plannedCount = computed(() => systems.value.items?.filter((item: any) => item.status === 'planned').length ?? 0)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [systemRes, workbenchRes, graphRes, retentionRes, evaluatorRes, toolsRes, memcubeRes, tierRes, locomoRes, streamRes] = await Promise.all([
      api.reproductionSystems(),
      api.reproductionWorkbench(),
      api.reproductionHippoGraph(),
      api.reproductionRetentionState(),
      api.reproductionReflexionEvaluator(),
      api.reproductionMemoryTools(),
      api.reproductionMemcubeSchema(),
      api.reproductionMemoryTiers(),
      api.reproductionLocomoTemplate(),
      api.reproductionGenerativeTemplate(),
    ])
    systems.value = systemRes
    workbench.value = workbenchRes
    graph.value = graphRes
    retention.value = retentionRes
    evaluator.value = evaluatorRes
    tools.value = toolsRes
    memcube.value = memcubeRes
    tiers.value = tierRes
    locomo.value = locomoRes
    stream.value = streamRes
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function runHippo() {
  hippoResult.value = await api.reproductionHippoRecall({ query: hippoQuery.value, top_k: 5, hops: 2 })
}

async function runRetention() {
  retentionResult.value = await api.reproductionRetentionSimulate({ action: retentionAction.value, days: 7, importance: 0.7, memory_strength: 0.8 })
}

async function runReflexion() {
  reflexionResult.value = await api.reproductionReflexionEvaluate({ task_id: 'ui_dry_run', goal_achieved: true, used_memories: ['cap_demo'], evidence_cards: [{ id: 'ev_demo' }], notes: reflexionNotes.value })
}

async function runTool() {
  toolResult.value = await api.reproductionMemoryToolDryRun({ tool_name: toolName.value, payload: { query: 'demo' } })
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head"><h1>论文复现</h1><p>v0.9 轻量级研究系统复现层</p></div>
    <section class="hero-board">
      <div><b>{{ systems.summary?.systems || 9 }}</b><span>论文系统</span></div>
      <div><b>{{ systems.summary?.api_count || 14 }}</b><span>API</span></div>
      <div><b>{{ partialCount }}</b><span>部分实现</span></div>
      <div><b>{{ plannedCount }}</b><span>计划中</span></div>
    </section>
    <div class="boundary">不是完整官方复现；这是项目内 lightweight reproduction layer，POST 接口均为 dry-run 或只读/隔离逻辑。</div>
    <div v-if="loading" class="muted">加载论文复现层...</div>
    <div v-else-if="error" class="muted">{{ error }}</div>
    <template v-else>
      <section class="system-grid">
        <article v-for="item in systems.items" :key="item.id" class="system-card" :class="item.status">
          <h2>{{ item.name }}</h2><code>{{ item.source }} · {{ item.status }}</code><p>API {{ item.api_count }}</p>
        </article>
      </section>

      <section class="section-block two-col">
        <article class="panel">
          <div class="section-title">MemoryArena 工作台</div>
          <div class="metrics"><span>用例 {{ workbench.cases.length }}</span><span>断言 {{ workbench.metrics.total_assertions }}</span><span>{{ workbench.failure_diagnosis.status }}</span></div>
          <div v-for="caseItem in workbench.cases" :key="caseItem.case_id" class="case-card">
            <b>{{ caseItem.title || caseItem.case_id }}</b><code>{{ caseItem.case_id }} · sessions {{ caseItem.session_count }}</code>
            <div class="timeline"><span v-for="step in caseItem.timeline" :key="step.session_id">{{ step.phase }}:{{ step.session_id }}</span></div>
          </div>
        </article>
        <article class="panel">
          <div class="section-title">Hippo-Lite 图召回</div>
          <div class="metrics"><span>节点 {{ graph.node_count }}</span><span>边 {{ graph.edge_count }}</span><span>{{ graph.status }}</span></div>
          <div class="run-row"><input v-model="hippoQuery" /><button @click="runHippo">召回 dry-run</button></div>
          <pre>{{ hippoResult || '等待召回 dry-run' }}</pre>
        </article>
      </section>

      <section class="section-block two-col">
        <article class="panel">
          <div class="section-title">MemoryBank 记忆保留</div>
          <div class="run-row"><select v-model="retentionAction"><option>recall</option><option>reinforce</option><option>decay</option></select><button @click="runRetention">模拟</button></div>
          <div class="retention-list"><span v-for="item in retention.items" :key="item.capsule_id">{{ item.capsule_id }} · score {{ item.retention_score }}</span></div>
          <pre>{{ retentionResult || '等待保留 dry-run' }}</pre>
        </article>
        <article class="panel">
          <div class="section-title">Reflexion 评估器</div>
          <div class="chips"><span v-for="item in evaluator.failure_taxonomy" :key="item">{{ item }}</span></div>
          <textarea v-model="reflexionNotes"></textarea><button @click="runReflexion">评估 dry-run</button>
          <pre>{{ reflexionResult || '等待评估 dry-run' }}</pre>
        </article>
      </section>

      <section class="section-block two-col">
        <article class="panel">
          <div class="section-title">记忆工具 API</div>
          <div class="tool-grid"><span v-for="tool in tools.items" :key="tool.tool_name">{{ tool.tool_name }} · {{ tool.mode }}</span></div>
          <div class="run-row"><select v-model="toolName"><option v-for="tool in tools.items" :key="tool.tool_name">{{ tool.tool_name }}</option></select><button @click="runTool">工具 dry-run</button></div>
          <pre>{{ toolResult || '等待工具 dry-run' }}</pre>
        </article>
        <article class="panel">
          <div class="section-title">辅助系统</div>
          <div class="secondary-grid">
            <div><b>MemCube 2.1</b><span>{{ memcube.status }}</span></div>
            <div><b>Memory Tiers（记忆层级）</b><span>{{ tiers.status }}</span></div>
            <div><b>LoCoMo</b><span>{{ locomo.sessions?.length }} 个会话</span></div>
            <div><b>生成流</b><span>{{ stream.status }}</span></div>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 22px; }
.page-head h1 { font-size: 28px; letter-spacing: 3px; }
.page-head p, .muted { color: var(--ink-soft); font-size: 13px; margin-top: 5px; }
.hero-board { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--line); background: rgba(28,26,23,.04); margin-bottom: 12px; }
.hero-board div { display: grid; place-items: center; padding: 16px 8px; border-left: 1px solid var(--line-soft); }
.hero-board div:first-child { border-left: 0; }
.hero-board b { font-size: 34px; font-family: Georgia, serif; color: var(--cinnabar); }
.hero-board span { color: var(--ink-soft); font-size: 11px; }
.boundary { border-left: 4px solid var(--cinnabar); background: rgba(255,255,255,.36); padding: 12px 14px; color: var(--ink-soft); font-size: 13px; margin-bottom: 18px; }
.system-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.system-card { border: 1px solid var(--line); border-top: 4px solid var(--gamboge); background: rgba(255,255,255,.34); padding: 13px; }
.system-card.planned { border-top-color: var(--ink-soft); }
.system-card h2 { font-size: 15px; }
.system-card code { display: block; color: var(--mineral); font-size: 11px; margin: 6px 0; }
.system-card p { color: var(--ink-soft); font-size: 12px; }
.section-block { margin-top: 24px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.panel { border: 1px solid var(--line); background: rgba(255,255,255,.34); padding: 15px; min-width: 0; }
.section-title { border-left: 4px solid var(--cinnabar); padding-left: 10px; margin-bottom: 12px; font-size: 16px; font-weight: 700; letter-spacing: 2px; }
.metrics, .chips, .tool-grid, .secondary-grid, .timeline, .retention-list { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.metrics span, .chips span, .tool-grid span, .timeline span, .retention-list span { border: 1px solid var(--line-soft); padding: 3px 7px; color: var(--ink-soft); font-size: 11px; background: rgba(255,255,255,.38); }
.case-card { border: 1px solid var(--line-soft); padding: 10px; margin-bottom: 10px; }
.case-card b { display: block; font-size: 13px; }
.case-card code { color: var(--mineral); font-size: 10.5px; }
.run-row { display: flex; gap: 8px; margin: 10px 0; }
input, select, textarea { width: 100%; border: 1px solid var(--line); background: rgba(255,255,255,.45); padding: 8px; color: var(--ink); }
textarea { min-height: 66px; resize: vertical; }
button { border: 1px solid var(--cinnabar); color: var(--cinnabar); background: rgba(178,58,46,.07); padding: 8px 11px; white-space: nowrap; }
pre { border: 1px solid var(--line); background: rgba(28,26,23,.04); color: var(--ink-soft); padding: 10px; white-space: pre-wrap; word-break: break-all; max-height: 260px; overflow: auto; font-size: 11px; }
.secondary-grid { display: grid; grid-template-columns: repeat(2, 1fr); }
.secondary-grid div { border: 1px solid var(--line-soft); padding: 12px; background: rgba(255,255,255,.35); }
.secondary-grid b { display: block; margin-bottom: 6px; }
.secondary-grid span { color: var(--mineral); font-size: 12px; }
@media (max-width: 1050px) { .two-col, .system-grid { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .hero-board { grid-template-columns: repeat(2, 1fr); } }
</style>

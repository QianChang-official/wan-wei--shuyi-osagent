<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { api } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfStat from '@/components/gf/GfStat.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

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

type GfTone = 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
function statusTone(status: string): GfTone {
  const tones: Record<string, GfTone> = { done: 'bamboo', partial: 'gold', planned: 'dai', ready: 'bamboo' }
  return tones[status] ?? 'ink'
}

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
    <PageHero
      seal="复"
      title="论文复现"
      en="Paper Reproduction"
      sub="v0.9 轻量级研究系统复现层"
    />

    <div class="stat-row">
      <GfStat label="论文系统" :value="systems.summary?.systems || 9" tone="rouge" />
      <GfStat label="API" :value="systems.summary?.api_count || 14" tone="dai" />
      <GfStat label="部分实现" :value="partialCount" tone="gold" />
      <GfStat label="计划中" :value="plannedCount" tone="ink" />
    </div>

    <p class="note-boundary">不是完整官方复现；这是项目内 lightweight reproduction layer，POST 接口均为 dry-run 或只读/隔离逻辑。</p>

    <GfEmpty v-if="loading" text="研墨中，正在加载论文复现层…" />
    <p v-else-if="error" class="error-note">{{ error }}</p>
    <template v-else>
      <section class="system-grid section">
        <GfCard v-for="item in systems.items" :key="item.id" :title="item.name">
          <code class="code-line">{{ item.source }}</code>
          <div class="sys-meta">
            <GfTag :tone="statusTone(item.status)">{{ item.status }}</GfTag>
            <span class="sys-api">API {{ item.api_count }}</span>
          </div>
        </GfCard>
      </section>

      <div class="grid-two section">
        <GfCard title="MemoryArena 工作台" seal="场">
          <div class="chip-list">
            <GfTag tone="dai">用例 {{ workbench.cases.length }}</GfTag>
            <GfTag tone="gold">断言 {{ workbench.metrics.total_assertions }}</GfTag>
            <GfTag :tone="statusTone(workbench.failure_diagnosis.status)">{{ workbench.failure_diagnosis.status }}</GfTag>
          </div>
          <div v-for="caseItem in workbench.cases" :key="caseItem.case_id" class="case-card">
            <b>{{ caseItem.title || caseItem.case_id }}</b>
            <code class="code-line">{{ caseItem.case_id }} · sessions {{ caseItem.session_count }}</code>
            <div class="vtl">
              <span v-for="step in caseItem.timeline" :key="step.session_id" class="vtl-item">{{ step.phase }}:{{ step.session_id }}</span>
            </div>
          </div>
        </GfCard>
        <GfCard title="Hippo-Lite 图召回" seal="河">
          <div class="chip-list">
            <GfTag tone="dai">节点 {{ graph.node_count }}</GfTag>
            <GfTag tone="dai">边 {{ graph.edge_count }}</GfTag>
            <GfTag :tone="statusTone(graph.status)">{{ graph.status }}</GfTag>
          </div>
          <div class="run-row">
            <input v-model="hippoQuery" class="gf-input" />
            <GfButton small @click="runHippo">召回 dry-run</GfButton>
          </div>
          <pre class="pre-scroll">{{ hippoResult || '等待召回 dry-run' }}</pre>
        </GfCard>
      </div>

      <div class="grid-two section">
        <GfCard title="MemoryBank 记忆保留" seal="库">
          <div class="run-row">
            <select v-model="retentionAction" class="gf-input"><option>recall</option><option>reinforce</option><option>decay</option></select>
            <GfButton small @click="runRetention">模拟</GfButton>
          </div>
          <div class="chip-list">
            <GfTag v-for="item in retention.items" :key="item.capsule_id" tone="ink">{{ item.capsule_id }} · score {{ item.retention_score }}</GfTag>
          </div>
          <pre class="pre-scroll">{{ retentionResult || '等待保留 dry-run' }}</pre>
        </GfCard>
        <GfCard title="Reflexion 评估器" seal="省">
          <div class="chip-list">
            <GfTag v-for="item in evaluator.failure_taxonomy" :key="item" tone="rouge">{{ item }}</GfTag>
          </div>
          <textarea v-model="reflexionNotes" class="gf-input gf-textarea"></textarea>
          <div class="btn-row"><GfButton small @click="runReflexion">评估 dry-run</GfButton></div>
          <pre class="pre-scroll">{{ reflexionResult || '等待评估 dry-run' }}</pre>
        </GfCard>
      </div>

      <div class="grid-two section">
        <GfCard title="记忆工具 API" seal="器">
          <div class="chip-list">
            <GfTag v-for="tool in tools.items" :key="tool.tool_name" tone="dai">{{ tool.tool_name }} · {{ tool.mode }}</GfTag>
          </div>
          <div class="run-row">
            <select v-model="toolName" class="gf-input"><option v-for="tool in tools.items" :key="tool.tool_name">{{ tool.tool_name }}</option></select>
            <GfButton small @click="runTool">工具 dry-run</GfButton>
          </div>
          <pre class="pre-scroll">{{ toolResult || '等待工具 dry-run' }}</pre>
        </GfCard>
        <GfCard title="辅助系统" seal="辅">
          <div class="secondary-grid">
            <div><b>MemCube 2.1</b><GfTag :tone="statusTone(memcube.status)">{{ memcube.status }}</GfTag></div>
            <div><b>Memory Tiers（记忆层级）</b><GfTag :tone="statusTone(tiers.status)">{{ tiers.status }}</GfTag></div>
            <div><b>LoCoMo</b><GfTag tone="dai">{{ locomo.sessions?.length }} 个会话</GfTag></div>
            <div><b>生成流</b><GfTag :tone="statusTone(stream.status)">{{ stream.status }}</GfTag></div>
          </div>
        </GfCard>
      </div>
    </template>
  </div>
</template>

<style scoped>
.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
.section { margin-top: 22px; }
.note-boundary {
  margin-top: 18px;
  padding: 12px 16px;
  border-radius: var(--radius-small);
  border: 1px solid var(--gold-line);
  border-left: 3px solid var(--cinnabar);
  background: var(--card);
  color: var(--ink-soft);
  font-size: 13px;
  line-height: 1.7;
}
.error-note {
  margin-top: 18px;
  padding: 12px 16px;
  border-radius: var(--radius-small);
  border: 1px solid var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 8%, transparent);
  color: var(--cinnabar);
  font-size: 13px;
}
.system-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.code-line { display: block; color: var(--dai); font-size: 11px; font-family: var(--font-mono); word-break: break-all; }
.sys-meta { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.sys-api { color: var(--ink-muted); font-size: 11px; font-family: var(--font-mono); }
.grid-two { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.chip-list { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 10px; }
.case-card {
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--line-soft);
  padding: 12px 14px;
  margin-bottom: 10px;
}
.case-card b { display: block; font-size: 13px; font-family: var(--font-kai); letter-spacing: 1px; color: var(--ink); margin-bottom: 4px; }

/* 用例时间线：朱砂圆点 + 金线 */
.vtl { position: relative; margin: 10px 0 2px; padding-left: 20px; display: grid; gap: 7px; }
.vtl::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 6px;
  bottom: 6px;
  width: 1px;
  background: linear-gradient(180deg, var(--gold-line), var(--gold-line));
}
.vtl-item { position: relative; font-size: 12px; color: var(--ink-soft); font-family: var(--font-mono); }
.vtl-item::before {
  content: '';
  position: absolute;
  left: -19.5px;
  top: 4px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--cinnabar);
  border: 2px solid var(--card-solid);
  box-shadow: 0 0 0 1.5px var(--gold-line);
}

.run-row { display: flex; gap: 10px; margin: 10px 0; align-items: center; }
.btn-row { display: flex; margin: 10px 0; }
.gf-input {
  width: 100%;
  border: 1px solid var(--line);
  background: var(--card);
  border-radius: var(--radius-small);
  padding: 9px 12px;
  color: var(--ink);
  font-size: 13px;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.gf-input:focus { outline: none; border-color: var(--cinnabar); box-shadow: 0 0 0 3px var(--rouge-glow); }
.gf-textarea { min-height: 72px; resize: vertical; line-height: 1.6; }
.pre-scroll {
  border: 1px solid var(--line-soft);
  background: var(--bg-soft);
  border-radius: var(--radius-small);
  color: var(--ink-soft);
  padding: 12px 14px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 260px;
  overflow: auto;
  font-size: 11px;
  font-family: var(--font-mono);
  line-height: 1.6;
}
.secondary-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.secondary-grid > div {
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--line-soft);
  padding: 12px;
  display: grid;
  gap: 8px;
  justify-items: start;
}
.secondary-grid b { font-family: var(--font-kai); font-size: 13px; letter-spacing: 1px; color: var(--ink); }

@media (max-width: 1050px) { .grid-two, .system-grid { grid-template-columns: 1fr; } .stat-row { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 700px) { .secondary-grid { grid-template-columns: 1fr; } }
</style>

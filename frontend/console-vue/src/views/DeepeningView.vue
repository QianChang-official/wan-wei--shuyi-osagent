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
const sessionCore = shallowRef<any>({ fields: [], design_rules: [] })
const demoTrace = shallowRef<any>({ flow: [] })
const reasoning = shallowRef<any>({ modes: [] })
const reasoningResult = shallowRef<any>(null)
const redqueen = shallowRef<any>({ criteria: [] })
const redqueenResult = shallowRef<any>(null)
const contracts = shallowRef<any>({ contracts: [] })
const drift = shallowRef<any>({ checks: [] })
const pathways = shallowRef<any>({ items: [] })
const questions = shallowRef<any>({ items: [] })
const answerResult = shallowRef<any>(null)
const visualProtocol = shallowRef<any>({ required_panels: [], fallback_path: [] })
const visualResult = shallowRef<any>(null)

const selectedMode = shallowRef('deep')
const selectedQuestion = shallowRef('chain_design')
const redqueenDraft = shallowRef('v0.9.1 deepening page includes Visual Verification, Contract Truth, and partial/planned boundaries.')

const modeSummary = computed(() => reasoning.value.modes?.map((item: any) => item.mode).join(' / ') || '')
const contractLayers = computed(() => contracts.value.contracts?.map((item: any) => item.layer).join(' / ') || '')
const firstQuestion = computed(() => questions.value.items?.[0]?.id || 'chain_design')

type GfTone = 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
function statusTone(status: string): GfTone {
  const tones: Record<string, GfTone> = { done: 'bamboo', ok: 'bamboo', pass: 'bamboo', partial: 'gold', planned: 'dai' }
  return tones[status] ?? 'ink'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [sessionRes, traceRes, reasoningRes, redqueenRes, contractRes, driftRes, pathwayRes, questionRes, visualRes] = await Promise.all([
      api.deepeningSessionCoreDesign(),
      api.deepeningSessionCoreDemoTrace(),
      api.deepeningReasoningDepthDesign(),
      api.deepeningRedQueenEvaluatorDesign(),
      api.deepeningContractSourceOfTruth(),
      api.deepeningContractDriftCheck(),
      api.deepeningAgiAsiPathways(),
      api.deepeningInterrogationQuestions(),
      api.deepeningVisualVerificationProtocol(),
    ])
    sessionCore.value = sessionRes
    demoTrace.value = traceRes
    reasoning.value = reasoningRes
    redqueen.value = redqueenRes
    contracts.value = contractRes
    drift.value = driftRes
    pathways.value = pathwayRes
    questions.value = questionRes
    visualProtocol.value = visualRes
    selectedQuestion.value = firstQuestion.value
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function runReasoning() {
  reasoningResult.value = await api.deepeningReasoningDepthSimulate({ mode: selectedMode.value, task_type: 'architecture_review', task_risk: selectedMode.value === 'audit' ? 'high' : 'medium' })
}

async function runRedQueen() {
  redqueenResult.value = await api.deepeningRedQueenEvaluateDryRun({ agent_output: redqueenDraft.value, utility_epoch: 'epoch_v091', adversarial_objective: 'find weak assumptions', metrics: { arena_assertions: 16 } })
}

async function runAnswer() {
  answerResult.value = await api.deepeningInterrogationAnswerDryRun({ question_id: selectedQuestion.value, detail_level: 'deep', context: 'v0.9.1 Deep Expansion & Visual Verification' })
}

async function runVisual() {
  visualResult.value = await api.deepeningVisualVerificationChecklistDryRun({ route: '/console/#/deepening', page_name: 'DeepeningView', fallback_mode: true })
}

onMounted(load)
</script>

<template>
  <div>
    <PageHero
      seal="问"
      title="深做追问"
      en="Deepening Inquiry"
      sub="v0.9.1 深度扩展与可视验证"
    />

    <div class="stat-row">
      <GfStat label="会话核心" value="会话" tone="rouge" />
      <GfStat label="推理深度" value="深度" tone="dai" :hint="modeSummary" />
      <GfStat label="合约真值" value="真值" tone="gold" :hint="contractLayers" />
      <GfStat label="可视验证" value="可视" hint="可视验证" />
    </div>

    <p class="note-boundary">本页只调用项目内 v0.9.1 dry-run / read-only API；不联网，不修改真实记忆，不声明完整复现外部系统。</p>

    <GfEmpty v-if="loading" text="研墨中，正在加载深做追问层…" />
    <p v-else-if="error" class="error-note">{{ error }}</p>

    <template v-else>
      <div class="grid-two section">
        <GfCard title="会话核心" seal="话">
          <div class="chip-list">
            <GfTag v-for="field in sessionCore.fields" :key="field.name" tone="dai">{{ field.name }} · {{ field.source_layer }}</GfTag>
          </div>
          <div class="vtl">
            <span v-for="step in demoTrace.flow" :key="step.stage" class="vtl-item">{{ step.stage }} → {{ step.item }}</span>
          </div>
        </GfCard>
        <GfCard title="推理深度" seal="深">
          <div class="mode-grid">
            <div v-for="mode in reasoning.modes" :key="mode.mode" class="mini-card">
              <div class="mini-head"><b>{{ mode.mode }}</b><GfTag tone="gold">{{ mode.estimated_token_multiplier }}x</GfTag></div>
              <span>{{ mode.evidence_requirement }}</span>
            </div>
          </div>
          <div class="run-row">
            <select v-model="selectedMode" class="gf-input"><option>shallow</option><option>normal</option><option>deep</option><option>audit</option></select>
            <GfButton small @click="runReasoning">模拟运行</GfButton>
          </div>
          <pre class="pre-scroll">{{ reasoningResult || '等待 reasoning-depth simulate dry-run' }}</pre>
        </GfCard>
      </div>

      <div class="grid-two section">
        <GfCard title="红皇后评估器" seal="后">
          <div class="chip-list">
            <GfTag v-for="item in redqueen.criteria" :key="item.id" tone="rouge">{{ item.id }} · {{ item.weight }}</GfTag>
          </div>
          <textarea v-model="redqueenDraft" class="gf-input gf-textarea"></textarea>
          <div class="btn-row"><GfButton small @click="runRedQueen">评估 dry-run</GfButton></div>
          <pre class="pre-scroll">{{ redqueenResult || '等待 red queen evaluator dry-run' }}</pre>
        </GfCard>
        <GfCard title="合约真值" seal="契">
          <div class="group-label">合约层</div>
          <div class="chip-list">
            <GfTag v-for="item in contracts.contracts" :key="item.layer" :tone="statusTone(item.status)">{{ item.layer }} · {{ item.status }}</GfTag>
          </div>
          <div class="group-label">漂移检查</div>
          <div class="chip-list">
            <GfTag v-for="item in drift.checks" :key="item.id" :tone="statusTone(item.status)">{{ item.id }} · {{ item.status }}</GfTag>
          </div>
        </GfCard>
      </div>

      <div class="grid-two section">
        <GfCard title="AGI 到 ASI 路径" seal="径">
          <div class="path-list">
            <div v-for="item in pathways.items" :key="item.path" class="mini-card">
              <b>{{ item.path }}</b>
              <span>{{ item.osagent_mapping }}</span>
              <div class="path-gate">
                <GfTag tone="dai">{{ item.current_state }}</GfTag>
                <span class="gate-arrow">→</span>
                <GfTag tone="gold">{{ item.next_gate }}</GfTag>
              </div>
            </div>
          </div>
        </GfCard>
        <GfCard title="连环追问" seal="问">
          <div class="run-row">
            <select v-model="selectedQuestion" class="gf-input"><option v-for="item in questions.items" :key="item.id" :value="item.id">{{ item.title }}</option></select>
            <GfButton small @click="runAnswer">回答 dry-run</GfButton>
          </div>
          <div class="chip-list">
            <GfTag v-for="item in questions.items" :key="item.id" tone="ink">{{ item.id }} · {{ item.focus }}</GfTag>
          </div>
          <pre class="pre-scroll">{{ answerResult || '等待连环追问 dry-run' }}</pre>
        </GfCard>
      </div>

      <div class="grid-two section">
        <GfCard title="可视验证" seal="视">
          <div class="chip-list">
            <GfTag v-for="item in visualProtocol.required_panels" :key="item" tone="dai">{{ item }}</GfTag>
          </div>
          <div class="group-label">降级路径</div>
          <div class="chip-list">
            <GfTag v-for="item in visualProtocol.fallback_path" :key="item" tone="gold">{{ item }}</GfTag>
          </div>
          <div class="btn-row"><GfButton small @click="runVisual">清单 dry-run</GfButton></div>
          <pre class="pre-scroll">{{ visualResult || '等待 visual checklist dry-run' }}</pre>
        </GfCard>
        <GfCard title="v0.1-v0.9 加厚边界" seal="厚">
          <div class="thickening-grid">
            <div class="mini-card"><b>链路怎么设计</b><span>source_layer → policy → capsule → evidence → export</span></div>
            <div class="mini-card"><b>Token 怎么省</b><span>mode routing + top-k + summary + fallback tokens</span></div>
            <div class="mini-card"><b>线上挂了怎么办</b><span>/health + smoke + dist fallback + reports</span></div>
            <div class="mini-card"><b>数据在哪里</b><span>SQLite / reports / docs / git / runtime_log</span></div>
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
.grid-two { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.chip-list { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 10px; }
.group-label { font-family: var(--font-kai); font-size: 12px; letter-spacing: 2px; color: var(--gold); margin: 10px 0 6px; }

/* 会话流转：朱砂圆点 + 金线 */
.vtl { position: relative; margin: 10px 0 2px; padding-left: 20px; display: grid; gap: 8px; }
.vtl::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 6px;
  bottom: 6px;
  width: 1px;
  background: linear-gradient(180deg, var(--gold-line), var(--gold-line));
}
.vtl-item { position: relative; font-size: 12px; color: var(--ink-soft); line-height: 1.6; }
.vtl-item::before {
  content: '';
  position: absolute;
  left: -19.5px;
  top: 5px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--cinnabar);
  border: 2px solid var(--card-solid);
  box-shadow: 0 0 0 1.5px var(--gold-line);
}

.mode-grid, .path-list, .thickening-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.mini-card {
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--line-soft);
  padding: 12px;
  display: grid;
  gap: 6px;
  align-content: start;
}
.mini-card b { font-family: var(--font-kai); font-size: 13px; letter-spacing: 1px; color: var(--cinnabar); }
.mini-card span { color: var(--ink-soft); font-size: 12px; line-height: 1.6; }
.mini-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.path-gate { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.gate-arrow { color: var(--gold); font-size: 12px; }

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
.gf-textarea { min-height: 78px; resize: vertical; line-height: 1.6; }
.pre-scroll {
  border: 1px solid var(--line-soft);
  background: var(--bg-soft);
  border-radius: var(--radius-small);
  color: var(--ink-soft);
  padding: 12px 14px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow: auto;
  font-size: 11px;
  font-family: var(--font-mono);
  line-height: 1.6;
}

@media (max-width: 1050px) { .grid-two, .mode-grid, .path-list, .thickening-grid { grid-template-columns: 1fr; } .stat-row { grid-template-columns: repeat(2, 1fr); } }
</style>

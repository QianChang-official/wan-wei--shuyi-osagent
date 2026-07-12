<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'

const goal = ref('提交 v0.6 文档变更前，生成只读检查计划')
const scene = ref('coding')
const topK = ref(5)
const result = ref<any | null>(null)
const loading = ref(false)
const err = ref('')

const RISK_COLOR: Record<string,string> = { low:'var(--jade)', medium:'var(--gamboge)', high:'var(--cinnabar)', critical:'#8B0000' }
const MODE_LABEL: Record<string,string> = { advisory_mode:'建议模式', supervised_mode:'监督执行', read_only_mode:'只读分析' }

async function run() {
  loading.value = true; err.value = ''; result.value = null
  try { result.value = await api.command(goal.value, scene.value, topK.value) }
  catch (e: any) { err.value = String(e) }
  loading.value = false
}
</script>

<template>
  <div>
    <div class="page-head">
      <h1>司契护栏 · 指挥闭环</h1>
      <p>Command Loop — 输入任务目标，召回记忆，生成带风险分级的执行计划</p>
    </div>
    <div class="form">
      <label>任务目标 goal</label>
      <textarea v-model="goal" rows="3"></textarea>
      <div class="row">
        <div><label>scene（场景）</label>
          <select v-model="scene"><option value="general">通用</option><option value="coding">编程</option><option value="ops">运维</option><option value="research">研究</option><option value="security">安全</option></select>
        </div>
        <div><label>top_k（返回数量）</label><input v-model.number="topK" type="number" min="1" max="20" /></div>
      </div>
      <button @click="run" :disabled="loading">{{ loading ? '运行中…' : '▶ 运行 Command Loop' }}</button>
    </div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="result">
      <div class="summary-bar">
        <span class="risk-badge" :style="{ background: RISK_COLOR[result.task_understanding?.risk_class] }">
          风险 {{ result.task_understanding?.risk_class }}
        </span>
        <span class="mode-badge">{{ MODE_LABEL[result.execution_mode] || result.execution_mode }}</span>
        <span class="safe-badge" :class="{ ok: !result.risk_assessment?.unsafe_autonomy }">
          越权自动化：{{ result.risk_assessment?.unsafe_autonomy ? '⚠ 检测到' : '✓ 无' }}
        </span>
        <span class="cnt-badge">召回 {{ result.recalled_memories?.length }} 条记忆</span>
        <span class="cnt-badge">{{ result.evidence_cards?.length }} 张证据卡</span>
      </div>

      <div class="result-grid">
        <section>
          <h3>执行计划</h3>
          <div v-for="step in result.recommended_plan" :key="step.step" class="step">
            <span class="step-n">{{ step.step }}</span>
            <div>
              <div class="step-act">{{ step.action }}</div>
              <div class="step-meta">风险 {{ step.risk_level }} · 需确认 {{ step.requires_confirmation ? '是' : '否' }}</div>
            </div>
          </div>
        </section>
        <section>
          <h3>证据卡 <span class="cnt">{{ result.evidence_cards?.length }}</span></h3>
          <div v-for="ec in result.evidence_cards" :key="ec.evidence_id" class="ec">
            <span class="tag cls">{{ ec.memory_class }}</span>
            <span class="ec-claim">{{ (ec.claim || '').slice(0, 90) }}</span>
            <div class="ec-meta">trust={{ ec.trust_score }}</div>
          </div>
        </section>
      </div>

      <div v-if="result.confirmation_points?.length" class="confirms">
        <h3>⚠ 确认点</h3>
        <div v-for="cp in result.confirmation_points" :key="cp.confirmation_id" class="confirm-card">
          <div class="cc-reason">{{ cp.reason }}</div>
          <div class="cc-q">{{ cp.question }}</div>
          <div class="cc-default">不操作默认：{{ cp.default_action_if_no_response }}</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 24px; }
.page-head h1 { font-size: 28px; font-weight: 700; letter-spacing: 3px; }
.page-head p { font-size: 13px; color: var(--ink-soft); margin-top: 4px; }
.form { border: 1px solid var(--line); background: rgba(255,255,255,.35); padding: 16px; margin-bottom: 18px; display: flex; flex-direction: column; gap: 10px; }
label { font-size: 12px; color: var(--ink-soft); }
textarea, input, select { width: 100%; border: 1px solid var(--line); padding: 7px 10px; background: rgba(255,255,255,.6); font-family: inherit; font-size: 13px; color: var(--ink); resize: vertical; }
.row { display: flex; gap: 12px; }
.row > div { flex: 1; }
button { align-self: flex-start; background: var(--ink); color: #EFE7D3; border: none; padding: 9px 22px; font-family: inherit; font-size: 13px; letter-spacing: 1px; cursor: pointer; }
button:hover { background: var(--cinnabar); }
button:disabled { opacity: .5; cursor: default; }
.err { color: var(--cinnabar); font-size: 13px; margin-bottom: 12px; }
.summary-bar { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; padding: 12px 16px; border: 1px solid var(--line); background: rgba(255,255,255,.3); }
.risk-badge { color: #fff; padding: 4px 12px; border-radius: 3px; font-size: 13px; font-weight: 700; }
.mode-badge { border: 1px solid var(--mineral); color: var(--mineral); padding: 3px 10px; font-size: 12px; }
.safe-badge { font-size: 13px; color: var(--cinnabar); }
.safe-badge.ok { color: var(--jade); }
.cnt-badge { font-size: 12px; color: var(--ink-soft); }
.result-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
section h3 { font-size: 15px; letter-spacing: 2px; margin-bottom: 12px; }
.cnt { font-size: 11px; background: var(--cinnabar); color: #fff; border-radius: 10px; padding: 1px 7px; }
.step { display: flex; gap: 12px; padding: 10px; border: 1px solid var(--line); background: rgba(255,255,255,.3); margin-bottom: 8px; }
.step-n { width: 26px; height: 26px; background: var(--cinnabar); color: #fff; border-radius: 50%; display: grid; place-items: center; font-size: 13px; font-weight: 700; flex-shrink: 0; }
.step-act { font-size: 13px; font-weight: 600; }
.step-meta { font-size: 11px; color: var(--ink-soft); margin-top: 3px; }
.ec { border: 1px solid var(--line); padding: 9px 11px; margin-bottom: 8px; }
.tag { display: inline-block; padding: 1px 7px; font-size: 11px; border-radius: 2px; }
.tag.cls { background: var(--mineral); color: #fff; margin-right: 6px; }
.ec-claim { font-size: 12.5px; color: var(--ink); }
.ec-meta { font-size: 11px; color: var(--ink-soft); margin-top: 3px; font-family: var(--mono); }
.confirms { margin-top: 18px; border: 1px solid var(--cinnabar); background: rgba(178,58,46,.04); padding: 14px; }
.confirms h3 { font-size: 14px; letter-spacing: 2px; color: var(--cinnabar); margin-bottom: 10px; }
.confirm-card { border: 1px solid rgba(178,58,46,.3); padding: 10px; margin-bottom: 8px; }
.cc-reason { font-size: 11px; color: var(--cinnabar); font-weight: 700; margin-bottom: 4px; }
.cc-q { font-size: 13px; color: var(--ink); }
.cc-default { font-size: 11px; color: var(--ink-soft); margin-top: 5px; }
@media (max-width: 860px) { .result-grid { grid-template-columns: 1fr; } }
</style>

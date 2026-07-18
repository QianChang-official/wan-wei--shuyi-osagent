<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

const goal = ref('提交 v0.6 文档变更前，生成只读检查计划')
const scene = ref('coding')
const topK = ref(5)
const result = ref<any | null>(null)
const loading = ref(false)
const err = ref('')

const RISK_COLOR: Record<string,string> = { low:'var(--bamboo)', medium:'var(--gold)', high:'var(--cinnabar)', critical:'var(--cinnabar-deep)' }
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
    <PageHero
      seal="契"
      title="司契指挥"
      en="Command Loop"
      sub="输入任务目标，召回记忆，生成带风险分级的执行计划"
    />

    <GfCard seal="契" title="任务书" class="form-card">
      <label>任务目标 goal</label>
      <textarea v-model="goal" rows="3"></textarea>
      <div class="row">
        <div>
          <label>scene（场景）</label>
          <select v-model="scene"><option value="general">通用</option><option value="coding">编程</option><option value="ops">运维</option><option value="research">研究</option><option value="security">安全</option></select>
        </div>
        <div>
          <label>top_k（返回数量）</label>
          <input v-model.number="topK" type="number" min="1" max="20" />
        </div>
      </div>
      <template #footer>
        <GfButton @click="run" :disabled="loading">{{ loading ? '筹谋中…' : '运行 Command Loop' }}</GfButton>
      </template>
    </GfCard>

    <div v-if="err" class="err">{{ err }}</div>

    <template v-if="result">
      <div class="summary-bar">
        <span class="risk-badge" :style="{ background: RISK_COLOR[result.task_understanding?.risk_class] }">
          风险 {{ result.task_understanding?.risk_class }}
        </span>
        <GfTag tone="dai">{{ MODE_LABEL[result.execution_mode] || result.execution_mode }}</GfTag>
        <span class="safe-badge" :class="{ ok: !result.risk_assessment?.unsafe_autonomy }">
          越权自动化：{{ result.risk_assessment?.unsafe_autonomy ? '检测到' : '无' }}
        </span>
        <GfTag tone="ink">召回 {{ result.recalled_memories?.length }} 条记忆</GfTag>
        <GfTag tone="ink">{{ result.evidence_cards?.length }} 张证据卡</GfTag>
      </div>

      <div class="result-grid">
        <GfCard class="result-card">
          <template #header>
            <span class="rc-seal">策</span>
            <h3 class="rc-title">执行计划</h3>
          </template>
          <GfEmpty v-if="!result.recommended_plan?.length" text="此番未出策" />
          <div v-for="step in result.recommended_plan" :key="step.step" class="step">
            <span class="step-n">{{ step.step }}</span>
            <div>
              <div class="step-act">{{ step.action }}</div>
              <div class="step-meta">风险 {{ step.risk_level }} · 需确认 {{ step.requires_confirmation ? '是' : '否' }}</div>
            </div>
          </div>
        </GfCard>

        <GfCard class="result-card">
          <template #header>
            <span class="rc-seal">证</span>
            <h3 class="rc-title">证据卡 <span class="cnt">{{ result.evidence_cards?.length }}</span></h3>
          </template>
          <GfEmpty v-if="!result.evidence_cards?.length" text="未召回证据卡" />
          <div v-for="ec in result.evidence_cards" :key="ec.evidence_id" class="ec">
            <GfTag tone="dai">{{ ec.memory_class }}</GfTag>
            <span class="ec-claim">{{ (ec.claim || '').slice(0, 90) }}</span>
            <div class="ec-meta">trust={{ ec.trust_score }}</div>
          </div>
        </GfCard>
      </div>

      <div v-if="result.confirmation_points?.length" class="confirms">
        <h3><span class="cf-seal">慎</span>确认点</h3>
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
.form-card { margin-bottom: 20px; }
label {
  display: block;
  font-size: 11px;
  letter-spacing: 1.5px;
  color: var(--ink-muted);
  margin-bottom: 5px;
}
textarea, input, select {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  padding: 8px 12px;
  background: var(--card);
  font-family: inherit;
  font-size: 13px;
  color: var(--ink);
  resize: vertical;
  transition: border-color .18s ease, box-shadow .18s ease;
  margin-bottom: 12px;
}
textarea:focus, input:focus, select:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.row { display: flex; gap: 14px; }
.row > div { flex: 1; }
.row input, .row select { margin-bottom: 0; }
.err {
  color: var(--cinnabar);
  font-size: 13px;
  margin-bottom: 12px;
  padding: 10px 14px;
  border: 1px solid color-mix(in srgb, var(--cinnabar) 32%, transparent);
  background: color-mix(in srgb, var(--cinnabar) 7%, transparent);
  border-radius: var(--radius-small);
}
.summary-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  padding: 13px 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: var(--shadow-card);
}
.risk-badge {
  color: #FDF6E9;
  padding: 4px 16px;
  border-radius: 999px;
  font-family: var(--font-kai);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 2px;
  box-shadow: var(--shadow-card);
}
.safe-badge { font-size: 13px; color: var(--cinnabar); letter-spacing: 1px; }
.safe-badge.ok { color: var(--bamboo); }
.result-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
.rc-seal {
  font-family: var(--font-kai);
  font-size: 13px;
  font-weight: 700;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: 0 0 10px var(--cinnabar-glow);
  flex-shrink: 0;
}
.rc-title {
  font-family: var(--font-kai);
  font-size: 20px;
  letter-spacing: 3px;
  color: var(--ink);
  font-weight: 700;
}
.cnt {
  font-family: var(--font-mono);
  font-size: 11px;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  border-radius: 999px;
  padding: 1px 9px;
  margin-left: 6px;
  letter-spacing: 0;
  box-shadow: 0 0 8px var(--cinnabar-glow);
}
.step {
  display: flex;
  gap: 12px;
  padding: 11px 13px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--card);
  margin-bottom: 8px;
  transition: background .18s ease, border-color .18s ease;
}
.step:hover {
  background: color-mix(in srgb, var(--rouge) 8%, transparent);
  border-color: color-mix(in srgb, var(--rouge) 28%, transparent);
}
.step-n {
  width: 26px;
  height: 26px;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-family: var(--font-kai);
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: 0 0 8px var(--cinnabar-glow);
}
.step-act { font-size: 13px; font-weight: 600; line-height: 1.5; }
.step-meta { font-size: 11px; color: var(--ink-muted); margin-top: 3px; }
.ec {
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--card);
  padding: 10px 12px;
  margin-bottom: 8px;
}
.ec-claim { font-size: 12.5px; color: var(--ink); margin-left: 6px; line-height: 1.5; }
.ec-meta { font-size: 11px; color: var(--dai); margin-top: 4px; font-family: var(--font-mono); }
.confirms {
  margin-top: 20px;
  border: 1px solid color-mix(in srgb, var(--cinnabar) 34%, transparent);
  border-radius: var(--radius-card);
  background: color-mix(in srgb, var(--cinnabar) 5%, transparent);
  padding: 16px 18px;
}
.confirms h3 {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-kai);
  font-size: 16px;
  letter-spacing: 3px;
  color: var(--cinnabar);
  margin-bottom: 12px;
}
.cf-seal {
  font-size: 12px;
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: 0 0 10px var(--cinnabar-glow);
}
.confirm-card {
  border: 1px solid color-mix(in srgb, var(--cinnabar) 26%, transparent);
  border-radius: var(--radius-small);
  background: var(--card);
  padding: 11px 13px;
  margin-bottom: 8px;
}
.cc-reason { font-size: 11px; color: var(--cinnabar); font-weight: 700; letter-spacing: 1px; margin-bottom: 4px; }
.cc-q { font-size: 13px; color: var(--ink); line-height: 1.6; }
.cc-default { font-size: 11px; color: var(--ink-muted); margin-top: 5px; }
@media (max-width: 860px) { .result-grid { grid-template-columns: 1fr; } }
</style>

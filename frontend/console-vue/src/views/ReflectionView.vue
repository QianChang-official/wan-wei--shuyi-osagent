<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

const taskId = ref('task_demo_' + Math.random().toString(36).slice(2, 8))
const goalAchieved = ref(true)
const helpful = ref('')
const misleading = ref('')
const newRisk = ref('提交前只看聊天界面渲染、不看真实文件，可能误判 JSON 失效')
const result = ref<any | null>(null)
const loading = ref(false)
const err = ref('')

async function run() {
  loading.value = true; err.value = ''; result.value = null
  const payload: any = {
    task_id: taskId.value,
    goal_achieved: goalAchieved.value,
    helpful_memories: helpful.value.split(',').map(s => s.trim()).filter(Boolean),
    misleading_memories: misleading.value.split(',').map(s => s.trim()).filter(Boolean),
    new_risks: newRisk.value.trim() ? [{ risk_statement: newRisk.value.trim() }] : [],
  }
  try { result.value = await api.reflection(payload) }
  catch (e: any) { err.value = String(e) }
  loading.value = false
}

const ACTION_LABEL: Record<string,string> = { reinforce:'强化', deprecate:'废弃', promote:'提升', conflict_mark:'标冲突' }
type TagTone = 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
const ACTION_TONE: Record<string, TagTone> = { reinforce: 'bamboo', deprecate: 'ink', promote: 'gold', conflict_mark: 'rouge' }
</script>

<template>
  <div>
    <PageHero
      seal="鉴"
      title="兰台复盘"
      en="Reflection"
      sub="任务结束后复盘，触发记忆演化动作（强化 / 废弃 / 提升为风险记忆）"
    />

    <GfCard seal="复" title="复盘录" class="form-card">
      <label>task_id</label>
      <input v-model="taskId" />
      <label class="check-row">
        <input type="checkbox" v-model="goalAchieved" />
        <span>目标达成 goal_achieved</span>
      </label>
      <label>有帮助的记忆 ID（逗号分隔）→ reinforce（强化）</label>
      <input v-model="helpful" placeholder="cap_xxx, cap_yyy" />
      <label>误导的记忆 ID（逗号分隔）→ deprecate（废弃）</label>
      <input v-model="misleading" placeholder="cap_zzz" />
      <label>新风险 → 写入风险记忆 risk memory（promote 提升）</label>
      <textarea v-model="newRisk" rows="2"></textarea>
      <template #footer>
        <GfButton @click="run" :disabled="loading">{{ loading ? '复盘中…' : '提交复盘' }}</GfButton>
      </template>
    </GfCard>

    <div v-if="err" class="err">{{ err }}</div>

    <GfCard v-if="result" class="result-card">
      <template #header>
        <span class="rc-seal">鉴</span>
        <h3 class="rc-title">演化动作 <span class="cnt">{{ result.evolution_actions?.length || 0 }}</span></h3>
      </template>
      <div class="rid">复盘编号 {{ result.reflection_id }}</div>
      <GfEmpty v-if="!result.evolution_actions?.length" text="本次复盘未触发演化动作" />
      <div v-for="(a, i) in result.evolution_actions" :key="i" class="action">
        <GfTag :tone="ACTION_TONE[a.action] || 'ink'">{{ ACTION_LABEL[a.action] || a.action }}</GfTag>
        <span class="act-cap">{{ a.capsule_id }}</span>
        <GfTag v-if="a.memory_class" tone="dai">{{ a.memory_class }}</GfTag>
      </div>
    </GfCard>
  </div>
</template>

<style scoped>
.form-card { max-width: 640px; margin-bottom: 20px; }
label {
  display: block;
  font-size: 11px;
  letter-spacing: 1.5px;
  color: var(--ink-muted);
  margin-bottom: 5px;
}
input, textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  padding: 8px 12px;
  background: var(--card);
  font-family: inherit;
  font-size: 13px;
  color: var(--ink);
  transition: border-color .18s ease, box-shadow .18s ease;
  margin-bottom: 12px;
}
input:focus, textarea:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
textarea { resize: vertical; }
.check-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 2px 0 12px;
  font-size: 13px;
  color: var(--ink-soft);
  letter-spacing: 1px;
}
.check-row input[type='checkbox'] {
  width: 15px;
  height: 15px;
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  accent-color: var(--cinnabar);
  flex-shrink: 0;
}
.err {
  color: var(--cinnabar);
  font-size: 13px;
  margin-bottom: 12px;
  padding: 10px 14px;
  border: 1px solid color-mix(in srgb, var(--cinnabar) 32%, transparent);
  background: color-mix(in srgb, var(--cinnabar) 7%, transparent);
  border-radius: var(--radius-small);
  max-width: 640px;
}
.result-card { max-width: 640px; }
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
.rid { font-family: var(--font-mono); font-size: 12px; color: var(--ink-muted); margin-bottom: 14px; }
.action {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--card);
  margin-bottom: 8px;
  transition: background .18s ease, border-color .18s ease;
}
.action:hover {
  background: color-mix(in srgb, var(--rouge) 8%, transparent);
  border-color: color-mix(in srgb, var(--rouge) 28%, transparent);
}
.act-cap { font-family: var(--font-mono); font-size: 12px; color: var(--ink); }
</style>

<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'

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
</script>

<template>
  <div>
    <div class="page-head">
      <h1>句芒演化 · 复盘反思</h1>
      <p>Reflection — 任务结束后复盘，触发记忆演化动作（强化 / 废弃 / 提升为风险记忆）</p>
    </div>
    <div class="form">
      <label>task_id</label>
      <input v-model="taskId" />
      <label><input type="checkbox" v-model="goalAchieved" /> 目标达成 goal_achieved</label>
      <label>有帮助的记忆 ID（逗号分隔）→ reinforce</label>
      <input v-model="helpful" placeholder="cap_xxx, cap_yyy" />
      <label>误导的记忆 ID（逗号分隔）→ deprecate</label>
      <input v-model="misleading" placeholder="cap_zzz" />
      <label>新风险 → 写入 risk memory (promote)</label>
      <textarea v-model="newRisk" rows="2"></textarea>
      <button @click="run" :disabled="loading">{{ loading ? '复盘中…' : '▶ 提交复盘' }}</button>
    </div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="result" class="result">
      <div class="rid">复盘编号 {{ result.reflection_id }}</div>
      <h3>演化动作 <span class="cnt">{{ result.evolution_actions?.length || 0 }}</span></h3>
      <div v-if="!result.evolution_actions?.length" class="empty">本次复盘未触发演化动作</div>
      <div v-for="(a, i) in result.evolution_actions" :key="i" class="action">
        <span class="act-badge">{{ ACTION_LABEL[a.action] || a.action }}</span>
        <span class="act-cap">{{ a.capsule_id }}</span>
        <span v-if="a.memory_class" class="act-cls">{{ a.memory_class }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 24px; }
.page-head h1 { font-size: 28px; font-weight: 700; letter-spacing: 3px; }
.page-head p { font-size: 13px; color: var(--ink-soft); margin-top: 4px; }
.form { border: 1px solid var(--line); background: rgba(255,255,255,.35); padding: 16px; margin-bottom: 18px; display: flex; flex-direction: column; gap: 9px; max-width: 640px; }
label { font-size: 12px; color: var(--ink-soft); }
input, textarea { width: 100%; border: 1px solid var(--line); padding: 7px 10px; background: rgba(255,255,255,.6); font-family: inherit; font-size: 13px; color: var(--ink); }
button { align-self: flex-start; background: var(--ink); color: #EFE7D3; border: none; padding: 9px 22px; font-family: inherit; font-size: 13px; letter-spacing: 1px; cursor: pointer; }
button:hover { background: var(--cinnabar); }
button:disabled { opacity: .5; }
.err { color: var(--cinnabar); font-size: 13px; }
.result { border: 1px solid var(--line); background: rgba(255,255,255,.3); padding: 16px; max-width: 640px; }
.rid { font-family: var(--mono); font-size: 12px; color: var(--ink-soft); margin-bottom: 12px; }
h3 { font-size: 15px; letter-spacing: 2px; margin-bottom: 12px; }
.cnt { font-size: 11px; background: var(--cinnabar); color: #fff; border-radius: 10px; padding: 1px 7px; }
.empty { font-size: 13px; color: var(--ink-soft); }
.action { display: flex; align-items: center; gap: 10px; padding: 9px 11px; border: 1px solid var(--line); margin-bottom: 8px; }
.act-badge { background: var(--jade); color: #fff; padding: 2px 10px; font-size: 12px; border-radius: 2px; }
.act-cap { font-family: var(--mono); font-size: 12px; color: var(--ink); }
.act-cls { background: var(--mineral); color: #fff; font-size: 11px; padding: 1px 7px; border-radius: 2px; }
</style>

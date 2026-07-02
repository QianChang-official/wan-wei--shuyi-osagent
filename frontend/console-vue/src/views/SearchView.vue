<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'

const q = ref('引用 规范')
const topK = ref(5)
const highRisk = ref(false)
const results = ref<any[]>([])
const evidenceCards = ref<any[]>([])
const loading = ref(false)
const err = ref('')

async function doSearch() {
  loading.value = true; err.value = ''; results.value = []; evidenceCards.value = []
  try {
    const r = await api.search(q.value, topK.value, highRisk.value)
    results.value = r.results || []
    evidenceCards.value = r.evidence_cards || []
  } catch (e: any) { err.value = String(e) }
  loading.value = false
}
</script>

<template>
  <div>
    <div class="page-head">
      <h1>琅嬛知识 · 可信检索</h1>
      <p>Trust-aware Retrieval — 带治理过滤与证据卡的召回</p>
    </div>
    <div class="form">
      <div class="row">
        <div style="flex:1">
          <label>查询词 q</label>
          <input v-model="q" @keyup.enter="doSearch" placeholder="输入检索词…" />
        </div>
        <div style="width:80px"><label>top_k</label><input v-model.number="topK" type="number" min="1" max="20" /></div>
        <div style="width:90px">
          <label>high_risk</label>
          <select v-model="highRisk"><option :value="false">否</option><option :value="true">是</option></select>
        </div>
      </div>
      <button @click="doSearch" :disabled="loading">{{ loading ? '检索中…' : '检索' }}</button>
    </div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="results.length || evidenceCards.length" class="results-layout">
      <section>
        <h3>召回记忆 <span class="cnt">{{ results.length }}</span></h3>
        <div v-for="c in results" :key="c.capsule_id" class="cap-row">
          <span class="tag cls">{{ c.memory_class }}</span>
          <span class="tag" :class="c.state?.lifecycle">{{ c.state?.lifecycle }}</span>
          <span class="cap-id">{{ c.capsule_id }}</span>
          <span class="score">得分 {{ (c.retrieval_score ?? 0).toFixed(3) }}</span>
        </div>
      </section>
      <section>
        <h3>证据卡 <span class="cnt">{{ evidenceCards.length }}</span></h3>
        <div v-for="ec in evidenceCards" :key="ec.evidence_id" class="ec-card">
          <div class="ec-head">
            <span class="tag cls">{{ ec.memory_class }}</span>
            <span class="tag mineral">{{ ec.used_for }}</span>
            <span class="ec-id">{{ ec.evidence_id }}</span>
          </div>
          <div class="ec-claim">{{ ec.claim }}</div>
          <div class="ec-meta">trust={{ ec.trust_score }} · conf={{ ec.confidence }} · source={{ ec.source }}</div>
          <div class="ec-limit">{{ ec.limitations }}</div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 24px; }
.page-head h1 { font-size: 28px; font-weight: 700; letter-spacing: 3px; }
.page-head p { font-size: 13px; color: var(--ink-soft); margin-top: 4px; }
.form { display: flex; flex-direction: column; gap: 10px; margin-bottom: 22px; border: 1px solid var(--line); background: rgba(255,255,255,.35); padding: 16px; }
.row { display: flex; gap: 12px; align-items: flex-end; }
label { display: block; font-size: 12px; color: var(--ink-soft); margin-bottom: 4px; }
input, select { width: 100%; border: 1px solid var(--line); padding: 7px 10px; background: rgba(255,255,255,.6); font-family: inherit; font-size: 13px; color: var(--ink); }
button { align-self: flex-start; background: var(--ink); color: #EFE7D3; border: none; padding: 8px 20px; font-family: inherit; font-size: 13px; letter-spacing: 1px; cursor: pointer; }
button:hover { background: var(--cinnabar); }
button:disabled { opacity: .5; cursor: default; }
.err { color: var(--cinnabar); font-size: 13px; }
.results-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
section h3 { font-size: 15px; letter-spacing: 2px; margin-bottom: 12px; }
.cnt { font-size: 12px; background: var(--cinnabar); color: #fff; border-radius: 10px; padding: 1px 7px; margin-left: 6px; }
.cap-row { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--line); background: rgba(255,255,255,.3); margin-bottom: 6px; font-size: 12px; }
.cap-id { font-family: var(--mono); font-size: 10px; color: var(--ink-soft); flex: 1; }
.score { color: var(--gamboge); font-family: var(--mono); font-size: 11px; }
.tag { display: inline-block; padding: 1px 7px; font-size: 11px; border-radius: 2px; }
.tag.cls { background: var(--mineral); color: #fff; }
.tag.mineral { background: var(--mineral); color: #fff; }
.tag.active, .tag.reinforced { background: var(--jade); color: #fff; }
.tag.candidate { background: var(--gamboge); color: var(--ink); }
.tag.quarantined, .tag.rejected { background: var(--cinnabar); color: #fff; }
.ec-card { border: 1px solid var(--line); background: rgba(255,255,255,.3); padding: 12px; margin-bottom: 10px; }
.ec-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.ec-id { font-family: var(--mono); font-size: 10px; color: var(--ink-soft); margin-left: auto; }
.ec-claim { font-size: 13px; color: var(--ink); margin-bottom: 6px; }
.ec-meta { font-size: 11px; color: var(--mineral); font-family: var(--mono); }
.ec-limit { font-size: 11px; color: var(--ink-soft); margin-top: 4px; }
@media (max-width: 860px) { .results-layout { grid-template-columns: 1fr; } }
</style>

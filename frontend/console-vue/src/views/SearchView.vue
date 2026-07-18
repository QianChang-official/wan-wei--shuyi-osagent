<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

const router = useRouter()

const q = ref('引用 规范')
const topK = ref(5)
const highRisk = ref(false)
const results = ref<any[]>([])
const evidenceCards = ref<any[]>([])
const loading = ref(false)
const err = ref('')

type TagTone = 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
const LIFECYCLE_TONE: Record<string, TagTone> = {
  active: 'bamboo', reinforced: 'bamboo', candidate: 'gold',
  quarantined: 'rouge', rejected: 'rouge', conflicted: 'gold',
  deprecated: 'ink', forgotten: 'ink',
}

async function doSearch() {
  loading.value = true; err.value = ''; results.value = []; evidenceCards.value = []
  try {
    const r = await api.search(q.value, topK.value, highRisk.value)
    results.value = r.results || []
    evidenceCards.value = r.evidence_cards || []
  } catch (e: any) { err.value = String(e) }
  loading.value = false
}

function openCapsule(id: string) {
  router.push({ path: '/capsules', query: { id } })
}
</script>

<template>
  <div>
    <PageHero
      seal="琅"
      title="琅嬛检索"
      en="Trusted Search"
      sub="可信检索 — 带治理过滤与证据卡的召回"
    />

    <GfCard seal="检" title="奉词" class="form-card">
      <div class="row">
        <div class="field-main">
          <label>查询词 q</label>
          <input v-model="q" @keyup.enter="doSearch" placeholder="输入检索词…" />
        </div>
        <div class="field-k">
          <label>top_k（返回数量）</label>
          <input v-model.number="topK" type="number" min="1" max="20" />
        </div>
        <div class="field-risk">
          <label>high_risk（高风险过滤）</label>
          <select v-model="highRisk"><option :value="false">否</option><option :value="true">是</option></select>
        </div>
      </div>
      <template #footer>
        <GfButton @click="doSearch" :disabled="loading">{{ loading ? '研墨寻卷中…' : '检索' }}</GfButton>
      </template>
    </GfCard>

    <div v-if="err" class="err">{{ err }}</div>

    <GfEmpty
      v-if="!loading && !err && !results.length && !evidenceCards.length"
      text="奉上一词，琅嬛为你寻卷"
    />

    <div v-if="results.length || evidenceCards.length" class="results-layout">
      <GfCard title="召回记忆" class="result-card">
        <template #header>
          <span class="rc-seal">忆</span>
          <h3 class="rc-title">召回记忆 <span class="cnt">{{ results.length }}</span></h3>
        </template>
        <div v-for="c in results" :key="c.capsule_id" class="cap-row">
          <GfTag tone="dai">{{ c.memory_class }}</GfTag>
          <GfTag :tone="LIFECYCLE_TONE[c.state?.lifecycle] || 'ink'">{{ c.state?.lifecycle }}</GfTag>
          <span class="cap-id">{{ c.capsule_id }}</span>
          <span class="score">得分 {{ (c.retrieval_score ?? 0).toFixed(3) }}</span>
        </div>
      </GfCard>

      <GfCard title="证据卡" class="result-card">
        <template #header>
          <span class="rc-seal">证</span>
          <h3 class="rc-title">证据卡 <span class="cnt">{{ evidenceCards.length }}</span></h3>
        </template>
        <div v-for="ec in evidenceCards" :key="ec.evidence_id" class="ec-card" @click="openCapsule(ec.capsule_id)">
          <div class="ec-head">
            <GfTag tone="dai">{{ ec.memory_class }}</GfTag>
            <GfTag tone="gold">{{ ec.used_for }}</GfTag>
            <span class="ec-id">{{ ec.evidence_id }}</span>
          </div>
          <div class="ec-claim">{{ ec.claim }}</div>
          <div class="ec-meta">trust={{ ec.trust_score }} · conf={{ ec.confidence }} · source={{ ec.source }}</div>
          <div class="ec-limit">{{ ec.limitations }}</div>
        </div>
      </GfCard>
    </div>
  </div>
</template>

<style scoped>
.form-card { margin-bottom: 22px; }
.row { display: flex; gap: 14px; align-items: flex-end; flex-wrap: wrap; }
.field-main { flex: 1; min-width: 200px; }
.field-k { width: 120px; }
.field-risk { width: 150px; }
label {
  display: block;
  font-size: 11px;
  letter-spacing: 1.5px;
  color: var(--ink-muted);
  margin-bottom: 5px;
}
input, select {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  padding: 8px 12px;
  background: var(--card);
  font-family: inherit;
  font-size: 13px;
  color: var(--ink);
  transition: border-color .18s ease, box-shadow .18s ease;
}
input:focus, select:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.err {
  color: var(--cinnabar);
  font-size: 13px;
  margin-bottom: 12px;
  padding: 10px 14px;
  border: 1px solid color-mix(in srgb, var(--cinnabar) 32%, transparent);
  background: color-mix(in srgb, var(--cinnabar) 7%, transparent);
  border-radius: var(--radius-small);
}
.results-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
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
.cap-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--card);
  margin-bottom: 8px;
  font-size: 12px;
  transition: background .18s ease, border-color .18s ease;
}
.cap-row:hover {
  background: color-mix(in srgb, var(--rouge) 8%, transparent);
  border-color: color-mix(in srgb, var(--rouge) 28%, transparent);
}
.cap-id { font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); flex: 1; }
.score { color: var(--gold); font-family: var(--font-mono); font-size: 11px; }
.ec-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  padding: 13px 14px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: border-color .18s ease, transform .18s ease, box-shadow .18s ease;
}
.ec-card:hover {
  border-color: var(--gold-line);
  transform: translateY(-2px);
  box-shadow: var(--shadow-lift);
}
.ec-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.ec-id { font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); margin-left: auto; }
.ec-claim { font-size: 13px; color: var(--ink); margin-bottom: 6px; line-height: 1.6; }
.ec-meta { font-size: 11px; color: var(--dai); font-family: var(--font-mono); }
.ec-limit { font-size: 11px; color: var(--ink-soft); margin-top: 5px; line-height: 1.5; }
@media (max-width: 860px) { .results-layout { grid-template-columns: 1fr; } }
</style>

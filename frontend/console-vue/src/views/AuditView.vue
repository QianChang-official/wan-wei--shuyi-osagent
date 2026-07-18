<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

const items = ref<any[]>([])
const loading = ref(false)
const err = ref('')
const traceId = ref('')

async function load() {
  loading.value = true
  err.value = ''
  try {
    const r = await api.auditLogs(50, traceId.value.trim())
    items.value = r.items || []
  } catch (e: any) {
    err.value = String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="hero-wrap">
      <PageHero
        seal="台"
        title="审计流水"
        en="Audit Trail"
        sub="运行时审计记录，默认最近 50 条；支持按 workflow trace_id 过滤"
      />
      <GfButton class="hero-act" variant="ghost" small @click="load">刷新</GfButton>
    </div>

    <div class="filter-row">
      <input v-model="traceId" placeholder="trace_id 过滤，例如 trace_xxx" @keyup.enter="load" />
      <GfButton variant="ghost" small @click="load">按 trace 过滤</GfButton>
      <GfButton variant="ghost" small @click="traceId=''; load()">清空</GfButton>
    </div>

    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="loading" class="loading">研墨中…</div>
    <GfEmpty v-else-if="!items.length" text="兰台尚无新墨 — 先写入 capsule 或运行一次 command loop" />

    <div v-else class="timeline">
      <article v-for="row in items" :key="row.audit_id" class="audit-card">
        <div class="left">
          <span class="stamp">台</span>
          <span class="line"></span>
        </div>
        <div class="body">
          <div class="head">
            <b>{{ row.action || row.event_type || 'audit_event' }}</b>
            <code>{{ row.audit_id }}</code>
          </div>
          <div class="time">{{ row.created_at }}</div>
          <pre>{{ JSON.stringify(row.payload ? JSON.parse(row.payload) : row, null, 2) }}</pre>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.hero-wrap { position: relative; }
.hero-act { position: absolute; top: 6px; right: 0; }
.filter-row { display: flex; gap: 10px; margin-bottom: 18px; align-items: center; }
.filter-row input {
  flex: 1;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 8px 12px;
  font-family: inherit;
  font-size: 13px;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.filter-row input:focus {
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
.loading {
  font-family: var(--font-kai);
  font-size: 14px;
  letter-spacing: 4px;
  color: var(--ink-muted);
  padding: 40px 0;
  text-align: center;
}
.timeline { display: flex; flex-direction: column; gap: 14px; }
.audit-card { display: grid; grid-template-columns: 42px 1fr; gap: 12px; }
.left { display: flex; flex-direction: column; align-items: center; }
.stamp {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  font-family: var(--font-kai);
  font-weight: 700;
  font-size: 14px;
  border: 1.5px solid var(--cinnabar);
  color: var(--cinnabar);
  border-radius: var(--radius-seal);
  background: var(--card-solid);
  box-shadow: 0 0 10px var(--rouge-glow);
  flex-shrink: 0;
}
.line {
  flex: 1;
  width: 1px;
  background: linear-gradient(180deg, var(--gold-line), transparent);
  margin-top: 8px;
}
.body {
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: var(--shadow-card);
  padding: 14px 16px;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.body:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lift);
  border-color: var(--gold-line);
}
.head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.head b {
  font-family: var(--font-kai);
  font-size: 15px;
  color: var(--cinnabar);
  letter-spacing: 2px;
}
.head code { font-family: var(--font-mono); font-size: 11px; color: var(--ink-muted); }
.time { font-size: 11px; color: var(--ink-muted); margin: 4px 0 9px; letter-spacing: 1px; }
pre {
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--bg-soft);
  padding: 11px 13px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-soft);
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.6;
  max-height: 220px;
  overflow: auto;
}
</style>

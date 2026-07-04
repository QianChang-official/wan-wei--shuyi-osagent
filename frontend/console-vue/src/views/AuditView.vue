<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'

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
    <div class="page-head">
      <h1>兰台鉴证 · 审计流水</h1>
      <p>运行时审计记录，默认最近 50 条；支持按 workflow trace_id 过滤。</p>
      <button class="refresh" @click="load">刷新</button>
    </div>

    <div class="filter-row">
      <input v-model="traceId" placeholder="trace_id 过滤，例如 trace_xxx" @keyup.enter="load" />
      <button @click="load">按 trace 过滤</button>
      <button @click="traceId=''; load()">清空</button>
    </div>

    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="loading" class="muted">加载中…</div>
    <div v-else-if="!items.length" class="empty">暂无审计记录。先写入 capsule 或运行 command loop。</div>

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
.page-head { margin-bottom: 22px; position: relative; }
.page-head h1 { font-size: 28px; letter-spacing: 3px; }
.page-head p { color: var(--ink-soft); font-size: 13px; margin-top: 4px; }
.refresh { position: absolute; right: 0; top: 0; border: 1px solid var(--line); background: transparent; padding: 7px 15px; color: var(--ink); }
.refresh:hover { border-color: var(--cinnabar); color: var(--cinnabar); }
.filter-row { display: flex; gap: 8px; margin-bottom: 16px; }
.filter-row input { flex: 1; border: 1px solid var(--line); background: rgba(255,255,255,.45); color: var(--ink); padding: 8px; }
.filter-row button { border: 1px solid var(--cinnabar); color: var(--cinnabar); background: rgba(178,58,46,.07); padding: 8px 12px; }
.err { color: var(--cinnabar); font-size: 13px; }
.muted,.empty { color: var(--ink-soft); font-size: 13px; }
.timeline { display: flex; flex-direction: column; gap: 12px; }
.audit-card { display: grid; grid-template-columns: 42px 1fr; gap: 12px; }
.left { display: flex; flex-direction: column; align-items: center; }
.stamp { width: 30px; height: 30px; display: grid; place-items: center; border: 2px solid var(--cinnabar); color: var(--cinnabar); border-radius: 4px; font-weight: 700; }
.line { flex: 1; width: 1px; background: var(--line); margin-top: 6px; }
.body { border: 1px solid var(--line); background: rgba(255,255,255,.35); padding: 13px 15px; }
.head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.head b { color: var(--cinnabar); letter-spacing: 1px; }
.head code { font-family: var(--mono); font-size: 11px; color: var(--ink-soft); }
.time { font-size: 11px; color: var(--ink-soft); margin: 4px 0 8px; }
pre { border: 1px solid var(--line); background: rgba(28,26,23,.04); padding: 10px; font-family: var(--mono); font-size: 11px; white-space: pre-wrap; word-break: break-all; max-height: 220px; overflow: auto; }
</style>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import CapsuleDetail from '@/components/CapsuleDetail.vue'

const route = useRoute()

const items = ref<any[]>([])
const selected = ref<any | null>(null)
const loading = ref(true)
const err = ref('')

const LIFECYCLE_COLOR: Record<string,string> = {
  active: 'var(--mineral)', reinforced: 'var(--pine)', candidate: 'var(--gamboge)',
  quarantined: 'var(--cinnabar)', rejected: 'var(--cinnabar)', deprecated: 'var(--ink-soft)',
  forgotten: 'var(--ink-soft)', conflicted: 'var(--gamboge)',
}

async function load() {
  loading.value = true; err.value = ''
  try {
    const r = await api.listCapsules(50)
    items.value = r.items || []
    const id = typeof route.query.id === 'string' ? route.query.id : ''
    if (id) await open(id)
  } catch (e: any) { err.value = String(e) }
  loading.value = false
}
async function open(id: string) {
  try { selected.value = await api.getCapsule(id) } catch (e: any) { err.value = String(e) }
}
onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <h1>枢忆核 · 记忆容器</h1>
      <p>MemoryCapsule 2.0 浏览器 — 点击查看 governance / state / provenance</p>
      <button class="btn-ghost" @click="load">刷新</button>
    </div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="loading" class="muted">加载中…</div>
    <div v-else-if="!items.length" class="muted">暂无记忆容器。去「命令回路」或「写入」创建。</div>
    <div class="cap-layout" v-else>
      <ul class="cap-list">
        <li v-for="c in items" :key="c.capsule_id" @click="open(c.capsule_id)"
            :class="{ sel: selected?.capsule_id === c.capsule_id }">
          <span class="cap-class">{{ c.memory_class }}</span>
          <span class="cap-dot" :style="{ background: LIFECYCLE_COLOR[c.state?.lifecycle] || 'var(--ink-soft)' }"></span>
          <span class="cap-life">{{ c.state?.lifecycle }}</span>
          <span class="cap-id">{{ c.capsule_id }}</span>
        </li>
      </ul>
      <CapsuleDetail :capsule="selected" />
    </div>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 20px; position: relative; }
.page-head h1 { font-size: 28px; font-weight: 700; letter-spacing: 3px; }
.page-head p { font-size: 13px; color: var(--ink-soft); margin-top: 4px; }
.btn-ghost { position: absolute; top: 2px; right: 0; border: 1px solid var(--line); background: transparent; padding: 6px 14px; cursor: pointer; font-family: inherit; color: var(--ink); }
.btn-ghost:hover { border-color: var(--cinnabar); color: var(--cinnabar); }
.err { color: var(--cinnabar); font-size: 13px; margin-bottom: 10px; }
.muted { color: var(--ink-soft); font-size: 13px; }
.cap-layout { display: grid; grid-template-columns: 340px 1fr; gap: 18px; }
.cap-list { border: 1px solid var(--line); background: rgba(255,255,255,.3); max-height: 62vh; overflow-y: auto; }
.cap-list li { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--line); cursor: pointer; font-size: 12px; }
.cap-list li:hover { background: rgba(178,58,46,.06); }
.cap-list li.sel { background: rgba(178,58,46,.1); border-left: 3px solid var(--cinnabar); }
.cap-class { font-weight: 700; color: var(--mineral); min-width: 74px; }
.cap-dot { width: 8px; height: 8px; border-radius: 50%; }
.cap-life { color: var(--ink-soft); min-width: 72px; }
.cap-id { font-family: var(--mono); font-size: 10px; color: var(--ink-soft); margin-left: auto; }
@media (max-width: 900px) { .cap-layout { grid-template-columns: 1fr; } }
</style>

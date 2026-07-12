<script setup lang="ts">
defineProps<{ capsule: any | null }>()
</script>
<template>
  <div class="detail">
    <div v-if="!capsule" class="empty">← 选择一个记忆容器查看详情</div>
    <template v-else>
      <div class="d-head">
        <span class="d-class">{{ capsule.memory_class }}</span>
        <span class="d-id">{{ capsule.capsule_id }}</span>
      </div>
      <section>
        <h4>内容</h4>
        <pre>{{ JSON.stringify(capsule.content, null, 2) }}</pre>
      </section>
      <div class="d-grid">
        <section>
          <h4>治理</h4>
          <pre>{{ JSON.stringify(capsule.governance, null, 2) }}</pre>
        </section>
        <section>
          <h4>状态</h4>
          <pre>{{ JSON.stringify(capsule.state, null, 2) }}</pre>
        </section>
      </div>
      <section>
        <h4>来源</h4>
        <pre>{{ JSON.stringify(capsule.provenance, null, 2) }}</pre>
      </section>
    </template>
  </div>
</template>
<style scoped>
.detail { border: 1px solid var(--line); background: rgba(255,255,255,.3); padding: 16px; max-height: 62vh; overflow-y: auto; }
.empty { color: var(--ink-soft); font-size: 13px; padding: 40px 0; text-align: center; }
.d-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--line); }
.d-class { font-weight: 700; color: var(--cinnabar); letter-spacing: 1px; }
.d-id { font-family: var(--mono); font-size: 11px; color: var(--ink-soft); }
section { margin-bottom: 12px; }
h4 { font-size: 12px; color: var(--mineral); font-family: var(--mono); margin-bottom: 5px; }
pre { background: rgba(28,26,23,.04); border: 1px solid var(--line); padding: 10px; font-size: 11.5px; font-family: var(--mono); white-space: pre-wrap; word-break: break-all; line-height: 1.5; }
.d-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 700px) { .d-grid { grid-template-columns: 1fr; } }
</style>

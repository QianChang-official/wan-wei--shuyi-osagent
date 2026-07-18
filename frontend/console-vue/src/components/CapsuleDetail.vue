<script setup lang="ts">
import GfEmpty from '@/components/gf/GfEmpty.vue'

defineProps<{ capsule: any | null }>()
</script>
<template>
  <div class="letter">
    <GfEmpty v-if="!capsule" text="选一函记忆，展读其笺" />
    <template v-else>
      <div class="d-head">
        <div class="d-head-main">
          <span class="d-class">{{ capsule.memory_class }}</span>
          <span class="d-id">{{ capsule.capsule_id }}</span>
        </div>
        <span class="d-seal">忆</span>
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
      <div class="d-tail" aria-hidden="true">枢忆核 · 花朝藏笺</div>
    </template>
  </div>
</template>
<style scoped>
/* 花笺信札：宣纸素底 + 金线描边 + 胭脂光晕 */
.letter {
  background: var(--card-solid);
  border: 1px solid var(--gold-line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: 20px 22px;
  max-height: 62vh;
  overflow-y: auto;
  position: relative;
}
.letter::before {
  content: '';
  position: absolute;
  top: 0; left: 24px; right: 24px;
  height: 3px;
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, var(--gold-line) 25%, var(--rouge-glow) 55%, var(--gold-line) 78%, transparent);
}
.d-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line-soft);
}
.d-head-main { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.d-class {
  font-family: var(--font-kai);
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 3px;
  color: var(--cinnabar);
}
.d-id { font-family: var(--font-mono); font-size: 11px; color: var(--ink-muted); }
.d-seal {
  margin-left: auto;
  font-family: var(--font-kai);
  font-size: 13px;
  font-weight: 700;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: var(--shadow-seal);
  flex-shrink: 0;
}
section { margin-bottom: 14px; }
h4 {
  font-family: var(--font-kai);
  font-size: 15px;
  letter-spacing: 3px;
  color: var(--dai);
  margin-bottom: 7px;
  display: flex;
  align-items: center;
  gap: 8px;
}
h4::before {
  content: '';
  width: 6px;
  height: 6px;
  background: var(--gold);
  transform: rotate(45deg);
  border-radius: 1px;
  flex-shrink: 0;
}
pre {
  background: var(--bg-soft);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  padding: 12px 14px;
  font-size: 11.5px;
  font-family: var(--font-mono);
  color: var(--ink-soft);
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.6;
}
.d-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.d-tail {
  margin-top: 18px;
  text-align: right;
  font-family: var(--font-kai);
  font-size: 11px;
  letter-spacing: 3px;
  color: var(--ink-muted);
}
@media (max-width: 700px) { .d-grid { grid-template-columns: 1fr; } }
</style>

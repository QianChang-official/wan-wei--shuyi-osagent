<script setup lang="ts">
/** GfStat — 大数字统计卡：楷体数字 + 标签 + 可选色调与提示 */
withDefaults(defineProps<{
  label: string
  value: string | number
  tone?: 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
  hint?: string
}>(), { tone: 'ink', hint: '' })
</script>

<template>
  <div class="gf-stat" :data-tone="tone">
    <div class="gs-label">{{ label }}</div>
    <div class="gs-value">{{ value }}</div>
    <div v-if="hint" class="gs-hint">{{ hint }}</div>
    <div class="gs-petal" aria-hidden="true">
      <svg viewBox="0 0 16 16" width="22" height="22">
        <g fill="currentColor" opacity=".28">
          <circle cx="8" cy="3.2" r="2.4" /><circle cx="12.6" cy="6.5" r="2.4" />
          <circle cx="11" cy="11.8" r="2.4" /><circle cx="5" cy="11.8" r="2.4" />
          <circle cx="3.4" cy="6.5" r="2.4" />
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.gf-stat {
  position: relative;
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: 16px 18px;
  overflow: hidden;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.gf-stat:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lift);
  border-color: var(--gold-line);
}
.gs-label {
  font-size: 11px;
  letter-spacing: 2px;
  color: var(--ink-muted);
  margin-bottom: 6px;
}
.gs-value {
  font-family: var(--font-kai);
  font-size: 32px;
  font-weight: 700;
  letter-spacing: 2px;
  line-height: 1.1;
  color: var(--ink);
}
.gf-stat[data-tone='rouge'] .gs-value { color: var(--rouge); }
.gf-stat[data-tone='dai'] .gs-value { color: var(--dai); }
.gf-stat[data-tone='bamboo'] .gs-value { color: var(--bamboo); }
.gf-stat[data-tone='gold'] .gs-value { color: var(--gold); }
.gs-hint {
  margin-top: 6px;
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--ink-muted);
}
.gs-petal {
  position: absolute;
  right: 10px;
  top: 10px;
  color: var(--rouge);
  pointer-events: none;
}
.gf-stat[data-tone='dai'] .gs-petal { color: var(--dai); }
.gf-stat[data-tone='bamboo'] .gs-petal { color: var(--bamboo); }
.gf-stat[data-tone='gold'] .gs-petal { color: var(--gold); }
</style>

<script setup lang="ts">
/** GfEmpty — 空状态：小月亮 SVG + 文案 */
defineProps<{ text: string }>()
</script>

<template>
  <div class="gf-empty">
    <svg class="ge-moon" viewBox="0 0 72 72" width="64" height="64" aria-hidden="true">
      <!-- 月洞门圆环 -->
      <circle cx="36" cy="36" r="26" fill="none" stroke="var(--gold-line)" stroke-width="1.5" />
      <circle cx="36" cy="36" r="26" fill="var(--rouge-glow)" opacity=".18" />
      <!-- 月牙 -->
      <path d="M45 24 A15 15 0 1 0 45 48 A12 12 0 1 1 45 24 Z" fill="var(--gold)" opacity=".8" />
      <!-- 梅 -->
      <g fill="var(--rouge)" opacity=".85">
        <circle cx="50" cy="42" r="2" /><circle cx="53.5" cy="44.6" r="2" />
        <circle cx="52.2" cy="48.6" r="2" /><circle cx="47.4" cy="48.6" r="2" />
        <circle cx="46.1" cy="44.6" r="2" />
      </g>
      <circle cx="49.8" cy="45.6" r="1.2" fill="var(--gold)" />
    </svg>
    <p class="ge-text">{{ text }}</p>
  </div>
</template>

<style scoped>
.gf-empty {
  display: grid;
  place-items: center;
  gap: 14px;
  padding: 48px 24px;
}
.ge-moon { filter: drop-shadow(0 0 10px var(--rouge-glow)); }
.ge-text {
  font-family: var(--font-kai);
  font-size: 14px;
  letter-spacing: 3px;
  color: var(--ink-muted);
  text-align: center;
}
</style>

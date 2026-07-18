<script setup lang="ts">
/** ThemeToggle — 昼/夜切换：写 <html data-theme> 并持久化 localStorage:gf-theme，默认 day */
import { onMounted, ref } from 'vue'
import { applyTheme, getTheme, type GfTheme } from './shared'

const theme = ref<GfTheme>('day')

function toggle() {
  theme.value = theme.value === 'day' ? 'night' : 'day'
  applyTheme(theme.value)
}

onMounted(() => {
  theme.value = getTheme()
  applyTheme(theme.value)
})
</script>

<template>
  <button
    class="theme-toggle"
    type="button"
    :aria-label="theme === 'day' ? '切换为夜间模式' : '切换为日间模式'"
    :title="theme === 'day' ? '入夜 · 靛青灯影' : '天明 · 宣纸白昼'"
    @click="toggle"
  >
    <!-- 日 -->
    <svg v-if="theme === 'day'" viewBox="0 0 24 24" width="16" height="16" fill="none"
      stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
      <circle cx="12" cy="12" r="4.2" fill="currentColor" stroke="none" opacity=".9" />
      <path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5 5l1.7 1.7M17.3 17.3L19 19M19 5l-1.7 1.7M6.7 17.3L5 19" />
    </svg>
    <!-- 月 -->
    <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none"
      stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M20 13.2A8.4 8.4 0 0 1 10.8 4 8.4 8.4 0 1 0 20 13.2Z" fill="currentColor" opacity=".9" stroke="none" />
      <path d="M17.5 4.5l.5 1.4 1.4.5-1.4.5-.5 1.4-.5-1.4-1.4-.5 1.4-.5.5-1.4Z" fill="currentColor" stroke="none" />
    </svg>
  </button>
</template>

<style scoped>
.theme-toggle {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  border: 1px solid var(--gold-line);
  background: var(--card);
  color: var(--gold);
  transition: transform .2s ease, box-shadow .2s ease, color .2s ease;
}
.theme-toggle:hover {
  transform: translateY(-2px) rotate(12deg);
  box-shadow: var(--shadow-glow-rouge);
  color: var(--rouge);
}
</style>

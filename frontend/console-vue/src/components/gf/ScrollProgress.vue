<script setup lang="ts">
/** ScrollProgress — 顶部 3px 阅读进度条：朱砂→胭脂渐变，右端一点梅花 */
import { onMounted, onUnmounted, ref } from 'vue'

const progress = ref(0)

function update() {
  const el = document.documentElement
  const max = el.scrollHeight - el.clientHeight
  progress.value = max > 0 ? Math.min(1, Math.max(0, el.scrollTop / max)) : 0
}

onMounted(() => {
  update()
  window.addEventListener('scroll', update, { passive: true })
  window.addEventListener('resize', update, { passive: true })
})
onUnmounted(() => {
  window.removeEventListener('scroll', update)
  window.removeEventListener('resize', update)
})
</script>

<template>
  <div class="scroll-progress" aria-hidden="true">
    <div class="sp-bar" :style="{ width: `${progress * 100}%` }">
      <span v-if="progress > 0.01" class="sp-dot">
        <svg viewBox="0 0 16 16" width="12" height="12">
          <g fill="var(--rouge)">
            <circle cx="8" cy="3.2" r="2.4" />
            <circle cx="12.6" cy="6.5" r="2.4" />
            <circle cx="11" cy="11.8" r="2.4" />
            <circle cx="5" cy="11.8" r="2.4" />
            <circle cx="3.4" cy="6.5" r="2.4" />
          </g>
          <circle cx="8" cy="8" r="1.6" fill="var(--gold)" />
        </svg>
      </span>
    </div>
  </div>
</template>

<style scoped>
.scroll-progress {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  z-index: 60;
  pointer-events: none;
  background: var(--line-soft);
}
.sp-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--cinnabar), var(--rouge));
  border-radius: 0 999px 999px 0;
  transition: width .12s linear;
  position: relative;
}
.sp-dot {
  position: absolute;
  right: -6px;
  top: 50%;
  transform: translateY(-50%);
  display: grid;
  place-items: center;
  filter: drop-shadow(0 0 4px var(--rouge-glow));
}
</style>

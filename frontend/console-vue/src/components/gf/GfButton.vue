<script setup lang="ts">
/** GfButton — primary=朱砂渐变+胭脂光晕；ghost=描边；danger=深朱 */
withDefaults(defineProps<{
  variant?: 'primary' | 'ghost' | 'danger'
  small?: boolean
}>(), { variant: 'primary', small: false })
</script>

<template>
  <button class="gf-btn" :data-variant="variant" :class="{ 'gf-btn--small': small }" type="button">
    <slot />
  </button>
</template>

<style scoped>
.gf-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 20px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 13px;
  letter-spacing: 2px;
  font-family: var(--font-kai);
  transition: transform .18s ease, box-shadow .18s ease, background .18s ease, color .18s ease, border-color .18s ease;
}
.gf-btn:active { transform: translateY(1px) scale(.98); }

.gf-btn[data-variant='primary'] {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: 0 2px 12px var(--cinnabar-glow), var(--shadow-card);
}
.gf-btn[data-variant='primary']:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 18px var(--cinnabar-glow), var(--shadow-glow-rouge);
}

.gf-btn[data-variant='ghost'] {
  background: var(--card);
  border-color: var(--gold-line);
  color: var(--ink-soft);
}
.gf-btn[data-variant='ghost']:hover {
  transform: translateY(-2px);
  border-color: var(--rouge);
  color: var(--cinnabar);
  box-shadow: var(--shadow-glow-rouge);
}

.gf-btn[data-variant='danger'] {
  background: transparent;
  border-color: color-mix(in srgb, var(--cinnabar) 55%, transparent);
  color: var(--cinnabar);
}
.gf-btn[data-variant='danger']:hover {
  transform: translateY(-2px);
  background: color-mix(in srgb, var(--cinnabar) 10%, transparent);
  box-shadow: 0 2px 14px var(--cinnabar-glow);
}

.gf-btn--small {
  padding: 4px 14px;
  font-size: 12px;
  letter-spacing: 1px;
}
.gf-btn:disabled {
  opacity: .55;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}
</style>

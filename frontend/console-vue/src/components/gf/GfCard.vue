<script setup lang="ts">
/** GfCard — 宣纸圆角卡片：半透 + blur(8px) + 淡线描边，hover 上浮 */
withDefaults(defineProps<{
  title?: string
  seal?: string
  pad?: boolean
}>(), { title: '', seal: '', pad: true })
</script>

<template>
  <section class="gf-card" :class="{ 'gf-card--nopad': !pad }">
    <header v-if="title || seal || $slots.header" class="gf-card-hd">
      <slot name="header">
        <span v-if="seal" class="gf-card-seal">{{ seal }}</span>
        <h3 v-if="title" class="gf-card-title">{{ title }}</h3>
      </slot>
    </header>
    <div class="gf-card-bd">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="gf-card-ft">
      <slot name="footer" />
    </footer>
  </section>
</template>

<style scoped>
.gf-card {
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  overflow: hidden;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.gf-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lift);
  border-color: var(--gold-line);
}
.gf-card-hd {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px 10px;
  border-bottom: 1px solid var(--line-soft);
}
.gf-card-seal {
  font-family: var(--font-kai);
  font-size: 13px;
  font-weight: 700;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: 0 0 10px var(--cinnabar-glow);
  flex-shrink: 0;
}
.gf-card-title {
  font-family: var(--font-kai);
  font-size: 20px;
  letter-spacing: 3px;
  color: var(--ink);
  font-weight: 700;
}
.gf-card-bd { padding: 16px 18px; }
.gf-card--nopad .gf-card-bd { padding: 0; }
.gf-card-hd + .gf-card-bd { padding-top: 14px; }
.gf-card-ft {
  padding: 12px 18px;
  border-top: 1px solid var(--line-soft);
  background: var(--line-soft);
}
</style>

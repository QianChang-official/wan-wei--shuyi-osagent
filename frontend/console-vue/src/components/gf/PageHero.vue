<script setup lang="ts">
/** PageHero — 每页页眉：印章 + 书法大标题 + 英文小字 + 副标题 + 梅枝 SVG 分隔线 */
withDefaults(defineProps<{
  seal: string
  title: string
  en: string
  sub?: string
}>(), { sub: '' })
</script>

<template>
  <header class="page-hero">
    <div class="ph-row">
      <span class="ph-seal">{{ seal }}</span>
      <div class="ph-main">
        <h1 class="ph-title">{{ title }}</h1>
        <div class="ph-en">{{ en }}</div>
      </div>
      <p v-if="sub" class="ph-sub">{{ sub }}</p>
    </div>
    <!-- 梅枝分隔线 -->
    <div class="ph-branch" aria-hidden="true">
      <svg viewBox="0 0 640 36" width="100%" height="36" preserveAspectRatio="xMidYMid meet">
        <!-- 金线 -->
        <line x1="0" y1="20" x2="252" y2="20" class="br-line" />
        <line x1="388" y1="20" x2="640" y2="20" class="br-line" />
        <!-- 梅枝 -->
        <path d="M258 24 Q 286 12 314 17 T 382 10" class="br-twig" fill="none" />
        <path d="M316 17 Q 330 22 344 21" class="br-twig" fill="none" />
        <!-- 花 -->
        <g class="br-blossom">
          <circle cx="300" cy="12.5" r="2.6" /><circle cx="304.8" cy="16.6" r="2.6" />
          <circle cx="302.6" cy="22.6" r="2.6" /><circle cx="295.4" cy="22.6" r="2.6" />
          <circle cx="293.2" cy="16.6" r="2.6" /><circle cx="299" cy="17.8" r="1.5" class="br-heart" />
        </g>
        <g class="br-blossom br-blossom--soft">
          <circle cx="352" cy="15" r="2.2" /><circle cx="356" cy="18.4" r="2.2" />
          <circle cx="354.2" cy="23.4" r="2.2" /><circle cx="348.2" cy="23.4" r="2.2" />
          <circle cx="346.4" cy="18.4" r="2.2" /><circle cx="351.2" cy="19.4" r="1.3" class="br-heart" />
        </g>
        <circle cx="376" cy="9" r="2" class="br-bud" />
        <circle cx="268" cy="22" r="1.8" class="br-bud" />
      </svg>
    </div>
  </header>
</template>

<style scoped>
.page-hero { margin-bottom: 22px; }
.ph-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.ph-seal {
  font-family: var(--font-kai);
  font-size: 22px;
  font-weight: 700;
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: var(--shadow-seal);
  position: relative;
  flex-shrink: 0;
}
.ph-seal::before {
  content: '';
  position: absolute;
  inset: 3px;
  border: 1px solid rgba(253, 246, 233, .35);
  border-radius: 4px;
}
.ph-main { display: flex; flex-direction: column; gap: 2px; }
.ph-title {
  font-family: var(--font-kai);
  font-size: 38px;
  font-weight: 700;
  letter-spacing: 8px;
  color: var(--ink);
  line-height: 1.15;
}
.ph-en {
  font-size: 11px;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: var(--ink-muted);
  font-family: var(--font-mono);
}
.ph-sub {
  margin-left: auto;
  font-family: var(--font-kai);
  font-size: 13px;
  letter-spacing: 2px;
  color: var(--ink-soft);
  max-width: 46%;
  text-align: right;
  line-height: 1.7;
}
.ph-branch { margin-top: 10px; }
.br-line { stroke: var(--gold-line); stroke-width: 1; }
.br-twig { stroke: var(--gold); stroke-width: 1.4; stroke-linecap: round; opacity: .75; }
.br-blossom circle { fill: var(--rouge); opacity: .85; }
.br-blossom--soft circle { fill: var(--rouge); opacity: .55; }
.br-blossom .br-heart { fill: var(--gold); opacity: .9; }
.br-bud { fill: var(--rouge); opacity: .5; }

@media (max-width: 720px) {
  .ph-title { font-size: 28px; letter-spacing: 5px; }
  .ph-sub { max-width: 100%; margin-left: 0; text-align: left; }
}
</style>

<script setup lang="ts">
/** 404 兜底视图（09-#9）：未注册路径不再渲染空白内容区，给出明确引导。 */
import { useRoute } from 'vue-router'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfButton from '@/components/gf/GfButton.vue'

const route = useRoute()
</script>

<template>
  <div>
    <PageHero
      seal="迷"
      title="迷途知返"
      en="PAGE NOT FOUND"
      sub="你要找的页面不存在，或路径已变更。"
    />

    <GfCard title="何去何从" seal="引" class="nf-card">
      <p class="nf-path">
        未匹配的路径：<code>{{ route.fullPath }}</code>
      </p>
      <p class="nf-hint">请从左侧屏风导航进入各舱室，或回到总览重新开始。</p>
      <div class="nf-actions">
        <RouterLink to="/">
          <GfButton small>回总览</GfButton>
        </RouterLink>
        <RouterLink to="/platform/workbench">
          <GfButton variant="ghost" small>去万枢工作台</GfButton>
        </RouterLink>
      </div>
    </GfCard>
  </div>
</template>

<style scoped>
.nf-card { max-width: 640px; }
.nf-path {
  font-size: 13px;
  color: var(--ink-soft);
  letter-spacing: 1px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}
.nf-path code {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--cinnabar-deep);
}
.nf-hint {
  margin-top: 10px;
  font-size: 12px;
  letter-spacing: 1px;
  line-height: 1.8;
  color: var(--ink-muted);
}
.nf-actions {
  margin-top: 16px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.nf-actions a { text-decoration: none; }
</style>

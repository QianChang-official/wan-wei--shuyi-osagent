<script setup lang="ts">
/** GfTag — 全圆角色粉小标签 */
withDefaults(defineProps<{
  tone?: 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'
}>(), { tone: 'rouge' })
</script>

<template>
  <span class="gf-tag" :data-tone="tone"><slot /></span>
</template>

<style scoped>
.gf-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  letter-spacing: 1px;
  line-height: 1.7;
  border: 1px solid transparent;
  white-space: nowrap;
}
.gf-tag[data-tone='rouge'] {
  background: color-mix(in srgb, var(--rouge) 14%, transparent);
  border-color: color-mix(in srgb, var(--rouge) 32%, transparent);
  color: color-mix(in srgb, var(--rouge) 72%, var(--ink));
}
.gf-tag[data-tone='dai'] {
  background: color-mix(in srgb, var(--dai) 13%, transparent);
  border-color: color-mix(in srgb, var(--dai) 30%, transparent);
  color: color-mix(in srgb, var(--dai) 76%, var(--ink));
}
.gf-tag[data-tone='bamboo'] {
  background: color-mix(in srgb, var(--bamboo) 15%, transparent);
  border-color: color-mix(in srgb, var(--bamboo) 34%, transparent);
  color: color-mix(in srgb, var(--bamboo) 62%, var(--ink));
}
.gf-tag[data-tone='gold'] {
  background: color-mix(in srgb, var(--gold) 15%, transparent);
  border-color: color-mix(in srgb, var(--gold) 36%, transparent);
  color: color-mix(in srgb, var(--gold) 66%, var(--ink));
}
.gf-tag[data-tone='ink'] {
  background: var(--line-soft);
  border-color: var(--line);
  color: var(--ink-soft);
}
</style>

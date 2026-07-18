<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import { api, type RegistrySkill, type RegistryTool } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

const tools = shallowRef<RegistryTool[]>([])
const skills = shallowRef<RegistrySkill[]>([])
const error = shallowRef('')
const loaded = shallowRef(false)

onMounted(async () => {
  try {
    const [toolRes, skillRes] = await Promise.all([api.registryTools(), api.registrySkills()])
    tools.value = toolRes.items
    skills.value = skillRes.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loaded.value = true
  }
})
</script>

<template>
  <div>
    <PageHero
      seal="工"
      title="百工技能舱"
      en="SKILLS REGISTRY"
      sub="MCP 服务器 · 技能注册表 · 工具权限 · 结构化结果入库"
    />
    <div v-if="error" class="notice error" role="alert">{{ error }}</div>

    <div class="matrix">
      <GfCard title="工具注册表" seal="具">
        <div v-if="!loaded" class="muted">研墨中…</div>
        <GfEmpty v-else-if="!tools.length" text="暂无工具登记" />
        <div v-for="tool in tools" :key="tool.id" class="row-card">
          <div class="row-top"><b>{{ tool.name_cn }}</b><GfTag tone="rouge">{{ tool.status }}</GfTag></div>
          <div class="meta">{{ tool.kind }} / {{ tool.permission_mode }} / {{ tool.sandbox }}</div>
          <p>{{ tool.description }}</p>
          <code>result_storage={{ tool.result_storage }}</code>
        </div>
      </GfCard>
      <GfCard title="技能注册表" seal="技">
        <div v-if="!loaded" class="muted">研墨中…</div>
        <GfEmpty v-else-if="!skills.length" text="暂无技能登记" />
        <div v-for="skill in skills" :key="skill.id" class="row-card row-card--skill">
          <div class="row-top"><b>{{ skill.name_cn }}</b><GfTag tone="gold">{{ skill.status }}</GfTag></div>
          <div class="meta">{{ skill.scope }}</div>
          <p>{{ skill.description }}</p>
          <code>{{ skill.entrypoint }}</code>
        </div>
      </GfCard>
    </div>
  </div>
</template>

<style scoped>
.notice {
  margin: 0 0 18px;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  font-size: 12px;
}
.notice.error {
  color: var(--cinnabar-deep);
  border-color: var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 7%, transparent);
}
.muted { color: var(--ink-soft); font-size: 13px; padding: 14px 0; font-family: var(--font-kai); letter-spacing: 2px; }

.matrix { display: grid; grid-template-columns: 1.35fr 1fr; gap: 20px; align-items: start; }

.row-card {
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-card);
  background: var(--card);
  box-shadow: var(--shadow-card);
  padding: 14px;
  margin-bottom: 12px;
  border-top: 2px solid color-mix(in srgb, var(--rouge) 45%, transparent);
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.row-card:last-child { margin-bottom: 0; }
.row-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lift); border-color: var(--gold-line); }
.row-card--skill { border-top-color: color-mix(in srgb, var(--gold) 55%, transparent); }
.row-top { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
.row-top b { font-family: var(--font-kai); font-size: 16px; letter-spacing: 2px; color: var(--ink); }
.meta { margin: 8px 0; font-family: var(--font-mono); font-size: 11px; color: var(--gold); }
p { font-size: 12.5px; line-height: 1.65; color: var(--ink-soft); }
code { display: inline-block; margin-top: 9px; font-family: var(--font-mono); font-size: 11px; color: var(--dai); word-break: break-all; }

@media (max-width: 850px) { .matrix { grid-template-columns: 1fr; } }
</style>

<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import { api, type RegistrySkill, type RegistryTool } from '@/api/client'

const tools = shallowRef<RegistryTool[]>([])
const skills = shallowRef<RegistrySkill[]>([])
const error = shallowRef('')

onMounted(async () => {
  try {
    const [toolRes, skillRes] = await Promise.all([api.registryTools(), api.registrySkills()])
    tools.value = toolRes.items
    skills.value = skillRes.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})
</script>

<template>
  <div>
    <div class="page-head">
      <h1>百工技能舱</h1>
      <p>MCP servers · Skills registry · 工具权限 · 结构化结果入库</p>
    </div>
    <div v-if="error" class="muted">{{ error }}</div>

    <section class="matrix">
      <article>
        <div class="section-title">工具注册表</div>
        <div v-for="tool in tools" :key="tool.id" class="row-card">
          <div class="row-top"><b>{{ tool.name_cn }}</b><span>{{ tool.status }}</span></div>
          <div class="meta">{{ tool.kind }} / {{ tool.permission_mode }} / {{ tool.sandbox }}</div>
          <p>{{ tool.description }}</p>
          <code>result_storage={{ tool.result_storage }}</code>
        </div>
      </article>
      <article>
        <div class="section-title">技能注册表</div>
        <div v-for="skill in skills" :key="skill.id" class="row-card skill">
          <div class="row-top"><b>{{ skill.name_cn }}</b><span>{{ skill.status }}</span></div>
          <div class="meta">{{ skill.scope }}</div>
          <p>{{ skill.description }}</p>
          <code>{{ skill.entrypoint }}</code>
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 24px; }
.page-head h1 { font-size: 28px; letter-spacing: 3px; }
.page-head p, .muted { color: var(--ink-soft); font-size: 13px; margin-top: 5px; }
.matrix { display: grid; grid-template-columns: 1.35fr 1fr; gap: 18px; }
.matrix > article { border: 1px solid var(--line); background: rgba(255,255,255,.28); padding: 16px; }
.section-title { border-left: 4px solid var(--cinnabar); padding-left: 10px; margin-bottom: 12px; font-size: 16px; font-weight: 700; letter-spacing: 2px; }
.row-card { border: 1px solid var(--line-soft); background: rgba(255,255,255,.36); padding: 13px; margin-bottom: 12px; border-top: 3px solid var(--mineral); }
.row-card.skill { border-top-color: var(--gamboge); }
.row-top { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
.row-top b { font-size: 15px; letter-spacing: 1px; }
.row-top span { font-size: 10px; border: 1px solid currentColor; padding: 2px 6px; color: var(--cinnabar); }
.meta { margin: 8px 0; font-family: var(--mono); font-size: 11px; color: var(--gamboge); }
p { font-size: 12.5px; line-height: 1.55; color: var(--ink-soft); }
code { display: inline-block; margin-top: 9px; font-size: 11px; color: var(--mineral); word-break: break-all; }
@media (max-width: 850px) { .matrix { grid-template-columns: 1fr; } }
</style>

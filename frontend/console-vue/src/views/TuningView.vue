<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { api } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

const defaults = shallowRef<Record<string, Record<string, unknown>>>({})
const policies = shallowRef<any[]>([])
const error = shallowRef('')
const loaded = shallowRef(false)
const groups = computed(() => Object.entries(defaults.value))

onMounted(async () => {
  try {
    const [defaultRes, policyRes] = await Promise.all([api.tuningDefaults(), api.tuningPolicies()])
    defaults.value = defaultRes.defaults
    policies.value = policyRes.items
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
      seal="南"
      title="司南调参舱"
      en="TUNING COMPASS"
      sub="top_k · trust_threshold · 控制链路延迟口径 · 模型生成延迟分离展示"
    />
    <div v-if="error" class="notice error" role="alert">{{ error }}</div>

    <div v-if="!loaded && !error" class="muted">研墨中…</div>
    <GfEmpty v-else-if="!groups.length && !error" text="暂无调参默认值" />

    <div class="tuning-grid">
      <GfCard v-for="[group, values] in groups" :key="group" :title="group">
        <div v-for="[key, value] in Object.entries(values)" :key="key" class="dial-row">
          <span>{{ key }}</span>
          <b>{{ value }}</b>
        </div>
      </GfCard>
    </div>

    <GfCard title="权限/执行模式" seal="式" class="policy-modes">
      <GfEmpty v-if="loaded && !policies.length && !error" text="暂无权限/执行模式" />
      <div class="mode-grid">
        <article v-for="mode in policies" :key="mode.id" class="mode-card" :class="mode.status">
          <div class="mode-top">
            <h2>{{ mode.name_cn }}</h2>
            <GfTag :tone="mode.status === 'available' ? 'bamboo' : mode.status === 'partial' ? 'gold' : 'ink'">{{ mode.status }}</GfTag>
          </div>
          <code>{{ mode.id }}</code>
          <p>{{ mode.description }}</p>
        </article>
      </div>
    </GfCard>
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

.tuning-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; align-items: start; }
.dial-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  padding: 10px 0;
  border-top: 1px solid var(--line-soft);
}
.dial-row:first-child { border-top: 0; padding-top: 2px; }
.dial-row span { font-family: var(--font-mono); color: var(--ink-soft); font-size: 11px; word-break: break-all; }
.dial-row b { font-family: var(--font-kai); color: var(--cinnabar); font-size: 15px; letter-spacing: 1px; }

.policy-modes { margin-top: 20px; }
.mode-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.mode-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  box-shadow: var(--shadow-card);
  padding: 14px;
  min-height: 132px;
  border-top: 2px solid var(--line);
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.mode-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lift); border-color: var(--gold-line); }
.mode-card.available { border-top-color: color-mix(in srgb, var(--bamboo) 60%, transparent); }
.mode-card.partial { border-top-color: color-mix(in srgb, var(--gold) 60%, transparent); }
.mode-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.mode-card h2 { font-family: var(--font-kai); font-size: 16px; letter-spacing: 2px; color: var(--ink); }
.mode-card code { display: block; margin: 6px 0 9px; font-family: var(--font-mono); font-size: 10.5px; color: var(--dai); }
.mode-card p { color: var(--ink-soft); font-size: 12px; line-height: 1.65; }

@media (max-width: 1100px) { .tuning-grid, .mode-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 620px) { .tuning-grid, .mode-grid { grid-template-columns: 1fr; } }
</style>

<script setup lang="ts">
import { computed, onMounted, shallowRef } from 'vue'
import { api } from '@/api/client'

const defaults = shallowRef<Record<string, Record<string, unknown>>>({})
const policies = shallowRef<any[]>([])
const error = shallowRef('')
const groups = computed(() => Object.entries(defaults.value))

onMounted(async () => {
  try {
    const [defaultRes, policyRes] = await Promise.all([api.tuningDefaults(), api.tuningPolicies()])
    defaults.value = defaultRes.defaults
    policies.value = policyRes.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})
</script>

<template>
  <div>
    <div class="page-head">
      <h1>司南调参舱</h1>
      <p>top_k · trust_threshold · 控制链路延迟口径 · 模型生成延迟分离展示</p>
    </div>
    <div v-if="error" class="muted">{{ error }}</div>

    <div class="tuning-grid">
      <section v-for="[group, values] in groups" :key="group" class="dial-bank">
        <div class="bank-title">{{ group }}</div>
        <div v-for="[key, value] in Object.entries(values)" :key="key" class="dial-row">
          <span>{{ key }}</span>
          <b>{{ value }}</b>
        </div>
      </section>
    </div>

    <section class="policy-modes">
      <div class="section-title">权限/执行模式</div>
      <div class="mode-grid">
        <article v-for="mode in policies" :key="mode.id" class="mode-card" :class="mode.status">
          <h2>{{ mode.name_cn }}</h2>
          <code>{{ mode.id }} / {{ mode.status }}</code>
          <p>{{ mode.description }}</p>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 24px; }
.page-head h1 { font-size: 28px; letter-spacing: 3px; }
.page-head p, .muted { color: var(--ink-soft); font-size: 13px; margin-top: 5px; }
.tuning-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.dial-bank { border: 1px solid var(--line); background: rgba(255,255,255,.36); padding: 15px; border-top: 4px solid var(--mineral); }
.bank-title { font-family: var(--mono); color: var(--gamboge); font-size: 12px; margin-bottom: 12px; text-transform: uppercase; }
.dial-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 14px; align-items: center; padding: 9px 0; border-top: 1px solid var(--line-soft); }
.dial-row span { font-family: var(--mono); color: var(--ink-soft); font-size: 11px; word-break: break-all; }
.dial-row b { color: var(--cinnabar); font-size: 13px; }
.policy-modes { margin-top: 28px; }
.section-title { border-left: 4px solid var(--cinnabar); padding-left: 10px; margin-bottom: 12px; font-size: 16px; font-weight: 700; letter-spacing: 2px; }
.mode-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.mode-card { border: 1px solid var(--line); background: rgba(255,255,255,.34); padding: 14px; min-height: 132px; border-top: 3px solid var(--ink-soft); }
.mode-card.available { border-top-color: var(--jade); }
.mode-card.partial { border-top-color: var(--gamboge); }
.mode-card h2 { font-size: 15px; letter-spacing: 1px; }
.mode-card code { display: block; margin: 6px 0 9px; font-size: 10.5px; color: var(--mineral); }
.mode-card p { color: var(--ink-soft); font-size: 12px; line-height: 1.55; }
@media (max-width: 1100px) { .tuning-grid, .mode-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 620px) { .tuning-grid, .mode-grid { grid-template-columns: 1fr; } }
</style>

<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import { api, type ModelProvider } from '@/api/client'

const providers = shallowRef<ModelProvider[]>([])
const testResult = shallowRef<any>(null)
const loading = shallowRef(true)
const error = shallowRef('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    providers.value = (await api.modelProviders()).items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function dryRun(provider: ModelProvider) {
  testResult.value = await api.testModelProvider({ provider: provider.provider, dry_run: true, prompt_preview: 'v0.7 console dry-run' })
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <h1>通玄模型舱</h1>
      <p>OpenAI-compatible / Anthropic / Gemini / local_mock · dry-run 网关仪器盘</p>
    </div>

    <div v-if="loading" class="muted">加载 provider...</div>
    <div v-else-if="error" class="muted">{{ error }}</div>
    <div v-else class="provider-grid">
      <article v-for="provider in providers" :key="provider.provider" class="provider" :class="{ enabled: provider.enabled }">
        <div class="provider-head">
          <h2>{{ provider.provider }}</h2>
          <span>{{ provider.enabled ? 'ENABLED' : 'STUB' }}</span>
        </div>
        <dl>
          <dt>model</dt><dd>{{ provider.model }}</dd>
          <dt>api_base</dt><dd>{{ provider.api_base }}</dd>
          <dt>key_alias</dt><dd>{{ provider.api_key_alias }}</dd>
          <dt>status</dt><dd>{{ provider.status }}</dd>
        </dl>
        <p>{{ provider.notes }}</p>
        <button @click="dryRun(provider)">Dry-run</button>
      </article>
    </div>

    <section class="result-panel">
      <div class="panel-title">调用日志预览</div>
      <pre>{{ testResult || '尚未执行 dry-run；v0.7 不保存、不回显、不打印真实 key。' }}</pre>
    </section>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 24px; }
.page-head h1 { font-size: 28px; letter-spacing: 3px; }
.page-head p { color: var(--ink-soft); font-size: 13px; margin-top: 5px; }
.muted { color: var(--ink-soft); }
.provider-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.provider { border: 1px solid var(--line); border-top: 4px solid var(--ink-soft); background: rgba(255,255,255,.38); padding: 15px; min-height: 310px; }
.provider.enabled { border-top-color: var(--jade); }
.provider-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.provider-head h2 { font-size: 16px; font-family: var(--mono); }
.provider-head span { border: 1px solid currentColor; padding: 2px 6px; font-size: 10px; color: var(--cinnabar); }
dl { display: grid; grid-template-columns: 72px 1fr; gap: 7px 8px; margin: 15px 0; }
dt { font-family: var(--mono); font-size: 10.5px; color: var(--gamboge); }
dd { font-size: 11.5px; color: var(--ink-soft); word-break: break-all; }
p { font-size: 12px; line-height: 1.55; color: var(--ink-soft); min-height: 58px; }
button { margin-top: 12px; border: 1px solid var(--cinnabar); color: var(--cinnabar); background: rgba(178,58,46,.07); padding: 8px 12px; }
.result-panel { margin-top: 28px; border: 1px solid var(--line); background: rgba(28,26,23,.04); }
.panel-title { padding: 10px 14px; border-bottom: 1px solid var(--line); font-size: 13px; letter-spacing: 2px; }
pre { padding: 14px; min-height: 120px; white-space: pre-wrap; font-family: var(--mono); font-size: 12px; color: var(--ink-soft); }
@media (max-width: 1100px) { .provider-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 620px) { .provider-grid { grid-template-columns: 1fr; } }
</style>

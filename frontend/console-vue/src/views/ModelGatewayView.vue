<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import { api, type ModelGatewayConfig, type ModelGatewayConfigInput, type ModelProvider } from '@/api/client'

type ConfigForm = ModelGatewayConfigInput
interface TestProvider {
  provider: string
  model: string
  enabled: boolean
  allowRealSmoke: boolean
}

interface ConfigRow extends ModelGatewayConfig {
  isCatalogProvider: boolean
  hasStoredConfig: boolean
}

const configs = shallowRef<ModelGatewayConfig[]>([])
const catalogProviders = shallowRef<ModelProvider[]>([])
const testResult = shallowRef<any>(null)
const loading = shallowRef(true)
const saving = shallowRef(false)
const deletingProvider = shallowRef('')
const testingProvider = shallowRef('')
const error = shallowRef('')
const smokePrompt = shallowRef('请用一句中文确认模型网关已接入宛委枢忆。')
const editingProvider = shallowRef<string | null>(null)
const isCreating = shallowRef(false)
const form = ref<ConfigForm>(emptyForm())

const configRows = computed<ConfigRow[]>(() => {
  const storedByProvider = new Map(configs.value.map((config) => [config.provider, config]))
  const rows: ConfigRow[] = catalogProviders.value.map((provider) => {
    const stored = storedByProvider.get(provider.provider)
    return {
      ...(stored ?? {
        provider: provider.provider,
        api_base: provider.api_base,
        api_key: '***' as const,
        model: provider.model,
        enabled: provider.enabled,
        notes: provider.notes,
      }),
      isCatalogProvider: true,
      hasStoredConfig: stored !== undefined,
    }
  })
  const catalogNames = new Set(catalogProviders.value.map((provider) => provider.provider))
  for (const config of configs.value) {
    if (!catalogNames.has(config.provider)) {
      rows.push({ ...config, isCatalogProvider: false, hasStoredConfig: true })
    }
  }
  return rows
})

const hasConfigs = computed(() => configRows.value.length > 0)
const testProviders = computed<TestProvider[]>(() => {
  const byProvider = new Map<string, TestProvider>()
  for (const provider of catalogProviders.value) {
    byProvider.set(provider.provider, {
      provider: provider.provider,
      model: provider.model,
      enabled: provider.enabled,
      allowRealSmoke: provider.provider === 'openai_compatible',
    })
  }
  for (const config of configs.value) {
    byProvider.set(config.provider, {
      provider: config.provider,
      model: config.model,
      enabled: config.enabled,
      allowRealSmoke: true,
    })
  }
  return [...byProvider.values()]
})

function emptyForm(): ConfigForm {
  return {
    provider: '',
    api_base: '',
    api_key: '',
    model: '',
    enabled: false,
    notes: '',
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [configResult, providerResult] = await Promise.all([
      api.modelGatewayConfigs(),
      api.modelProviders(),
    ])
    configs.value = configResult.items
    catalogProviders.value = providerResult.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function startNew() {
  if (saving.value || deletingProvider.value) return
  isCreating.value = true
  editingProvider.value = null
  form.value = emptyForm()
}

function startEdit(config: ModelGatewayConfig) {
  if (saving.value || deletingProvider.value) return
  isCreating.value = false
  editingProvider.value = config.provider
  form.value = {
    provider: config.provider,
    api_base: config.api_base,
    api_key: '',
    model: config.model,
    enabled: config.enabled,
    notes: config.notes,
  }
}

function resetEdit() {
  isCreating.value = false
  editingProvider.value = null
  form.value = emptyForm()
}

function cancelEdit() {
  if (saving.value || deletingProvider.value) return
  resetEdit()
}

function keyDisplay(config: ConfigRow) {
  return config.hasStoredConfig ? config.api_key : '—'
}

async function saveConfig() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  const payload = { ...form.value }
  form.value.api_key = ''
  try {
    await api.saveModelGatewayConfig(payload)
    resetEdit()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

async function deleteConfig(provider: string) {
  if (saving.value || deletingProvider.value) return
  deletingProvider.value = provider
  error.value = ''
  try {
    await api.deleteModelGatewayConfig(provider)
    if (editingProvider.value === provider) resetEdit()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    deletingProvider.value = ''
  }
}

async function dryRun(provider: TestProvider) {
  testingProvider.value = provider.provider
  try {
    testResult.value = await api.testModelProvider({
      provider: provider.provider,
      dry_run: true,
      prompt_preview: 'console configuration dry-run',
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    testingProvider.value = ''
  }
}

async function realSmoke(provider: TestProvider) {
  testingProvider.value = provider.provider
  try {
    testResult.value = await api.testModelProvider({
      provider: provider.provider,
      dry_run: false,
      prompt_preview: smokePrompt.value,
      model: provider.model,
      max_tokens: 96,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    testingProvider.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>通玄模型舱</h1>
        <p>配置即时写入本机 SQLite；列表只展示密钥掩码，真实密钥仅在提交时发送。</p>
      </div>
      <button class="primary-action" :disabled="saving || !!deletingProvider || editingProvider !== null || isCreating" @click="startNew">新增 provider</button>
    </div>

    <div v-if="error" class="notice error" role="alert" aria-live="polite">
      {{ error }}
      <button type="button" :disabled="loading || saving" @click="load">重试</button>
    </div>

    <section class="config-zone">
      <div class="section-title">配置台</div>
      <div v-if="loading" class="muted">读取配置中...</div>
      <div v-else class="table-wrap">
        <table v-if="hasConfigs" class="config-table">
          <thead>
            <tr>
              <th scope="col">provider</th>
              <th scope="col">api_base</th>
              <th scope="col">model</th>
              <th scope="col">key</th>
              <th scope="col">enabled</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="config in configRows" :key="config.provider">
              <tr>
                <td><code>{{ config.provider }}</code></td>
                <td class="long-value">{{ config.api_base }}</td>
                <td>{{ config.model }}</td>
                <td><code>{{ keyDisplay(config) }}</code></td>
                <td><span class="state" :class="{ enabled: config.enabled }">{{ config.enabled ? '已启用' : '停用' }}</span></td>
                <td class="row-actions">
                  <button title="编辑配置" :disabled="saving || !!deletingProvider || editingProvider !== null || isCreating" @click="startEdit(config)">编辑</button>
                  <button
                    v-if="config.hasStoredConfig"
                    :title="config.isCatalogProvider ? '删除数据库覆盖并恢复目录默认值' : '删除配置'"
                    class="danger"
                    :disabled="saving || !!deletingProvider || editingProvider !== null || isCreating"
                    @click="deleteConfig(config.provider)"
                  >
                    {{ deletingProvider === config.provider ? '删除中…' : config.isCatalogProvider ? '恢复默认' : '删除' }}
                  </button>
                </td>
              </tr>
              <tr v-if="editingProvider === config.provider" class="edit-row">
                <td colspan="6">
                  <form class="config-form" @submit.prevent="saveConfig">
                    <label>provider<input v-model.trim="form.provider" :disabled="saving || !!deletingProvider" required readonly /></label>
                    <label>api_base<input v-model.trim="form.api_base" :disabled="saving || !!deletingProvider" required autocomplete="off" /></label>
                    <label>model<input v-model.trim="form.model" :disabled="saving || !!deletingProvider" required autocomplete="off" /></label>
                    <label>api_key<input v-model="form.api_key" :disabled="saving || !!deletingProvider" type="password" autocomplete="new-password" placeholder="留空则保留当前密钥" /></label>
                    <label class="notes-field">notes<input v-model.trim="form.notes" :disabled="saving || !!deletingProvider" autocomplete="off" /></label>
                    <label class="enabled-field"><input v-model="form.enabled" :disabled="saving || !!deletingProvider" type="checkbox" /> 启用该 provider</label>
                    <div class="form-actions">
                      <button class="primary-action" type="submit" :disabled="saving || !!deletingProvider">{{ saving ? '保存中…' : '保存配置' }}</button>
                      <button type="button" :disabled="saving || !!deletingProvider" @click="cancelEdit">取消</button>
                    </div>
                  </form>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
        <div v-else class="empty-state">尚无 provider 配置。新增一条配置后可在下方进行测试。</div>
        <form v-if="isCreating" class="config-form new-form" @submit.prevent="saveConfig">
          <label>provider<input v-model.trim="form.provider" :disabled="saving || !!deletingProvider" required autocomplete="off" pattern="[A-Za-z0-9_-][A-Za-z0-9._-]*" title="仅支持字母、数字、点、下划线和连字符" /></label>
          <label>api_base<input v-model.trim="form.api_base" :disabled="saving || !!deletingProvider" required autocomplete="off" /></label>
          <label>model<input v-model.trim="form.model" :disabled="saving || !!deletingProvider" required autocomplete="off" /></label>
          <label>api_key<input v-model="form.api_key" :disabled="saving || !!deletingProvider" type="password" autocomplete="new-password" placeholder="仅提交时发送" /></label>
          <label class="notes-field">notes<input v-model.trim="form.notes" :disabled="saving || !!deletingProvider" autocomplete="off" /></label>
          <label class="enabled-field"><input v-model="form.enabled" :disabled="saving || !!deletingProvider" type="checkbox" /> 启用该 provider</label>
          <div class="form-actions">
            <button class="primary-action" type="submit" :disabled="saving || !!deletingProvider">{{ saving ? '保存中…' : '保存配置' }}</button>
            <button type="button" :disabled="saving || !!deletingProvider" @click="cancelEdit">取消</button>
          </div>
        </form>
      </div>
    </section>

    <section class="test-zone">
      <div class="section-title">测试台</div>
      <textarea v-model="smokePrompt" class="smoke-prompt" aria-label="真实 smoke 提示词"></textarea>
      <div v-if="testProviders.length" class="test-grid">
        <article v-for="provider in testProviders" :key="provider.provider" class="test-card" :class="{ enabled: provider.enabled }">
          <div>
            <h2>{{ provider.provider }}</h2>
            <p>{{ provider.model }}</p>
          </div>
          <div class="button-row">
            <button :disabled="saving || !!deletingProvider || !!testingProvider" @click="dryRun(provider)">{{ testingProvider === provider.provider ? '测试中…' : 'Dry-run' }}</button>
            <button v-if="provider.allowRealSmoke" class="primary-action" :disabled="saving || !!deletingProvider || !!testingProvider || !provider.enabled" @click="realSmoke(provider)">
              {{ testingProvider === provider.provider ? '调用中…' : '真实 smoke' }}
            </button>
          </div>
        </article>
      </div>
      <pre aria-live="polite">{{ testResult || '尚未执行测试。真实密钥不会在本页回显或写入调用日志。' }}</pre>
    </section>
  </div>
</template>

<style scoped>
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 24px; }
.page-head h1 { font-size: 28px; letter-spacing: 0; }
.page-head p { margin-top: 5px; color: var(--ink-soft); font-size: 13px; }
.section-title { border-left: 4px solid var(--cinnabar); padding-left: 10px; margin-bottom: 13px; font-size: 16px; font-weight: 700; letter-spacing: 0; }
.config-zone, .test-zone { border: 1px solid var(--line); background: rgba(255,255,255,.38); padding: 16px; box-shadow: var(--shadow-paper); }
.test-zone { margin-top: 24px; }
.muted, .empty-state { color: var(--ink-soft); font-size: 13px; padding: 14px 0; }
.notice { margin: 0 0 18px; padding: 10px 12px; border: 1px solid var(--line); font-size: 12px; }
.notice.error { color: var(--cinnabar-deep); border-color: var(--line-cinnabar); background: rgba(178,58,46,.07); }
.table-wrap { overflow-x: auto; }
.config-table { width: 100%; min-width: 820px; border-collapse: collapse; }
th, td { border-bottom: 1px solid var(--line-soft); padding: 11px 10px; text-align: left; vertical-align: middle; font-size: 12px; }
th { color: var(--gamboge); font-family: var(--mono); font-size: 10px; font-weight: 600; text-transform: uppercase; }
td { color: var(--ink-soft); }
code { font-family: var(--mono); font-size: 11px; color: var(--mineral); }
.long-value { max-width: 260px; overflow-wrap: anywhere; }
.state { border: 1px solid var(--line); color: var(--ink-muted); padding: 2px 6px; font-size: 10px; white-space: nowrap; }
.state.enabled { border-color: rgba(78,122,98,.45); color: var(--jade); }
.row-actions, .button-row, .form-actions { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; }
button { border: 1px solid var(--line-gold); background: rgba(255,255,255,.42); color: var(--ink-soft); padding: 7px 10px; font-size: 12px; }
button:hover:not(:disabled) { border-color: var(--cinnabar); color: var(--cinnabar); }
button:disabled { cursor: not-allowed; opacity: .55; }
.primary-action { border-color: var(--cinnabar); background: rgba(178,58,46,.08); color: var(--cinnabar); }
.danger { border-color: rgba(178,58,46,.32); color: var(--cinnabar-deep); }
.edit-row td { padding: 0; background: rgba(200,153,31,.055); }
.config-form { display: grid; grid-template-columns: repeat(3, minmax(160px, 1fr)); gap: 12px; padding: 14px; border-top: 1px solid var(--line-gold); }
.new-form { margin-top: 14px; border: 1px solid var(--line-gold); background: rgba(200,153,31,.05); }
label { display: grid; gap: 5px; color: var(--ink-muted); font-family: var(--mono); font-size: 10px; }
input { min-width: 0; border: 1px solid var(--line); background: rgba(255,255,255,.52); color: var(--ink); padding: 8px; font: inherit; font-size: 12px; }
input:focus, .smoke-prompt:focus { outline: 1px solid var(--cinnabar); border-color: var(--cinnabar); }
.notes-field { grid-column: span 2; }
.enabled-field { align-self: end; display: flex; align-items: center; gap: 7px; padding-bottom: 8px; font-family: var(--sans); font-size: 12px; color: var(--ink-soft); }
.enabled-field input { width: 15px; height: 15px; accent-color: var(--jade); }
.form-actions { align-self: end; justify-content: flex-end; }
.smoke-prompt { display: block; width: 100%; min-height: 76px; resize: vertical; margin-bottom: 14px; border: 1px solid var(--line); background: rgba(255,255,255,.52); color: var(--ink); padding: 10px; font: inherit; font-size: 13px; }
.test-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.test-card { border: 1px solid var(--line); border-top: 3px solid var(--ink-muted); background: rgba(255,255,255,.28); padding: 13px; }
.test-card.enabled { border-top-color: var(--jade); }
.test-card h2 { font-family: var(--mono); font-size: 14px; }
.test-card p { color: var(--ink-muted); font-size: 11px; margin-top: 4px; overflow-wrap: anywhere; }
.button-row { margin-top: 14px; }
pre { min-height: 116px; margin-top: 14px; padding: 13px; border: 1px solid var(--line-soft); background: rgba(26,23,20,.035); white-space: pre-wrap; overflow-wrap: anywhere; color: var(--ink-soft); font-family: var(--mono); font-size: 11px; line-height: 1.55; }
@media (max-width: 980px) { .test-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .config-form { grid-template-columns: repeat(2, minmax(150px, 1fr)); } .notes-field { grid-column: auto; } }
@media (max-width: 620px) { .page-head { display: grid; align-items: stretch; } .page-head .primary-action { justify-self: start; } .config-zone, .test-zone { padding: 13px; } .test-grid, .config-form { grid-template-columns: 1fr; } .form-actions { justify-content: flex-start; } }
</style>

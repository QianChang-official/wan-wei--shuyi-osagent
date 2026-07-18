<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import { api, type ModelGatewayConfig, type ModelGatewayConfigInput, type ModelProvider } from '@/api/client'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

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
    <PageHero
      seal="玄"
      title="通玄模型舱"
      en="MODEL GATEWAY"
      sub="配置即时写入本机 SQLite；列表只展示密钥掩码，真实密钥仅在提交时发送。"
    />

    <div class="action-bar">
      <GfButton :disabled="saving || !!deletingProvider || editingProvider !== null || isCreating" @click="startNew">新增 provider</GfButton>
    </div>

    <div v-if="error" class="notice error" role="alert" aria-live="polite">
      <span class="notice-text">{{ error }}</span>
      <GfButton variant="ghost" small :disabled="loading || saving" @click="load">重试</GfButton>
    </div>

    <GfCard title="配置台" seal="配">
      <div v-if="loading" class="muted">研墨中…</div>
      <template v-else>
        <div v-if="hasConfigs" class="table-wrap">
          <table class="config-table">
            <thead>
              <tr>
                <th scope="col">provider</th>
                <th scope="col">api_base</th>
                <th scope="col">model</th>
                <th scope="col">密钥</th>
                <th scope="col">启用</th>
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
                  <td><GfTag :tone="config.enabled ? 'bamboo' : 'ink'">{{ config.enabled ? '已启用' : '停用' }}</GfTag></td>
                  <td class="row-actions">
                    <GfButton variant="ghost" small title="编辑配置" :disabled="saving || !!deletingProvider || editingProvider !== null || isCreating" @click="startEdit(config)">编辑</GfButton>
                    <GfButton
                      v-if="config.hasStoredConfig"
                      variant="danger"
                      small
                      :title="config.isCatalogProvider ? '删除数据库覆盖并恢复目录默认值' : '删除配置'"
                      :disabled="saving || !!deletingProvider || editingProvider !== null || isCreating"
                      @click="deleteConfig(config.provider)"
                    >
                      {{ deletingProvider === config.provider ? '删除中…' : config.isCatalogProvider ? '恢复默认' : '删除' }}
                    </GfButton>
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
                        <button class="form-submit" type="submit" :disabled="saving || !!deletingProvider">{{ saving ? '保存中…' : '保存配置' }}</button>
                        <button class="form-cancel" type="button" :disabled="saving || !!deletingProvider" @click="cancelEdit">取消</button>
                      </div>
                    </form>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <GfEmpty v-else text="尚无 provider 配置。新增一条配置后可在下方进行测试。" />
        <form v-if="isCreating" class="config-form new-form" @submit.prevent="saveConfig">
          <label>provider<input v-model.trim="form.provider" :disabled="saving || !!deletingProvider" required autocomplete="off" pattern="[A-Za-z0-9_-][A-Za-z0-9._-]*" title="仅支持字母、数字、点、下划线和连字符" /></label>
          <label>api_base<input v-model.trim="form.api_base" :disabled="saving || !!deletingProvider" required autocomplete="off" /></label>
          <label>model<input v-model.trim="form.model" :disabled="saving || !!deletingProvider" required autocomplete="off" /></label>
          <label>api_key<input v-model="form.api_key" :disabled="saving || !!deletingProvider" type="password" autocomplete="new-password" placeholder="仅提交时发送" /></label>
          <label class="notes-field">notes<input v-model.trim="form.notes" :disabled="saving || !!deletingProvider" autocomplete="off" /></label>
          <label class="enabled-field"><input v-model="form.enabled" :disabled="saving || !!deletingProvider" type="checkbox" /> 启用该 provider</label>
          <div class="form-actions">
            <button class="form-submit" type="submit" :disabled="saving || !!deletingProvider">{{ saving ? '保存中…' : '保存配置' }}</button>
            <button class="form-cancel" type="button" :disabled="saving || !!deletingProvider" @click="cancelEdit">取消</button>
          </div>
        </form>
      </template>
    </GfCard>

    <GfCard title="测试台" seal="试" class="test-zone">
      <textarea v-model="smokePrompt" class="smoke-prompt" aria-label="真实 smoke（冒烟测试）提示词"></textarea>
      <div v-if="testProviders.length" class="test-grid">
        <article v-for="provider in testProviders" :key="provider.provider" class="test-card" :class="{ enabled: provider.enabled }">
          <div class="test-head">
            <h2>{{ provider.provider }}</h2>
            <GfTag :tone="provider.enabled ? 'bamboo' : 'ink'">{{ provider.enabled ? '已启用' : '停用' }}</GfTag>
          </div>
          <p class="test-model">{{ provider.model }}</p>
          <div class="button-row">
            <GfButton variant="ghost" small :disabled="saving || !!deletingProvider || !!testingProvider" @click="dryRun(provider)">{{ testingProvider === provider.provider ? '测试中…' : 'Dry-run（模拟运行）' }}</GfButton>
            <GfButton v-if="provider.allowRealSmoke" small :disabled="saving || !!deletingProvider || !!testingProvider || !provider.enabled" @click="realSmoke(provider)">
              {{ testingProvider === provider.provider ? '调用中…' : '真实 smoke（冒烟测试）' }}
            </GfButton>
          </div>
        </article>
      </div>
      <pre aria-live="polite">{{ testResult || '尚未执行测试。真实密钥不会在本页回显或写入调用日志。' }}</pre>
    </GfCard>
  </div>
</template>

<style scoped>
.action-bar { display: flex; justify-content: flex-end; margin: -8px 0 18px; }
.muted { color: var(--ink-soft); font-size: 13px; padding: 14px 0; font-family: var(--font-kai); letter-spacing: 2px; }

.notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
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
.notice-text { line-height: 1.6; }

.test-zone { margin-top: 20px; }

/* ── 表格：圆角容器 + 楷体表头 + 行 hover 染胭脂 ── */
.table-wrap { overflow-x: auto; border-radius: var(--radius-small); }
.config-table { width: 100%; min-width: 820px; border-collapse: collapse; }
th, td { border-bottom: 1px solid var(--line-soft); padding: 11px 10px; text-align: left; vertical-align: middle; font-size: 12px; }
th {
  background: var(--bg-soft);
  color: var(--gold);
  font-family: var(--font-kai);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 2px;
}
td { color: var(--ink-soft); }
tbody tr { transition: background .18s ease; }
tbody tr:hover { background: color-mix(in srgb, var(--rouge) 8%, transparent); }
code { font-family: var(--font-mono); font-size: 11px; color: var(--dai); }
.long-value { max-width: 260px; overflow-wrap: anywhere; }
.row-actions, .button-row, .form-actions { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; }
.edit-row td { padding: 0; background: color-mix(in srgb, var(--gold) 6%, transparent); }
.edit-row:hover { background: color-mix(in srgb, var(--gold) 8%, transparent); }

/* ── 表单：圆角 10px 半透底，focus 朱砂描边 + 胭脂光晕 ── */
.config-form { display: grid; grid-template-columns: repeat(3, minmax(160px, 1fr)); gap: 12px; padding: 14px; border-top: 1px solid var(--gold-line); }
.new-form {
  margin-top: 14px;
  border: 1px solid var(--gold-line);
  border-radius: var(--radius-card);
  background: color-mix(in srgb, var(--gold) 5%, transparent);
}
label { display: grid; gap: 6px; color: var(--ink-muted); font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px; }
input {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 8px 12px;
  font: inherit;
  font-size: 12px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
input:focus, .smoke-prompt:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
input:disabled { opacity: .55; }
.notes-field { grid-column: span 2; }
.enabled-field { align-self: end; display: flex; align-items: center; gap: 7px; padding-bottom: 8px; font-family: var(--font-sans); font-size: 12px; color: var(--ink-soft); }
.enabled-field input { width: 15px; height: 15px; accent-color: var(--bamboo); }
.form-actions { align-self: end; justify-content: flex-end; }

/* 表单内原生提交/取消按钮（GfButton 固定 type=button，提交钮需原生 submit） */
.form-submit, .form-cancel {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 20px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 13px;
  letter-spacing: 2px;
  font-family: var(--font-kai);
  cursor: pointer;
  transition: transform .18s ease, box-shadow .18s ease, background .18s ease, color .18s ease, border-color .18s ease;
}
.form-submit {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: 0 2px 12px var(--cinnabar-glow), var(--shadow-card);
}
.form-submit:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 4px 18px var(--cinnabar-glow), var(--shadow-glow-rouge); }
.form-cancel { background: var(--card); border-color: var(--gold-line); color: var(--ink-soft); }
.form-cancel:hover:not(:disabled) { transform: translateY(-2px); border-color: var(--rouge); color: var(--cinnabar); box-shadow: var(--shadow-glow-rouge); }
.form-submit:disabled, .form-cancel:disabled { opacity: .55; cursor: not-allowed; transform: none; box-shadow: none; }

/* ── 测试台 ── */
.smoke-prompt {
  display: block;
  width: 100%;
  min-height: 76px;
  resize: vertical;
  margin-bottom: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 10px 12px;
  font: inherit;
  font-size: 13px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.test-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.test-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--card);
  box-shadow: var(--shadow-card);
  padding: 14px;
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.test-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lift); border-color: var(--gold-line); }
.test-card.enabled { border-color: color-mix(in srgb, var(--bamboo) 45%, transparent); }
.test-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.test-head h2 { font-family: var(--font-mono); font-size: 14px; color: var(--ink); overflow-wrap: anywhere; }
.test-model { color: var(--ink-muted); font-size: 11px; margin-top: 6px; overflow-wrap: anywhere; }
.button-row { margin-top: 14px; }
pre {
  min-height: 116px;
  margin-top: 14px;
  padding: 14px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--bg-soft);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--ink-soft);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
}

@media (max-width: 980px) { .test-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .config-form { grid-template-columns: repeat(2, minmax(150px, 1fr)); } .notes-field { grid-column: auto; } }
@media (max-width: 620px) { .action-bar { justify-content: flex-start; } .test-grid, .config-form { grid-template-columns: 1fr; } .form-actions { justify-content: flex-start; } }
</style>

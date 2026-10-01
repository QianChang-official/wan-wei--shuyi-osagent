<!--
 Copyright (c) 2026 QianChang-official

 宛委·枢忆 is licensed under Mulan PSL v2.
 You can use this software according to the terms of the Mulan PSL v2.
 You may obtain a copy of Mulan PSL v2 at:
 http://license.coscl.org.cn/MulanPSL2

 THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
 EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
 MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
 See the Mulan PSL v2 for more details.
-->

<script setup lang="ts">
/**
 * SettingsModal —— 设置面板（模态，带左侧导航）：
 * 外观（昼夜/花瓣）· 模型接入（真实服务商配置 + 连通测试）·
 * 记忆指令（真实读写）· 通用（访问密钥）· 关于（版本实时取自后端）。
 */
import { computed, onMounted, ref } from 'vue'
import { api, getApiKey, getCredentialRevision, setApiKey } from '@/api/client'
import type { Instructions, ProviderCatalogEntry, ProviderConfig, ProviderTestResult } from '@/api/types'
import { applyTheme, getPetalsEnabled, getTheme, setPetalsEnabled, type GfTheme } from '@/components/gf/shared'
import { useDialogFocus } from '@/composables/useDialogFocus'
import { useAgents } from '@/composables/useAgents'
import { useRuns } from '@/composables/useRuns'
import { useChat } from '@/composables/useChat'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import { useHealth } from '@/composables/useHealth'

const props = defineProps<{ initialSection?: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const panel = ref<HTMLElement | null>(null)
useDialogFocus(panel, () => emit('close'))

type Section = 'appearance' | 'providers' | 'memory' | 'general' | 'about'
const SECTIONS: { id: Section; name: string; seal: string }[] = [
  { id: 'appearance', name: '外观', seal: '妆' },
  { id: 'providers', name: '模型接入', seal: '玄' },
  { id: 'memory', name: '记忆指令', seal: '忆' },
  { id: 'general', name: '通用', seal: '契' },
  { id: 'about', name: '关于', seal: '识' },
]
const VALID_SECTIONS = new Set(SECTIONS.map((s) => s.id))
const section = ref<Section>(
  VALID_SECTIONS.has(props.initialSection as Section) ? (props.initialSection as Section) : 'appearance',
)

const { online, version, name, check } = useHealth()

/* ── 外观 ── */
const theme = ref<GfTheme>(getTheme())
const petalsOn = ref(getPetalsEnabled())
function switchTheme(t: GfTheme) { theme.value = t; applyTheme(t) }
function switchPetals(on: boolean) { petalsOn.value = on; setPetalsEnabled(on) }

/* ── 模型接入 ── */
const configs = ref<ProviderConfig[]>([])
const catalog = ref<ProviderCatalogEntry[]>([])
const providersLoading = ref(false)
const providersError = ref('')
const editingPid = ref('')
const editForm = ref({ api_key: '', base_url: '', model: '', enabled: true })
const saving = ref(false)
const testing = ref('')
const saveError = ref('')
const testResults = ref<Record<string, ProviderTestResult>>({})
const filter = ref('')

const catalogById = computed(() => new Map(catalog.value.map((c) => [c.id, c])))
const visibleConfigs = computed(() => {
  const kw = filter.value.trim().toLowerCase()
  const list = configs.value
  if (!kw) return list
  return list.filter((c) =>
    c.pid.toLowerCase().includes(kw)
    || (catalogById.value.get(c.pid)?.name ?? '').toLowerCase().includes(kw),
  )
})

async function loadProviders() {
  const scope = getCredentialRevision()
  providersLoading.value = true
  providersError.value = ''
  try {
    const [cfgs, ctl] = await Promise.all([api.listProviderConfigs(), api.listProviderCatalog()])
    if (scope !== getCredentialRevision()) return
    configs.value = cfgs
    catalog.value = ctl
  } catch (err) {
    if (scope !== getCredentialRevision()) return
    providersError.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (scope === getCredentialRevision()) providersLoading.value = false
  }
}

function startEdit(cfg: ProviderConfig) {
  if (saving.value) return
  if (editingPid.value === cfg.pid) { editingPid.value = ''; return }
  saveError.value = ''
  editingPid.value = cfg.pid
  editForm.value = {
    api_key: '',
    base_url: cfg.base_url || catalogById.value.get(cfg.pid)?.base_url || '',
    model: cfg.model || catalogById.value.get(cfg.pid)?.models[0] || '',
    enabled: cfg.enabled,
  }
}

async function saveProvider(pid: string) {
  if (saving.value) return
  saving.value = true
  saveError.value = ''
  try {
    const body: Record<string, unknown> = {
      base_url: editForm.value.base_url,
      model: editForm.value.model,
      enabled: editForm.value.enabled,
    }
    if (editForm.value.api_key) body.api_key = editForm.value.api_key
    await api.saveProviderConfig(pid, body)
    editingPid.value = ''
    editForm.value.api_key = ''
    await loadProviders()
    useChat().revision.value++
  } catch (err) {
    saveError.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}

async function testProvider(pid: string) {
  if (testing.value) return
  testing.value = pid
  try {
    const res = await testProviderInner(pid)
    testResults.value = { ...testResults.value, [pid]: res }
  } finally {
    testing.value = ''
  }
}
async function testProviderInner(pid: string): Promise<ProviderTestResult> {
  try {
    return await api.testProvider(pid)
  } catch (err) {
    return { ok: false, pid, reason: err instanceof Error ? err.message : String(err) }
  }
}

/* ── 记忆指令 ── */
const instructions = ref<Instructions | null>(null)
const instructionsText = ref('')
const instructionsLoading = ref(false)
const instructionsMsg = ref('')
const instructionsError = ref('')
const instructionsSaving = ref(false)

async function loadInstructions() {
  const scope = getCredentialRevision()
  instructionsLoading.value = true
  instructionsError.value = ''
  try {
    const res = await api.getInstructions()
    if (scope !== getCredentialRevision()) return
    instructions.value = res
    instructionsText.value = res.lines.join('\n')
  } catch (err) {
    if (scope !== getCredentialRevision()) return
    instructions.value = null
    instructionsError.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (scope === getCredentialRevision()) instructionsLoading.value = false
  }
}

async function saveInstructions() {
  if (instructionsSaving.value) return
  instructionsSaving.value = true
  instructionsMsg.value = ''
  const lines = instructionsText.value.split('\n').map((l) => l.trim()).filter(Boolean)
  try {
    const res = await api.putInstructions(lines)
    instructions.value = res
    instructionsText.value = res.lines.join('\n')
    instructionsMsg.value = `已保存 ${res.count} 条（治理留痕已记录）`
    useChat().revision.value++
  } catch (err) {
    instructionsMsg.value = err instanceof Error ? err.message : String(err)
  } finally { instructionsSaving.value = false }
}

/* ── 通用：访问密钥 ── */
const keyDraft = ref('')
const keyMsg = ref('')
const keySaving = ref(false)
async function saveKey() {
  if (keySaving.value) return
  keySaving.value = true
  keyMsg.value = ''
  setApiKey(keyDraft.value)
  keyDraft.value = ''
  configs.value = []
  catalog.value = []
  instructions.value = null
  editingPid.value = ''
  editForm.value.api_key = ''
  testResults.value = {}
  try {
    await Promise.all([useAgents().refresh(), useRuns().refresh(), loadProviders(), loadInstructions(), check()])
    keyMsg.value = useAgents().error.value
      ? `密钥已保存，但重新加载失败：${useAgents().error.value}`
      : getApiKey() ? '访问密钥已更新，共享数据已重新加载' : '访问密钥已清除，共享数据已重新加载'
  } finally { keySaving.value = false }
}

onMounted(() => {
  loadProviders()
  loadInstructions()
  keyDraft.value = ''
})

const appVersion = __APP_VERSION__
</script>

<template>
  <div class="settings-mask" @click.self="emit('close')">
    <div ref="panel" tabindex="-1" class="settings-panel" role="dialog" aria-modal="true" aria-label="设置">
      <!-- 左侧导航 -->
      <nav class="st-nav">
        <div class="st-title">设置</div>
        <button
          v-for="s in SECTIONS"
          :key="s.id"
          type="button"
          class="st-item"
          :class="{ active: section === s.id }"
          @click="section = s.id"
        >
          <span class="st-seal">{{ s.seal }}</span>
          <span>{{ s.name }}</span>
        </button>
      </nav>

      <!-- 内容区 -->
      <main class="st-body">
        <button class="st-close" type="button" title="关闭" aria-label="关闭设置" @click="emit('close')">✕</button>

        <!-- 外观 -->
        <section v-if="section === 'appearance'" class="st-section">
          <h2>外观</h2>
          <div class="row">
            <span class="row-label">昼夜</span>
            <div class="seg">
              <button :class="{ on: theme === 'day' }" type="button" @click="switchTheme('day')">宣纸白昼</button>
              <button :class="{ on: theme === 'night' }" type="button" @click="switchTheme('night')">靛夜灯影</button>
            </div>
          </div>
          <div class="row">
            <span class="row-label">花瓣雨</span>
            <div class="seg">
              <button :class="{ on: petalsOn }" type="button" @click="switchPetals(true)">开</button>
              <button :class="{ on: !petalsOn }" type="button" @click="switchPetals(false)">关</button>
            </div>
          </div>
        </section>

        <!-- 模型接入 -->
        <section v-else-if="section === 'providers'" class="st-section">
          <h2>模型接入</h2>
          <p class="hint">对话经模型网关真实调用；此处配置服务商密钥与端点，密钥只保存在后端，前端永不回显。</p>
          <RouterLink to="/platform/providers" @click="emit('close')">高级模型接入（OAuth / 辅助模型 / 导入导出）</RouterLink>
          <input v-model="filter" class="txt" type="search" aria-label="筛选服务商" placeholder="筛选服务商…" />
          <p v-if="providersError" class="error-line" role="alert">{{ providersError }} <button type="button" @click="loadProviders">重试</button></p>
          <p v-else-if="providersLoading" class="hint">载入中…</p>
          <GfEmpty v-else-if="visibleConfigs.length === 0" text="无匹配服务商" />
          <div v-else class="provider-list">
            <div v-for="cfg in visibleConfigs" :key="cfg.pid" class="provider-row">
              <div class="pr-head">
                <b>{{ catalogById.get(cfg.pid)?.name ?? cfg.pid }}</b>
                <GfTag v-if="cfg.enabled && cfg.configured" tone="bamboo">已启用</GfTag>
                <GfTag v-else-if="cfg.configured" tone="gold">已配置未启用</GfTag>
                <GfTag v-else tone="ink">未配置</GfTag>
                <span class="pr-kind">{{ catalogById.get(cfg.pid)?.kind ?? '' }}</span>
                <span class="spacer"></span>
                <button class="mini-btn" type="button" @click="startEdit(cfg)">
                  {{ editingPid === cfg.pid ? '收起' : '配置' }}
                </button>
                <button
                  v-if="cfg.configured"
                  class="mini-btn" type="button"
                  :disabled="!!testing"
                  @click="testProvider(cfg.pid)"
                >{{ testing === cfg.pid ? '探测中…' : '测试' }}</button>
              </div>
              <div v-if="editingPid === cfg.pid" class="pr-form">
                <label>端点<input v-model="editForm.base_url" class="txt" type="url" placeholder="https://…" /></label>
                <label>模型<input v-model="editForm.model" class="txt" type="text" placeholder="模型名" /></label>
                <label>
                  密钥{{ cfg.has_api_key ? `（已存 ${cfg.api_key_masked}，留空保持不变）` : '' }}
                  <input v-model="editForm.api_key" class="txt" type="password" autocomplete="new-password" placeholder="sk-…" />
                </label>
                <label class="chk"><input v-model="editForm.enabled" type="checkbox" /> 启用</label>
                <p v-if="saveError" class="error-line" role="alert">{{ saveError }}</p>
                <div class="pr-actions">
                  <button class="mini-btn primary" type="button" :disabled="saving" @click="saveProvider(cfg.pid)">保存</button>
                  <button class="mini-btn" type="button" :disabled="saving" @click="editingPid = ''">取消</button>
                </div>
              </div>
              <p v-if="testResults[cfg.pid]" class="pr-test" role="status" :class="{ ok: testResults[cfg.pid].ok }">
                {{ testResults[cfg.pid].ok
                  ? `✓ ${testResults[cfg.pid].note ?? '连通正常'}${testResults[cfg.pid].latency_ms != null ? `（${testResults[cfg.pid].latency_ms}ms）` : ''}`
                  : `✗ ${testResults[cfg.pid].reason ?? '探测失败'}` }}
              </p>
            </div>
          </div>
        </section>

        <!-- 记忆指令 -->
        <section v-else-if="section === 'memory'" class="st-section">
          <h2>记忆指令</h2>
          <p class="hint">每行一条，注入所有对话的系统提示；保存即记录治理留痕。</p>
          <p v-if="instructionsLoading" class="hint">载入中…</p>
          <template v-else-if="instructions">
            <textarea
              v-model="instructionsText"
              aria-label="记忆指令"
              class="txt area"
              rows="10"
              :placeholder="'例如：\n回复一律使用简体中文\n代码变更先列计划再动手'"
            ></textarea>
            <div class="mem-bar">
              <span class="hint">{{ instructions.count }} / {{ instructions.max }} 条</span>
              <button class="mini-btn primary" type="button" :disabled="instructionsSaving" @click="saveInstructions">保存</button>
            </div>
            <p v-if="instructionsMsg" class="hint">{{ instructionsMsg }}</p>
          </template>
          <p v-else class="error-line" role="alert">{{ instructionsError || '记忆指令服务暂不可达' }} <button type="button" @click="loadInstructions">重试</button></p>
        </section>

        <!-- 通用 -->
        <section v-else-if="section === 'general'" class="st-section">
          <h2>通用</h2>
          <div class="row column">
            <span class="row-label">控制台访问密钥（X-API-Key）</span>
            <p class="hint">仅当后端启用了密钥鉴权时才需填写；密钥只保存在本机浏览器。</p>
            <div class="key-row">
              <input
                v-model="keyDraft" aria-label="控制台访问密钥" class="txt" type="password" autocomplete="off"
                :placeholder="getApiKey() ? '已设置（输入以更换）' : '未设置'"
              />
              <button class="mini-btn primary" type="button" :disabled="keySaving" @click="saveKey">{{ keySaving ? '重新加载中…' : '保存' }}</button>
            </div>
            <p v-if="keyMsg" class="hint" role="status">{{ keyMsg }}</p>
          </div>
        </section>

        <!-- 关于 -->
        <section v-else class="st-section">
          <h2>关于</h2>
          <div class="about">
            <div class="about-seal">枢</div>
            <div>
              <p class="about-name">宛委·枢忆 <span>花朝台</span></p>
              <p class="hint">端侧记忆治理 · 多智能体编排控制台</p>
            </div>
          </div>
          <dl class="about-list">
            <div><dt>后端</dt><dd>{{ online ? `${name} ${version}` : '离线' }}</dd></div>
            <div><dt>控制台</dt><dd>v{{ appVersion }}</dd></div>
            <div><dt>许可证</dt><dd>Mulan PSL v2</dd></div>
          </dl>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.settings-mask {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(20, 16, 12, .38);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  display: grid;
  place-items: center;
  animation: fade-in .18s ease;
}
@keyframes fade-in { from { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .settings-mask { animation: none; } }

.settings-panel {
  width: min(880px, 92vw);
  height: min(620px, 86vh);
  display: flex;
  overflow: hidden;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: var(--bg);
  box-shadow: var(--shadow-lift);
}

/* 左侧导航 */
.st-nav {
  flex: none;
  width: 168px;
  padding: 18px 10px;
  border-right: 1px solid var(--line-soft);
  background: var(--card);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.st-title {
  font-family: var(--font-kai);
  font-size: 17px;
  letter-spacing: 4px;
  padding: 0 10px 12px;
}
.st-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-small);
  background: transparent;
  font-size: 13px;
  color: var(--ink-soft);
  text-align: left;
  transition: background .16s ease, color .16s ease;
}
.st-item:hover { background: var(--bg-soft); }
.st-item.active { background: var(--bg-soft); color: var(--ink); border-color: var(--gold-line); }
.st-seal {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-family: var(--font-kai);
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: 5px;
}

/* 内容区 */
.st-body { flex: 1; min-width: 0; overflow-y: auto; padding: 22px 26px; position: relative; }
.st-close {
  position: absolute;
  top: 14px;
  right: 16px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: var(--card);
  color: var(--ink-soft);
}
.st-close:hover { color: var(--cinnabar); border-color: var(--cinnabar); }
.st-section h2 {
  font-family: var(--font-kai);
  font-size: 19px;
  letter-spacing: 4px;
  margin-bottom: 14px;
}
.hint { font-size: 12px; color: var(--ink-muted); line-height: 1.8; }
.error-line { font-size: 12.5px; color: var(--cinnabar); }

.row { display: flex; align-items: center; gap: 14px; padding: 10px 0; }
.row.column { flex-direction: column; align-items: stretch; gap: 8px; }
.row-label { font-size: 13px; letter-spacing: 1px; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: var(--radius-pill); overflow: hidden; }
.seg button {
  padding: 6px 16px;
  border: 0;
  background: transparent;
  color: var(--ink-soft);
  font-size: 12.5px;
  transition: background .16s ease, color .16s ease;
}
.seg button.on { background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep)); color: #FDF6E9; }

.txt {
  width: 100%;
  padding: 7px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card-solid);
  font-size: 13px;
  transition: border-color .16s ease, box-shadow .16s ease;
}
.txt:focus { outline: none; border-color: var(--rouge); box-shadow: 0 0 0 3px var(--rouge-glow); }
.txt.area { font-family: var(--font-mono); font-size: 12.5px; line-height: 1.8; resize: vertical; }

/* 模型接入 */
.provider-list { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.provider-row {
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--card);
  padding: 10px 12px;
}
.pr-head { display: flex; align-items: center; gap: 8px; }
.pr-head b { font-size: 13px; }
.pr-kind { font-size: 11px; color: var(--ink-muted); }
.spacer { flex: 1; }
.pr-form { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.pr-form label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-soft); }
.pr-form .chk { flex-direction: row; align-items: center; gap: 6px; }
.pr-actions { display: flex; gap: 8px; }
.pr-test { margin-top: 8px; font-size: 12px; color: var(--cinnabar); }
.pr-test.ok { color: var(--bamboo); }

.mini-btn {
  padding: 4px 12px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--gold-line);
  background: var(--card-solid);
  color: var(--ink-soft);
  font-size: 12px;
  transition: all .16s ease;
}
.mini-btn:hover { border-color: var(--rouge); color: var(--rouge); }
.mini-btn.primary {
  border-color: transparent;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
}
.mini-btn:disabled { opacity: .5; cursor: wait; }

/* 记忆指令 */
.mem-bar { display: flex; align-items: center; justify-content: space-between; margin-top: 8px; }

/* 通用 */
.key-row { display: flex; gap: 8px; }

/* 关于 */
.about { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }
.about-seal {
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
  font-family: var(--font-kai);
  font-size: 26px;
  font-weight: 700;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: var(--shadow-seal);
}
.about-name { font-family: var(--font-kai); font-size: 18px; letter-spacing: 2px; }
.about-name span { font-size: 12px; color: var(--ink-muted); margin-left: 6px; }
.about-list { display: flex; flex-direction: column; gap: 8px; font-size: 13px; }
.about-list > div { display: flex; gap: 12px; }
.about-list dt { width: 72px; color: var(--ink-muted); letter-spacing: 2px; }
.about-list dd { font-family: var(--font-mono); font-size: 12.5px; }
@media (max-width: 640px) {
  .settings-panel { flex-direction: column; width: 96vw; height: 92dvh; }
  .st-nav { width: 100%; padding: 8px; flex-direction: row; overflow-x: auto; flex-shrink: 0; }
  .st-title, .st-seal { display: none; }
  .st-item { flex-shrink: 0; padding: 8px; }
  .st-body { padding: 18px 12px; }
  .pr-head, .key-row { flex-wrap: wrap; }
}
</style>

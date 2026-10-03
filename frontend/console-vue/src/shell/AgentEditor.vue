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
/** AgentEditor —— 新建 / 编辑智能体（POST/PUT /platform/agents） */
import { computed, ref } from 'vue'
import { useAgents } from '@/composables/useAgents'
import type { Agent, AgentInput } from '@/api/types'
import { GEARS, GEAR_LABELS } from '@/utils/platformEnums'

const props = defineProps<{ agent?: Agent | null }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()

const { create, update } = useAgents()

const DEPTHS = [
  { value: 'low', label: '浅思 low' },
  { value: 'medium', label: '中思 medium' },
  { value: 'high', label: '深思 high' },
  { value: 'xhigh', label: '极思 xhigh' },
  { value: 'max', label: '彻思 max' },
  { value: 'ultracode', label: '超码 ultracode' },
] as const

const PERMISSION_LABELS: Record<string, string> = {
  fs_read: '读文件', fs_write: '写文件', shell: '命令行', network: '网络', git: 'Git',
}

const form = ref<AgentInput>(props.agent
  ? {
      name: props.agent.name,
      role: props.agent.role,
      persona: props.agent.persona,
      depth: props.agent.depth,
      gear: props.agent.gear,
      permissions: { ...props.agent.permissions },
      provider_pid: props.agent.provider_pid,
      model: props.agent.model,
      goal: props.agent.goal,
    }
  : {
      name: '',
      role: '',
      persona: '',
      depth: 'medium',
      gear: 'sandbox',
      permissions: { fs_read: true, fs_write: false, shell: false, network: false, git: false },
      provider_pid: '',
      model: '',
      goal: '',
    })

const saving = ref(false)
const error = ref('')

const valid = computed(() => form.value.name.trim().length > 0 && form.value.name.trim().length <= 60)

async function save() {
  if (!valid.value || saving.value) return
  saving.value = true
  error.value = ''
  try {
    const payload: AgentInput = { ...form.value, name: form.value.name.trim() }
    if (props.agent) await update(props.agent.id, payload)
    else await create(payload)
    emit('saved')
    emit('close')
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="editor-mask" @click.self="emit('close')">
    <div class="editor-panel" role="dialog" aria-modal="true" :aria-label="agent ? '编辑智能体' : '新智能体'">
      <h2 class="ed-title">
        <span class="ed-seal">{{ agent ? '修' : '立' }}</span>
        {{ agent ? `编辑「${agent.name}」` : '新智能体' }}
      </h2>

      <div class="ed-grid">
        <label class="fld">
          <span>名称 *</span>
          <input v-model="form.name" class="txt" type="text" maxlength="60" placeholder="例如：书僮" />
        </label>
        <label class="fld">
          <span>角色定位</span>
          <input v-model="form.role" class="txt" type="text" placeholder="例如：代码看护" />
        </label>
        <label class="fld wide">
          <span>人格语气</span>
          <input v-model="form.persona" class="txt" type="text" placeholder="例如：温润、严谨、直言" />
        </label>
        <label class="fld wide">
          <span>目标</span>
          <textarea v-model="form.goal" class="txt area" rows="2" placeholder="这位智能体要达成什么"></textarea>
        </label>
        <label class="fld">
          <span>思考深度</span>
          <select v-model="form.depth" class="txt">
            <option v-for="d in DEPTHS" :key="d.value" :value="d.value">{{ d.label }}</option>
          </select>
        </label>
        <label class="fld">
          <span>工作档位</span>
          <select v-model="form.gear" class="txt">
            <option v-for="g in GEARS" :key="g" :value="g">{{ GEAR_LABELS[g] }}</option>
          </select>
        </label>
        <label class="fld">
          <span>绑定服务商（pid，可空）</span>
          <input v-model="form.provider_pid" class="txt" type="text" placeholder="如 deepseek；空为网关默认" />
        </label>
        <label class="fld">
          <span>绑定模型（可空）</span>
          <input v-model="form.model" class="txt" type="text" placeholder="如 deepseek-chat" />
        </label>
        <fieldset class="fld wide perms">
          <span>权限面</span>
          <label v-for="(label, key) in PERMISSION_LABELS" :key="key" class="chk">
            <input v-model="form.permissions[key as keyof typeof form.permissions]" type="checkbox" />
            {{ label }}
          </label>
        </fieldset>
      </div>

      <p v-if="error" class="ed-error">{{ error }}</p>

      <div class="ed-actions">
        <button class="btn ghost" type="button" @click="emit('close')">取消</button>
        <button class="btn primary" type="button" :disabled="!valid || saving" @click="save">
          {{ saving ? '保存中…' : agent ? '保存修改' : '创建' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.editor-mask {
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
@media (prefers-reduced-motion: reduce) { .editor-mask { animation: none; } }

.editor-panel {
  width: min(640px, 92vw);
  max-height: 86vh;
  overflow-y: auto;
  border-radius: var(--radius-card);
  border: 1px solid var(--line);
  background: var(--bg);
  box-shadow: var(--shadow-lift);
  padding: 22px 26px;
}
.ed-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-kai);
  font-size: 18px;
  letter-spacing: 3px;
  margin-bottom: 16px;
}
.ed-seal {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  font-size: 14px;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: var(--shadow-seal);
}

.ed-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; }
.fld { display: flex; flex-direction: column; gap: 5px; border: 0; }
.fld.wide { grid-column: 1 / -1; }
.fld > span { font-size: 12px; color: var(--ink-soft); letter-spacing: 1px; }
.txt {
  padding: 7px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card-solid);
  font-size: 13px;
  transition: border-color .16s ease, box-shadow .16s ease;
}
.txt:focus { outline: none; border-color: var(--rouge); box-shadow: 0 0 0 3px var(--rouge-glow); }
.txt.area { resize: vertical; line-height: 1.7; }
.perms { flex-direction: row !important; flex-wrap: wrap; align-items: center; gap: 8px 16px; padding: 0; }
.perms > span { width: 100%; }
.chk { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--ink-soft); }

.ed-error { margin-top: 12px; font-size: 12.5px; color: var(--cinnabar); }

.ed-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.btn {
  padding: 8px 22px;
  border-radius: var(--radius-pill);
  font-size: 13px;
  font-family: var(--font-kai);
  letter-spacing: 2px;
  transition: all .18s ease;
}
.btn.primary {
  border: 1px solid transparent;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: var(--shadow-seal);
}
.btn.primary:hover:not(:disabled) { transform: translateY(-1px); box-shadow: var(--shadow-lift); }
.btn.primary:disabled { opacity: .45; cursor: not-allowed; }
.btn.ghost { border: 1px solid var(--line); background: transparent; color: var(--ink-soft); }
.btn.ghost:hover { border-color: var(--rouge); color: var(--rouge); }
</style>

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
/** NewSessionDialog — 新建编程会话：任务 + 工作区 + 权限档位 */
import { reactive, ref } from 'vue'

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'create', payload: { task: string; workspace: string; policy_mode: string; title?: string }): void
}>()

const props = defineProps<{ submitting?: boolean }>()

const form = reactive({
  title: '',
  task: '',
  workspace: '',
  policy_mode: 'supervised',
})

const localError = ref('')

const MODES = [
  { id: 'readonly', label: '只读', hint: '仅侦察与检索，不写文件、不跑命令' },
  { id: 'supervised', label: '监督', hint: '低风险直接放行，写/执行需人工审批（默认）' },
  { id: 'trusted', label: '信任', hint: '低/中风险放行，仅高风险需审批' },
]

function submit() {
  localError.value = ''
  if (!form.task.trim()) { localError.value = '请填写任务描述'; return }
  if (!form.workspace.trim()) { localError.value = '请填写工作区目录'; return }
  emit('create', {
    task: form.task.trim(),
    workspace: form.workspace.trim(),
    policy_mode: form.policy_mode,
    title: form.title.trim() || undefined,
  })
}
</script>

<template>
  <div class="ns-mask" @click.self="emit('close')">
    <section class="ns-dialog paper-card" role="dialog" aria-label="新建编程会话">
      <header class="ns-hd">
        <span class="seal ns-seal">枢</span>
        <div>
          <h2 class="ns-title">新建编程会话</h2>
          <p class="ns-sub">把任务交给编程框架：先侦察规划，经你确认后再动手</p>
        </div>
        <button class="ns-x" type="button" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="ns-body">
        <label class="ns-field">
          <span class="ns-label">会话标题 <em>可选</em></span>
          <input v-model="form.title" class="ns-input" maxlength="60" placeholder="留空则取任务前 40 字" />
        </label>

        <label class="ns-field">
          <span class="ns-label">任务描述</span>
          <textarea
            v-model="form.task"
            class="ns-input ns-textarea"
            rows="4"
            maxlength="4000"
            placeholder="例如：为 backend/app/coding/sandbox.py 增加命令白名单的可配置项，并补测试"
          />
        </label>

        <label class="ns-field">
          <span class="ns-label">工作区目录</span>
          <input
            v-model="form.workspace"
            class="ns-input ns-mono"
            placeholder="绝对路径，须落在允许的根目录白名单内"
          />
          <small class="ns-hint">
            沙箱硬边界：所有读写与命令都被限制在该目录内，越界与凭据文件一律拒绝。
          </small>
        </label>

        <div class="ns-field">
          <span class="ns-label">权限档位</span>
          <div class="ns-modes">
            <button
              v-for="m in MODES"
              :key="m.id"
              type="button"
              class="ns-mode"
              :class="{ 'ns-mode--on': form.policy_mode === m.id }"
              @click="form.policy_mode = m.id"
            >
              <strong>{{ m.label }}</strong>
              <span>{{ m.hint }}</span>
            </button>
          </div>
        </div>

        <p v-if="localError" class="ns-err">{{ localError }}</p>
      </div>

      <footer class="ns-ft">
        <button class="ns-btn ns-btn--ghost" type="button" @click="emit('close')">取消</button>
        <button class="ns-btn ns-btn--primary" type="button" :disabled="props.submitting" @click="submit">
          {{ props.submitting ? '创建中…' : '创建会话' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.ns-mask {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 24px;
  background: color-mix(in srgb, var(--bg-soft) 62%, transparent);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}
.ns-dialog {
  width: min(620px, 100%);
  max-height: 88vh;
  overflow: auto;
  animation: ns-in .22s cubic-bezier(.4, 0, .2, 1);
}
@keyframes ns-in { from { opacity: 0; transform: translateY(14px) scale(.985); } }
.ns-hd {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--line-soft);
}
.ns-seal { width: 34px; height: 34px; font-size: 17px; }
.ns-title { font-family: var(--font-kai); font-size: 21px; letter-spacing: 3px; color: var(--ink); }
.ns-sub { margin-top: 3px; font-size: 12px; color: var(--ink-muted); letter-spacing: .5px; }
.ns-x {
  margin-left: auto;
  width: 30px; height: 30px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: transparent;
  color: var(--ink-soft);
  font-size: 18px;
  line-height: 1;
}
.ns-x:hover { color: var(--cinnabar); border-color: var(--line-cinnabar); }

.ns-body { display: grid; gap: 16px; padding: 18px 22px; }
.ns-field { display: grid; gap: 7px; }
.ns-label {
  font-size: 12px;
  letter-spacing: 1.5px;
  color: var(--ink-soft);
  font-weight: 600;
}
.ns-label em { font-style: normal; color: var(--ink-muted); font-weight: 400; font-size: 11px; }
.ns-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card-solid);
  color: var(--ink);
  font-size: 13.5px;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.ns-input:focus { outline: none; border-color: var(--rouge); box-shadow: 0 0 0 3px var(--rouge-glow); }
.ns-textarea { resize: vertical; line-height: 1.65; }
.ns-mono { font-family: var(--font-mono); font-size: 12.5px; }
.ns-hint { color: var(--ink-muted); font-size: 11.5px; line-height: 1.6; }

.ns-modes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.ns-mode {
  display: grid;
  gap: 5px;
  padding: 11px 12px;
  text-align: left;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card-solid);
  transition: all .18s ease;
}
.ns-mode strong { font-size: 13px; color: var(--ink); font-family: var(--font-kai); letter-spacing: 2px; }
.ns-mode span { font-size: 11px; line-height: 1.55; color: var(--ink-muted); }
.ns-mode:hover { border-color: var(--gold-line); }
.ns-mode--on {
  border-color: var(--rouge);
  background: color-mix(in srgb, var(--rouge) 10%, var(--card-solid));
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.ns-err { color: var(--cinnabar); font-size: 12.5px; }

.ns-ft {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 22px 18px;
  border-top: 1px solid var(--line-soft);
}
.ns-btn {
  padding: 9px 20px;
  border-radius: var(--radius-small);
  border: 1px solid transparent;
  font-size: 13.5px;
  letter-spacing: 1px;
  transition: all .18s ease;
}
.ns-btn--ghost { background: transparent; border-color: var(--line); color: var(--ink-soft); }
.ns-btn--ghost:hover { border-color: var(--ink-muted); color: var(--ink); }
.ns-btn--primary {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: 0 2px 12px var(--cinnabar-glow);
}
.ns-btn--primary:hover { transform: translateY(-1px); box-shadow: var(--shadow-lift); }
.ns-btn--primary:disabled { opacity: .6; transform: none; cursor: not-allowed; }

@media (max-width: 640px) {
  .ns-modes { grid-template-columns: 1fr; }
}
</style>

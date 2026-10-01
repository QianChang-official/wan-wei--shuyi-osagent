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
 * DetailsPanel —— 右栏详情：智能体档案、上下文玉环（真实估算）、
 * 运行记录（人工审查可放行/驳回，进行中可取消；有活件时 4s 轮询）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useAgents } from '@/composables/useAgents'
import { useChat } from '@/composables/useChat'
import { useRuns } from '@/composables/useRuns'
import { api } from '@/api/client'
import type { ContextSize } from '@/api/types'
import { formatTime, formatTokens } from '@/utils/format'
import { runStatusLabel, runStatusTone } from '@/utils/platformEnums'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'edit-agent'): void
  (e: 'delete-agent'): void
}>()

const { selectedAgent } = useAgents()
const { acting, loading, error, actionError, agentRuns, hasActive, refresh, approve, cancel } = useRuns()

const ctx = ref<ContextSize | null>(null)
const contextError = ref('')
const contextLoading = ref(false)
let contextVersion = 0
let mounted = true
const { revision: chatRevision } = useChat()
let pollTimer: number | undefined

const runs = computed(() => agentRuns(selectedAgent.value?.id ?? null).value.slice(0, 12))

/** 玉环弧度：r=52 的圆周 ≈ 326.7 */
const RING_LEN = 2 * Math.PI * 52
const ctxRatio = computed(() => {
  if (!ctx.value || ctx.value.limit <= 0) return 0
  return Math.min(1, ctx.value.total_tokens / ctx.value.limit)
})
const ringDash = computed(() => `${(ctxRatio.value * RING_LEN).toFixed(1)} ${RING_LEN.toFixed(1)}`)

async function refreshContext() {
  const version = ++contextVersion
  const id = selectedAgent.value?.id
  ctx.value = null
  contextError.value = ''
  if (!id) { contextLoading.value = false; return }
  contextLoading.value = true
  try {
    const result = await api.contextSize(id)
    if (version === contextVersion && mounted) ctx.value = result
  } catch (err) {
    if (version === contextVersion && mounted) contextError.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (version === contextVersion && mounted) contextLoading.value = false
  }
}

function reschedulePoll() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = undefined
  if (mounted && hasActive(selectedAgent.value?.id ?? null)) {
    pollTimer = window.setInterval(refresh, 4000)
  }
}

watch(selectedAgent, async () => {
  await Promise.all([refresh(), refreshContext()])
  reschedulePoll()
})

watch(runs, () => reschedulePoll())
watch(chatRevision, async () => {
  await Promise.all([refresh(), refreshContext()])
  reschedulePoll()
})

onMounted(async () => {
  await Promise.all([refresh(), refreshContext()])
  reschedulePoll()
})

onUnmounted(() => {
  mounted = false
  contextVersion++
  if (pollTimer) window.clearInterval(pollTimer)
})

const PERMISSION_LABELS: Record<string, string> = {
  fs_read: '读文件', fs_write: '写文件', shell: '命令行', network: '网络', git: 'Git',
}
</script>

<template>
  <aside class="details" aria-label="智能体详情">
    <button class="mini-btn close-details" type="button" aria-label="关闭详情栏" @click="emit('close')">关闭详情</button>
    <template v-if="selectedAgent">
      <!-- 档案卡 -->
      <GfCard title="智能体档案" :seal="selectedAgent.name.charAt(0)">
        <dl class="profile">
          <div><dt>角色</dt><dd>{{ selectedAgent.role || '—' }}</dd></div>
          <div><dt>人格</dt><dd>{{ selectedAgent.persona || '—' }}</dd></div>
          <div><dt>目标</dt><dd class="goal">{{ selectedAgent.goal || '—' }}</dd></div>
          <div><dt>绑定模型</dt><dd>{{ selectedAgent.provider_pid ? `${selectedAgent.provider_pid} / ${selectedAgent.model || '默认'}` : '—（跟随网关默认）' }}</dd></div>
          <div>
            <dt>权限</dt>
            <dd class="perms">
              <GfTag
                v-for="(on, key) in selectedAgent.permissions"
                v-show="on"
                :key="key"
                :tone="key === 'shell' || key === 'network' ? 'rouge' : 'bamboo'"
              >{{ PERMISSION_LABELS[key] ?? key }}</GfTag>
              <span v-if="!Object.values(selectedAgent.permissions).some(Boolean)" class="muted">无</span>
            </dd>
          </div>
        </dl>
        <template #footer>
          <div class="card-actions">
            <button class="mini-btn" type="button" @click="emit('edit-agent')">编辑</button>
            <button class="mini-btn danger" type="button" @click="emit('delete-agent')">删除</button>
          </div>
        </template>
      </GfCard>

      <!-- 上下文玉环 -->
      <GfCard title="上下文" seal="环">
        <p v-if="contextLoading" role="status">正在加载上下文…</p>
        <p v-else-if="contextError" role="alert">{{ contextError }} <button type="button" @click="refreshContext">重试</button></p>
        <div v-else class="ring-wrap">
          <svg viewBox="0 0 120 120" width="104" height="104" role="img"
            :aria-label="`上下文用量 ${ctx ? formatTokens(ctx.total_tokens) : '—'} / ${ctx ? formatTokens(ctx.limit) : '—'}`">
            <circle cx="60" cy="60" r="52" fill="none" stroke="var(--line-soft)" stroke-width="9" />
            <circle
              cx="60" cy="60" r="52" fill="none"
              :stroke="ctxRatio > 0.85 ? 'var(--cinnabar)' : 'var(--rouge)'"
              stroke-width="9" stroke-linecap="round"
              :stroke-dasharray="ringDash"
              transform="rotate(-90 60 60)"
              opacity=".9"
            />
            <circle cx="60" cy="60" r="40" fill="none" stroke="var(--gold-line)" stroke-width="1" stroke-dasharray="2 4" />
            <text x="60" y="57" text-anchor="middle" class="ring-num">{{ ctx ? Math.round(ctxRatio * 100) + '%' : '—' }}</text>
            <text x="60" y="74" text-anchor="middle" class="ring-sub">{{ ctx ? formatTokens(ctx.total_tokens) + ' / ' + formatTokens(ctx.limit) : '未取到' }}</text>
          </svg>
          <ul v-if="ctx" class="ctx-list">
            <li><span>系统提示</span><b>{{ formatTokens(ctx.system_prompt) }}</b></li>
            <li><span>记忆指令</span><b>{{ formatTokens(ctx.memory_instructions) }}</b></li>
            <li><span>历史运行</span><b>{{ formatTokens(ctx.history) }}</b></li>
          </ul>
        </div>
      </GfCard>

      <!-- 运行记录 -->
      <GfCard title="运行" seal="运" class="runs-card">
        <p v-if="loading && !runs.length" role="status">正在加载运行…</p>
        <p v-if="error" role="alert">{{ error }} <button type="button" @click="refresh">重试</button></p>
        <p v-if="actionError" role="alert">{{ actionError }}</p>
        <GfEmpty v-if="!loading && !error && runs.length === 0" text="尚无运行记录" />
        <div v-if="runs.length" class="run-list">
          <div v-for="run in runs" :key="run.id" class="run-row">
            <div class="rr-head">
              <GfTag :tone="runStatusTone(run.status)">{{ runStatusLabel(run.status) }}</GfTag>
              <span class="rr-kind">{{ { solo: '独立', team: '团队', chat: '对话', subagent: '子代理' }[run.kind] ?? run.kind }}</span>
              <time>{{ formatTime(run.created_at) }}</time>
            </div>
            <p class="rr-task">{{ run.task || run.goal || '（对话轮）' }}</p>
            <p v-if="run.error" class="rr-error">{{ run.error }}</p>
            <p v-if="run.kind === 'chat' && run.status === 'awaiting_review'" class="rr-task">工具操作须在会话内逐项确认，不能批量放行。</p>
            <div v-if="run.kind !== 'chat'" class="rr-steps">
              <span
                v-for="step in run.steps"
                :key="step.id"
                class="step-dot"
                :class="`st-${step.status}`"
                :title="`${step.title}：${step.status}`"
              ></span>
            </div>
            <div v-if="run.status === 'awaiting_review' && run.kind !== 'chat'" class="rr-actions">
              <button
                class="mini-btn" type="button" :disabled="!!acting"
                @click="approve(run.id, true)"
              >放行</button>
              <button
                class="mini-btn danger" type="button" :disabled="!!acting"
                @click="approve(run.id, false)"
              >驳回</button>
            </div>
            <div v-else-if="run.status === 'running' || run.status === 'queued' || run.status === 'awaiting_review'" class="rr-actions">
              <button
                class="mini-btn danger" type="button" :disabled="!!acting"
                @click="cancel(run.id)"
              >取消</button>
            </div>
          </div>
        </div>
      </GfCard>
    </template>
    <GfEmpty v-else text="选择一位智能体后，这里展示它的档案、上下文与运行" />
  </aside>
</template>

<style scoped>
.details {
  height: 100%;
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  border-left: 1px solid var(--line);
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

/* 档案 */
.profile { display: flex; flex-direction: column; gap: 8px; }
.profile > div { display: flex; gap: 10px; font-size: 12.5px; }
.profile dt { flex: none; width: 56px; color: var(--ink-muted); letter-spacing: 2px; }
.profile dd { flex: 1; min-width: 0; overflow-wrap: break-word; }
.profile .goal { font-family: var(--font-kai); }
.perms { display: flex; flex-wrap: wrap; gap: 4px; }
.muted { color: var(--ink-muted); }
.card-actions { display: flex; gap: 8px; justify-content: flex-end; }

.mini-btn {
  padding: 4px 14px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--gold-line);
  background: var(--card-solid);
  color: var(--ink-soft);
  font-size: 12px;
  letter-spacing: 1px;
  transition: all .18s ease;
}
.mini-btn:hover { border-color: var(--rouge); color: var(--rouge); box-shadow: var(--shadow-glow-rouge); }
.mini-btn.danger:hover { border-color: var(--cinnabar); color: var(--cinnabar); box-shadow: 0 0 12px var(--cinnabar-glow); }
.mini-btn:disabled { opacity: .5; cursor: wait; }

/* 玉环 */
.ring-wrap { display: flex; align-items: center; gap: 14px; }
.ring-num { font-size: 17px; font-weight: 700; fill: var(--ink); font-family: var(--font-kai); }
.ring-sub { font-size: 9px; fill: var(--ink-muted); }
.ctx-list { flex: 1; list-style: none; display: flex; flex-direction: column; gap: 6px; font-size: 12px; }
.ctx-list li { display: flex; justify-content: space-between; color: var(--ink-soft); }
.ctx-list b { font-family: var(--font-mono); color: var(--ink); }

/* 运行 */
.run-list { display: flex; flex-direction: column; gap: 10px; }
.run-row {
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  padding: 8px 10px;
  background: var(--card-solid);
}
.rr-head { display: flex; align-items: center; gap: 8px; }
.rr-kind { font-size: 11px; color: var(--ink-muted); }
.rr-head time { margin-left: auto; font-size: 11px; color: var(--ink-muted); font-family: var(--font-mono); }
.rr-task {
  margin-top: 4px;
  font-size: 12.5px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.rr-error { margin-top: 4px; font-size: 11.5px; color: var(--cinnabar); }
.rr-steps { display: flex; gap: 4px; margin-top: 6px; }
.step-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--line); }
.step-dot.st-done { background: var(--bamboo); }
.step-dot.st-running { background: var(--dai); animation: pulse 1.6s ease-in-out infinite; }
.step-dot.st-awaiting_review { background: var(--gold); animation: pulse 1.6s ease-in-out infinite; }
.step-dot.st-rejected { background: var(--cinnabar); }
.step-dot.st-skipped { background: var(--line); opacity: .5; }
@keyframes pulse { 50% { opacity: .45; } }
@media (prefers-reduced-motion: reduce) { .step-dot { animation: none !important; } }
.rr-actions { display: flex; gap: 8px; margin-top: 8px; }
</style>

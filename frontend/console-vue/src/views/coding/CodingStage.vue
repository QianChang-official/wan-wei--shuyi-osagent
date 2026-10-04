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
/** CodingStage — 中栏：计划步骤 + 事件时间线 + 执行动作条 */
import { computed, ref } from 'vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import { formatTime } from '@/utils/format'
import type { CodingEvent, SessionDetail } from '@/api/coding'

const props = defineProps<{
  detail: SessionDetail | null
  events: CodingEvent[]
  isRunning: boolean
  busy: Record<string, boolean>
}>()

const emit = defineEmits<{
  (e: 'plan', useLlm: boolean): void
  (e: 'confirm', approved: boolean): void
  (e: 'run'): void
  (e: 'resume'): void
}>()

const useLlm = ref(false)
const openStep = ref<string>('')

const plan = computed(() => props.detail?.plan || null)
const steps = computed(() => plan.value?.steps || [])
const state = computed(() => props.detail?.state || '')
const confirmed = computed(() => Boolean(plan.value?.confirmed))
const canRun = computed(() => confirmed.value && state.value !== 'running' && state.value !== 'paused')
const canResume = computed(() => state.value === 'paused')
const progressPct = computed(() => Math.round((plan.value?.progress || 0) * 100))

const STEP_ICON: Record<string, string> = {
  pending: '○', in_progress: '◐', done: '●', skipped: '◌', failed: '✕',
}
const STEP_TONE: Record<string, 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'> = {
  pending: 'ink', in_progress: 'rouge', done: 'bamboo', skipped: 'ink', failed: 'rouge',
}

/** 事件 → 展示描述 */
function describe(e: CodingEvent): { icon: string; label: string; detail: string; tone: string } {
  const p = e.payload || {}
  switch (e.type) {
    case 'session_created': return { icon: '✦', label: '会话创建', detail: String(p.workspace || ''), tone: 'dai' }
    case 'plan_proposed': return { icon: '☰', label: '计划已生成', detail: `共 ${p.plan?.total ?? 0} 步`, tone: 'gold' }
    case 'plan_confirmed': return { icon: '✓', label: p.approved ? '计划已确认' : '计划被否决', detail: '', tone: p.approved ? 'bamboo' : 'rouge' }
    case 'step_started': return {
      icon: p.finished ? '●' : '▶',
      label: p.finished ? '步骤结束' : '步骤开始',
      detail: String(p.step?.title || ''),
      tone: p.finished ? 'bamboo' : 'rouge',
    }
    case 'tool_called': return { icon: '⚙', label: '调用工具', detail: `${p.tool_id}`, tone: 'dai' }
    case 'tool_result': return {
      icon: p.result?.status === 'ok' ? '✓' : '!',
      label: `工具返回 · ${p.result?.status || ''}`,
      detail: String(p.result?.summary || ''),
      tone: p.result?.status === 'ok' ? 'bamboo' : (p.result?.status === 'denied' ? 'rouge' : 'gold'),
    }
    case 'approval_requested': return { icon: '⏸', label: '请求人工审批', detail: String(p.approval?.summary || ''), tone: 'gold' }
    case 'approval_resolved': return {
      icon: p.approval?.status === 'approved' ? '✓' : '✕',
      label: `审批${p.approval?.status === 'approved' ? '放行' : '拒绝'}`,
      detail: String(p.approval?.summary || ''),
      tone: p.approval?.status === 'approved' ? 'bamboo' : 'rouge',
    }
    case 'subagent_spawned': return { icon: '◈', label: '委派子智能体', detail: `${p.subagent?.role_label || ''}：${p.subagent?.task || ''}`, tone: 'dai' }
    case 'subagent_finished': return {
      icon: '◆', label: '子智能体完成',
      detail: String(p.subagent?.findings?.summary || ''),
      tone: p.subagent?.status === 'done' ? 'bamboo' : 'rouge',
    }
    case 'memory_written': return { icon: '❖', label: '写入可审计记忆', detail: `${p.title || ''}（${p.kind || ''}）`, tone: 'gold' }
    case 'memory_forgotten': return { icon: '⌫', label: '记忆已删除（含取证）', detail: String(p.capsule_id || ''), tone: 'rouge' }
    case 'guard_tripped': return { icon: '⛔', label: '护栏熔断', detail: String(p.message || ''), tone: 'rouge' }
    case 'session_state': return { icon: '↻', label: '状态变更', detail: String(p.state || ''), tone: 'ink' }
    case 'workflow_started': return { icon: '⑃', label: '工作流启动', detail: `${(p.nodes || []).length} 节点`, tone: 'dai' }
    case 'workflow_finished': return { icon: '⑃', label: '工作流结束', detail: `成功 ${p.succeeded} / 失败 ${p.failed} / 阻断 ${p.blocked}`, tone: p.ok ? 'bamboo' : 'gold' }
    case 'assistant_message': return { icon: '✎', label: '框架输出', detail: String(p.text || '').slice(0, 120), tone: 'ink' }
    case 'error': return { icon: '✕', label: '错误', detail: String(p.message || ''), tone: 'rouge' }
    default: return { icon: '·', label: e.type, detail: '', tone: 'ink' }
  }
}

const visibleEvents = computed(() => [...props.events].reverse().slice(0, 120))
</script>

<template>
  <section class="st">
    <GfEmpty v-if="!detail" text="从左侧选择一个会话，或新建一个" />

    <template v-else>
      <!-- 任务头 -->
      <header class="st-hd">
        <div class="st-hd-main">
          <h2 class="st-task">{{ detail.title || '未命名会话' }}</h2>
          <p class="st-desc">{{ detail.task }}</p>
        </div>
        <div class="st-hd-side">
          <GfTag :tone="state === 'done' ? 'bamboo' : (state === 'running' ? 'rouge' : 'gold')">
            {{ detail.state_label }}
          </GfTag>
          <span class="st-ws" :title="detail.workspace">{{ detail.workspace }}</span>
        </div>
      </header>

      <!-- 动作条 -->
      <div class="st-actions">
        <button class="st-btn" type="button" :disabled="busy.plan || isRunning" @click="emit('plan', useLlm)">
          {{ busy.plan ? '规划中…' : (plan?.total ? '重新规划' : '生成计划') }}
        </button>
        <label class="st-toggle" title="用模型网关润色步骤说明（未配置则自动回退启发式）">
          <input v-model="useLlm" type="checkbox" />
          <span>模型润色</span>
        </label>
        <button
          v-if="plan?.total && !confirmed"
          class="st-btn st-btn--primary"
          type="button"
          :disabled="busy.confirm"
          @click="emit('confirm', true)"
        >
          确认并执行
        </button>
        <button
          v-if="plan?.total && confirmed"
          class="st-btn st-btn--primary"
          type="button"
          :disabled="!canRun || busy.run"
          @click="emit('run')"
        >
          {{ isRunning ? '执行中…' : '开始执行' }}
        </button>
        <button
          v-if="canResume"
          class="st-btn st-btn--gold"
          type="button"
          :disabled="busy.resume"
          @click="emit('resume')"
        >
          处理审批后续跑
        </button>
        <button
          v-if="plan?.total && !confirmed"
          class="st-btn st-btn--ghost"
          type="button"
          @click="emit('confirm', false)"
        >
          否决
        </button>
      </div>

      <!-- 计划 -->
      <section class="st-plan">
        <div class="st-plan-hd">
          <h3 class="st-sec-title">执行计划</h3>
          <span class="st-plan-meta">
            {{ plan?.done || 0 }}/{{ plan?.total || 0 }} 步
            <em v-if="plan?.source === 'llm'">· 模型润色</em>
            <em v-else-if="plan?.total">· 启发式</em>
          </span>
          <span class="st-bar"><i :style="{ width: progressPct + '%' }" /></span>
        </div>
        <p v-if="plan?.rationale" class="st-rationale">{{ plan.rationale }}</p>
        <ol v-if="steps.length" class="st-steps">
          <li
            v-for="(s, i) in steps"
            :key="s.id"
            class="st-step"
            :class="['st-step--' + s.state, { 'st-step--open': openStep === s.id }]"
            @click="openStep = openStep === s.id ? '' : s.id"
          >
            <span class="st-step-no">{{ STEP_ICON[s.state] || '○' }}</span>
            <div class="st-step-body">
              <div class="st-step-line">
                <span class="st-step-title">{{ i + 1 }}. {{ s.title }}</span>
                <GfTag :tone="STEP_TONE[s.state] || 'ink'">{{ s.state_label }}</GfTag>
                <code v-if="s.tool_hint" class="st-step-hint">{{ s.tool_hint }}</code>
              </div>
              <p class="st-step-detail">{{ s.detail }}</p>
              <pre v-if="openStep === s.id && s.result" class="st-step-result">{{ s.result }}</pre>
            </div>
          </li>
        </ol>
        <p v-else class="st-hint">尚未生成计划。点上方「生成计划」，框架会先侦察工作区再给出步骤。</p>
      </section>

      <!-- 时间线 -->
      <section class="st-timeline">
        <h3 class="st-sec-title">事件时间线</h3>
        <ul class="st-events">
          <li v-for="e in visibleEvents" :key="e.seq" class="st-ev" :data-tone="describe(e).tone">
            <span class="st-ev-icon">{{ describe(e).icon }}</span>
            <div class="st-ev-body">
              <div class="st-ev-line">
                <span class="st-ev-label">{{ describe(e).label }}</span>
                <time class="st-ev-time">{{ formatTime(e.at) }}</time>
              </div>
              <p v-if="describe(e).detail" class="st-ev-detail">{{ describe(e).detail }}</p>
            </div>
          </li>
          <li v-if="!visibleEvents.length" class="st-ev st-ev--empty">暂无事件</li>
        </ul>
      </section>
    </template>
  </section>
</template>

<style scoped>
.st {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}

.st-hd {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px 22px 12px;
  border-bottom: 1px solid var(--line-soft);
}
.st-hd-main { flex: 1 1 auto; min-width: 0; }
.st-task { font-family: var(--font-kai); font-size: 20px; letter-spacing: 2px; color: var(--ink); }
.st-desc { margin-top: 4px; font-size: 12.5px; line-height: 1.65; color: var(--ink-soft); }
.st-hd-side { display: grid; gap: 6px; justify-items: end; flex: 0 0 auto; }
.st-ws {
  max-width: 260px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--ink-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.st-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 12px 22px;
  border-bottom: 1px solid var(--line-soft);
  background: color-mix(in srgb, var(--bg-soft) 30%, transparent);
}
.st-btn {
  padding: 7px 16px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line);
  background: var(--card-solid);
  color: var(--ink-soft);
  font-size: 12.5px;
  letter-spacing: 1px;
  transition: all .18s ease;
}
.st-btn:hover:not(:disabled) { border-color: var(--gold-line); color: var(--ink); transform: translateY(-1px); }
.st-btn:disabled { opacity: .5; cursor: not-allowed; }
.st-btn--primary {
  border-color: transparent;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: 0 2px 12px var(--cinnabar-glow);
}
.st-btn--gold {
  border-color: var(--gold-line);
  background: color-mix(in srgb, var(--gold) 16%, transparent);
  color: color-mix(in srgb, var(--gold) 72%, var(--ink));
}
.st-btn--ghost { background: transparent; }
.st-toggle { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--ink-muted); cursor: pointer; }

/* 计划区最多占中栏 46%，超出自身滚动；时间线吃掉剩余高度并独立滚动，
   保证两块内容都始终可见（长计划不会把时间线挤出视口）。 */
.st-plan {
  flex: 0 1 auto;
  max-height: 46%;
  overflow-y: auto;
  padding: 14px 22px;
  border-bottom: 1px solid var(--line-soft);
}
.st-timeline {
  flex: 1 1 auto;
  min-height: 140px;
  overflow-y: auto;
  padding: 14px 22px;
}
.st-sec-title {
  font-family: var(--font-kai);
  font-size: 14px;
  letter-spacing: 3px;
  color: var(--ink-soft);
  margin-bottom: 10px;
}
.st-plan-hd { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.st-plan-hd .st-sec-title { margin-bottom: 0; }
.st-plan-meta { font-size: 11.5px; color: var(--ink-muted); }
.st-plan-meta em { font-style: normal; color: var(--gold); }
.st-bar { flex: 1 1 auto; height: 4px; border-radius: 999px; background: var(--line-soft); overflow: hidden; }
.st-bar i { display: block; height: 100%; background: linear-gradient(90deg, var(--rouge), var(--gold)); transition: width .35s ease; }
.st-rationale { font-size: 11.5px; color: var(--ink-muted); line-height: 1.7; margin-bottom: 10px; }

.st-steps { display: grid; gap: 6px; }
.st-step {
  display: flex;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  background: var(--card);
  cursor: pointer;
  transition: border-color .16s ease, background .16s ease;
}
.st-step:hover { border-color: var(--gold-line); }
.st-step--open { border-color: var(--rouge); background: color-mix(in srgb, var(--rouge) 5%, var(--card)); }
.st-step--done .st-step-title { color: var(--ink-soft); }
.st-step--failed { border-color: var(--line-cinnabar); }
.st-step-no { flex: 0 0 auto; width: 16px; color: var(--gold); font-size: 13px; line-height: 1.5; }
.st-step-body { flex: 1 1 auto; min-width: 0; }
.st-step-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.st-step-title { font-size: 13px; color: var(--ink); font-weight: 600; }
.st-step-hint {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-muted);
  background: var(--line-soft);
  padding: 1px 6px;
  border-radius: 4px;
}
.st-step-detail { margin-top: 4px; font-size: 11.5px; line-height: 1.65; color: var(--ink-muted); }
.st-step-result {
  margin-top: 8px;
  padding: 10px;
  max-height: 240px;
  overflow: auto;
  border-radius: var(--radius-small);
  background: var(--bg-soft);
  border: 1px solid var(--line-soft);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
  color: var(--ink-soft);
  white-space: pre-wrap;
  word-break: break-word;
}
.st-hint { font-size: 12px; color: var(--ink-muted); line-height: 1.7; }

.st-events { display: grid; gap: 2px; }
.st-ev { display: flex; gap: 10px; padding: 7px 8px; border-radius: var(--radius-small); }
.st-ev:hover { background: var(--line-soft); }
.st-ev-icon { flex: 0 0 auto; width: 16px; text-align: center; font-size: 12px; line-height: 1.5; color: var(--ink-muted); }
.st-ev[data-tone='bamboo'] .st-ev-icon { color: var(--bamboo); }
.st-ev[data-tone='rouge'] .st-ev-icon { color: var(--cinnabar); }
.st-ev[data-tone='gold'] .st-ev-icon { color: var(--gold); }
.st-ev[data-tone='dai'] .st-ev-icon { color: var(--dai); }
.st-ev-body { flex: 1 1 auto; min-width: 0; }
.st-ev-line { display: flex; align-items: baseline; gap: 10px; }
.st-ev-label { font-size: 12.5px; color: var(--ink); }
.st-ev-time { margin-left: auto; font-size: 10.5px; color: var(--ink-muted); font-family: var(--font-mono); }
.st-ev-detail { font-size: 11.5px; color: var(--ink-muted); line-height: 1.6; word-break: break-word; }
.st-ev--empty { color: var(--ink-muted); font-size: 12px; justify-content: center; }
</style>

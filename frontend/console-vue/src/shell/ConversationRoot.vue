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
 * ConversationRoot —— 中栏会话区：
 * 未选智能体时显示月洞门英雄位；选中后为 头部信息 + 消息流 + 输入坞。
 * 消息经 markdown-lite 渲染（HTML 全转义，链接仅 http/https）。
 * 发送失败如实呈错误气泡；网关未就绪时给出去往「模型接入」的引导。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useAgents } from '@/composables/useAgents'
import { useChat } from '@/composables/useChat'
import type { ChatMessage } from '@/composables/useChat'
import { renderMarkdown } from '@/utils/markdown'
import { formatTime } from '@/utils/format'
import { GEAR_LABELS } from '@/utils/platformEnums'
import GfTag from '@/components/gf/GfTag.vue'

const emit = defineEmits<{
  (e: 'new-agent'): void
  (e: 'open-settings', section?: string): void
  (e: 'toggle-details'): void
}>()

const DEPTHS = [
  { value: 'low', label: '浅思' },
  { value: 'medium', label: '中思' },
  { value: 'high', label: '深思' },
  { value: 'xhigh', label: '极思' },
  { value: 'max', label: '彻思' },
  { value: 'ultracode', label: '超码' },
] as const

const { selectedAgent, loading, error, authError, refresh } = useAgents()
const { sending: sendingByAgent, messagesOf, send, cancel, clear, confirmCommand } = useChat()

/** 过程时间线统计与工具图标 */
function thinkingCount(msg: ChatMessage): number {
  return msg.meta?.process_steps?.filter(s => s.kind === 'thinking').length ?? 0
}
function toolCount(msg: ChatMessage): number {
  return msg.meta?.process_steps?.filter(s => s.kind === 'tool_call').length ?? 0
}
function toolIcon(tool = ''): string {
  if (tool.includes('run_command')) return '⌨'
  if (tool.includes('write_file')) return '✎'
  if (tool.includes('read_file')) return '👁'
  if (tool.includes('open_path')) return '↗'
  if (tool.includes('device_')) return '🖥'
  if (tool.includes('user_dirs')) return '🗂'
  if (tool.includes('current_time')) return '⏱'
  return '🔧'
}

const draft = ref('')
const depth = ref<string>('')
const gear = ref<string>('')
const scrollEl = ref<HTMLElement | null>(null)

const sending = computed(() => !!selectedAgent.value && !!sendingByAgent[selectedAgent.value.id])
const messages = computed(() => (selectedAgent.value ? messagesOf(selectedAgent.value.id) : []))

const unresolved = computed(() => messages.value.some(m => m.confirmations?.some(c => c.state === 'pending' || c.state === 'submitting')))
watch(() => selectedAgent.value?.id, () => { draft.value = '' })

watch(selectedAgent, (agent) => {
  depth.value = agent?.depth ?? ''
  gear.value = agent?.gear ?? ''
  scrollToBottom()
}, { immediate: true })

watch(() => messages.value.length, () => scrollToBottom())

async function scrollToBottom() {
  await nextTick()
  const el = scrollEl.value
  if (el) el.scrollTop = el.scrollHeight
}

async function onSend() {
  const agent = selectedAgent.value
  const text = draft.value.trim()
  if (!agent || !text || sending.value || unresolved.value) return
  draft.value = ''
  await send(agent, text, { depth: depth.value, gear: gear.value })
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    onSend()
  }
}

function onClear() {
  const agent = selectedAgent.value
  if (agent && !sending.value && !unresolved.value && window.confirm('清空此页会话并开始新的上下文？后端运行记录不会删除。')) {
    clear(agent.id)
  }
}

defineExpose({ scrollEl })
</script>

<template>
  <section class="conversation">
    <!-- 英雄位：未选中智能体 -->
    <div v-if="!selectedAgent && (loading || error)" class="hero" :role="error ? 'alert' : 'status'">
      <h1>{{ loading ? '正在加载智能体…' : authError ? '访问鉴权失败' : '加载失败' }}</h1>
      <p>{{ error }}</p>
      <button v-if="error" type="button" @click="refresh">重试</button>
      <button v-if="error" type="button" @click="emit('open-settings', 'general')">设置访问密钥</button>
    </div>
    <div v-else-if="!selectedAgent" class="hero">
      <div class="hero-gate" aria-hidden="true">
        <svg viewBox="0 0 168 168" width="168" height="168">
          <circle cx="84" cy="84" r="60" fill="none" stroke="var(--gold-line)" stroke-width="2" />
          <circle cx="84" cy="84" r="60" fill="var(--rouge-glow)" opacity=".14" />
          <circle cx="84" cy="84" r="46" fill="none" stroke="var(--rouge)" stroke-width="1" opacity=".5"
            stroke-dasharray="3 5" />
          <g fill="var(--rouge)" opacity=".9">
            <circle cx="84" cy="64" r="7" /><circle cx="103" cy="78" r="7" />
            <circle cx="96" cy="100" r="7" /><circle cx="72" cy="100" r="7" />
            <circle cx="65" cy="78" r="7" />
          </g>
          <circle cx="84" cy="84" r="4.5" fill="var(--gold)" />
        </svg>
      </div>
      <h1 class="hero-title">宛委·枢忆</h1>
      <p class="hero-sub">月下梅影，纸上花朝 —— 选择左侧智能体开始对话，或创建一位新的</p>
      <button class="hero-cta" type="button" @click="emit('new-agent')">
        <span>＋</span> 新智能体
      </button>
    </div>

    <template v-else>
      <!-- 会话头部 -->
      <header class="conv-head">
        <div class="ch-title">
          <span class="ch-seal">{{ selectedAgent.name.charAt(0) }}</span>
          <div class="ch-names">
            <b>{{ selectedAgent.name }}</b>
            <i>{{ selectedAgent.role || '通用智能体' }}</i>
          </div>
          <GfTag :tone="'dai'">{{ DEPTHS.find(d => d.value === (depth || selectedAgent?.depth))?.label ?? selectedAgent?.depth }}</GfTag>
          <GfTag :tone="'gold'">{{ GEAR_LABELS[(gear || selectedAgent.gear) as keyof typeof GEAR_LABELS] ?? selectedAgent.gear }}</GfTag>
        </div>
        <div class="ch-actions">
          <button class="ch-btn" type="button" title="清空此页会话（待确认操作请先处理）" aria-label="清空此页会话" :disabled="sending || unresolved" @click="onClear">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
              stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
            </svg>
          </button>
          <button class="ch-btn" type="button" title="详情栏" aria-label="详情栏" @click="emit('toggle-details')">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
              stroke-width="1.8" stroke-linecap="round">
              <path d="M4 5h16M4 12h16M4 19h16" />
              <circle cx="19" cy="12" r="2" fill="currentColor" stroke="none" />
            </svg>
          </button>
        </div>
      </header>

      <!-- 消息流 -->
      <div ref="scrollEl" class="transcript">
        <p v-if="messages.length === 0" class="t-empty">
          此页仅缓存当前身份的最近 200 条消息；刷新或清空后重新开始。<br>发送内容会由后端保存为运行记录；续聊引用最近成功运行的有限上下文。<br>向「{{ selectedAgent.name }}」说第一句话吧。
        </p>
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="msg"
          :class="[msg.role, { failed: msg.failed }]"
        >
          <!-- 过程透明化：思考 + 工具调用时间线（流式期间实时追加，默认展开） -->
          <details v-if="msg.meta?.process_steps?.length" class="proc" :open="msg.pending">
            <summary>
              过程
              <span v-if="thinkingCount(msg)" class="proc-count">· {{ thinkingCount(msg) }} 段思考</span>
              <span class="proc-count">· {{ toolCount(msg) }} 次调用</span>
              <span v-if="msg.pending" class="proc-live">进行中…</span>
            </summary>
            <ol class="proc-list">
              <li v-for="(step, i) in msg.meta.process_steps" :key="i" :class="step.kind">
                <!-- 思考块：可折叠，显示耗时 -->
                <details v-if="step.kind === 'thinking'" class="think">
                  <summary>
                    💭 思考
                    <span v-if="step.duration_s != null" class="think-dur">持续了{{ step.duration_s >= 1 ? `${step.duration_s}秒` : '不到1秒' }}</span>
                  </summary>
                  <div class="think-body">{{ step.text }}</div>
                </details>
                <template v-else-if="step.kind === 'tool_call'">
                  <span class="proc-tool">{{ toolIcon(step.tool) }} {{ step.tool }}</span>
                  <code v-if="step.args">{{ step.args }}</code>
                </template>
                <template v-else>
                  <span class="proc-ret">↳ {{ step.tool }}</span>
                  <code v-if="step.result">{{ step.result }}</code>
                </template>
              </li>
            </ol>
          </details>
          <!-- 每张票据独立确认，最终答案不代表操作已执行。 -->
          <div v-for="ticket in msg.confirmations" :key="ticket.confirm_token" class="confirm-gate" :class="{ resolved: ticket.state !== 'pending' }">
            <div class="confirm-text">
              <b>操作确认 · {{ ticket.operation || '工具操作' }}</b>
              <code>{{ ticket.command || ticket.path || '查看上方过程中的操作与参数' }}</code>
              <pre v-if="ticket.content_preview">{{ ticket.content_preview }}</pre>
              <span v-if="ticket.bytes != null">{{ ticket.bytes }} 字节</span>
              <span v-if="ticket.expires_at">有效期至 {{ ticket.expires_at }}</span>
            </div>
            <div v-if="ticket.state === 'pending' || ticket.state === 'submitting'" class="confirm-actions">
              <button class="mini-btn danger" type="button" :disabled="ticket.state === 'submitting'" @click="confirmCommand(selectedAgent, msg, ticket.confirm_token, true)">{{ ticket.state === 'submitting' ? '正在确认…' : '放行执行' }}</button>
              <button class="mini-btn" type="button" :disabled="ticket.state === 'submitting'" @click="confirmCommand(selectedAgent, msg, ticket.confirm_token, false)">拒绝</button>
            </div>
            <p v-else role="status">{{ { approved: '后端已确认操作成功', denied: '已拒绝，未执行', error: '后端报告操作失败', unknown: '操作结果未知', cancelled: '本次运行已结束或票据失效；此处不再提交', expired: '确认期限已过，本页不再提交此票据；实际操作状态请核对运行记录' }[ticket.state] }}</p>
            <p v-if="ticket.error" role="alert">{{ ticket.error }}</p>
            <template v-if="ticket.result">
              <p v-if="ticket.result.exit_code != null">退出码：{{ ticket.result.exit_code }}</p>
              <pre v-if="ticket.result.stdout">{{ ticket.result.stdout }}</pre>
              <pre v-if="ticket.result.stderr || ticket.result.error || ticket.result.reason" role="alert">{{ ticket.result.stderr || ticket.result.error || ticket.result.reason }}</pre>
            </template>
          </div>
          <p v-if="msg.syncError" role="alert">{{ msg.syncError }}</p>
          <div class="bubble" :class="{ pending: msg.pending }">
            <span v-if="msg.pending" class="plum-wait" role="status" aria-label="处理运行中；流式显示过程，答案完成后显示">
              <i></i><i></i><i></i>
            </span>
            <!-- eslint-disable-next-line vue/no-v-html -- markdown.ts 已全量转义 -->
            <div v-else-if="msg.role === 'assistant'" class="md" v-html="renderMarkdown(msg.text)"></div>
            <div v-else class="plain">{{ msg.text }}</div>
          </div>
          <div class="msg-meta">
            <span>{{ formatTime(msg.time) }}</span>
            <template v-if="msg.meta">
              <GfTag v-if="msg.meta.engine" tone="bamboo">{{ msg.meta.engine }}</GfTag>
              <span v-if="msg.meta.provider_used">{{ msg.meta.provider_used }}</span>
              <span v-if="msg.meta.context_tokens != null">{{ msg.meta.context_tokens }} tok</span>
              <span v-if="msg.meta.status">运行状态：{{ msg.meta.status }}</span>
              <span v-if="msg.meta.memory_injection === 'ok'" title="已注入记忆指令">忆✓</span>
            </template>
            <button
              v-if="msg.failed && (msg.gatewayDown || msg.authError)"
              type="button"
              class="meta-cta"
              @click="emit('open-settings', msg.authError ? 'general' : 'providers')"
            >{{ msg.authError ? '更新访问密钥' : '去配置模型' }}</button>
          </div>
          <details v-if="msg.meta?.capabilities" class="proc"><summary>本次运行能力（后端报告）</summary><pre>{{ JSON.stringify(msg.meta.capabilities, null, 2) }}</pre></details>
        </div>
      </div>

      <!-- 输入坞 -->
      <footer class="composer">
        <p v-if="unresolved" class="hint" role="status">请先处理本次运行的待确认操作，再开始下一轮。</p>
        <textarea
          v-model="draft"
          aria-label="消息"
          rows="3"
          :placeholder="`与 ${selectedAgent.name} 对话…（Enter 发送，Shift+Enter 换行）`"
          :disabled="sending"
          @keydown="onKeydown"
        ></textarea>
        <div class="cp-bar">
          <div class="cp-opts">
            <select v-model="depth" class="cp-select" title="思考深度（默认随智能体）" aria-label="思考深度">
              <option value="">深度·随体</option>
              <option v-for="d in DEPTHS" :key="d.value" :value="d.value">{{ d.label }}</option>
            </select>
            <select v-model="gear" class="cp-select" title="工作档位（默认随智能体）" aria-label="工作档位">
              <option value="">档位·随体</option>
              <option value="human_review">人工审查</option>
              <option value="sandbox">沙盒工作</option>
              <option value="device">整台设备</option>
            </select>
          </div>
          <button v-if="sending" type="button" class="cp-send" @click="cancel(selectedAgent.id)">停止</button>
          <button
            v-else
            class="cp-send"
            type="button"
            :disabled="!draft.trim() || sending || unresolved"
            @click="onSend"
          >
            {{ sending ? '思量中…' : '发送' }}
          </button>
        </div>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.conversation {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
}

/* ── 英雄位 ── */
.hero {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
  padding: 40px;
  text-align: center;
}
.hero-gate { filter: drop-shadow(0 0 18px var(--rouge-glow)); }
.hero-title {
  font-family: var(--font-kai);
  font-size: 34px;
  letter-spacing: 10px;
  font-weight: 700;
  background: linear-gradient(120deg, var(--cinnabar), var(--rouge) 55%, var(--gold));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero-sub {
  color: var(--ink-soft);
  font-family: var(--font-kai);
  letter-spacing: 2px;
}
.hero-cta {
  margin-top: 8px;
  padding: 10px 26px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  font-family: var(--font-kai);
  font-size: 15px;
  letter-spacing: 3px;
  box-shadow: var(--shadow-seal);
  transition: transform .2s ease, box-shadow .2s ease;
}
.hero-cta:hover { transform: translateY(-2px); box-shadow: var(--shadow-lift); }

/* ── 会话头部 ── */
.conv-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--line-soft);
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
.ch-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.ch-seal {
  flex: none;
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  font-family: var(--font-kai);
  font-weight: 700;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: var(--shadow-seal);
}
.ch-names { display: flex; flex-direction: column; min-width: 0; }
.ch-names b { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ch-names i { font-style: normal; font-size: 11px; color: var(--ink-muted); }
.ch-actions { display: flex; gap: 8px; }
.ch-btn {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid var(--gold-line);
  background: var(--card);
  color: var(--ink-soft);
  transition: color .18s ease, box-shadow .18s ease, transform .18s ease;
}
.ch-btn:hover { color: var(--rouge); box-shadow: var(--shadow-glow-rouge); transform: translateY(-1px); }

/* ── 消息流 ── */
.transcript {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.t-empty {
  margin: auto;
  text-align: center;
  color: var(--ink-muted);
  font-family: var(--font-kai);
  letter-spacing: 2px;
  line-height: 2;
}
.msg { display: flex; flex-direction: column; gap: 4px; max-width: 82%; }
.msg.user { align-self: flex-end; align-items: flex-end; }
.msg.assistant { align-self: flex-start; align-items: flex-start; }

.bubble {
  padding: 10px 14px;
  border-radius: var(--radius-card);
  line-height: 1.75;
  font-size: 14px;
  overflow-wrap: break-word;
}
.msg.user .bubble {
  background: linear-gradient(135deg, var(--rouge), var(--cinnabar));
  color: #FDF6E9;
  border-bottom-right-radius: var(--radius-small);
  box-shadow: var(--shadow-card);
  white-space: pre-wrap;
}
.msg.assistant .bubble {
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--line);
  border-bottom-left-radius: var(--radius-small);
  box-shadow: var(--shadow-card);
}
.msg.failed .bubble {
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 1px var(--cinnabar-glow), var(--shadow-card);
  color: var(--cinnabar-deep);
}
.bubble.pending { display: flex; }

/* 思考中：三瓣梅点呼吸 */
.plum-wait { display: inline-flex; gap: 6px; padding: 4px 2px; }
.plum-wait i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--rouge);
  animation: plum-breathe 1.2s ease-in-out infinite;
}
.plum-wait i:nth-child(2) { animation-delay: .18s; background: var(--gold); }
.plum-wait i:nth-child(3) { animation-delay: .36s; background: var(--dai); }
@keyframes plum-breathe { 50% { transform: translateY(-4px); opacity: .5; } }
@media (prefers-reduced-motion: reduce) { .plum-wait i { animation: none; } }

.msg-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--ink-muted);
  padding: 0 4px;
}
.meta-cta {
  border: 1px solid var(--cinnabar);
  background: transparent;
  color: var(--cinnabar);
  border-radius: var(--radius-pill);
  padding: 2px 10px;
  font-size: 11px;
  transition: background .18s ease, color .18s ease;
}
.meta-cta:hover { background: var(--cinnabar); color: #FDF6E9; }

/* 过程透明化：折叠面板（工具调用/结果） */
.proc {
  font-size: 12px;
  color: var(--ink-muted);
  margin-bottom: 4px;
  border: 1px dashed var(--line);
  border-radius: var(--radius-small);
  max-width: 640px;
}
.proc summary {
  cursor: pointer;
  padding: 4px 10px;
  user-select: none;
  list-style: none;
}
.proc summary::before { content: '▸ '; }
.proc[open] summary::before { content: '▾ '; }
.proc-list {
  margin: 0;
  padding: 2px 10px 8px 26px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.proc-list li { display: flex; flex-direction: column; gap: 2px; }
.proc-list li.tool_call .proc-tool { color: var(--dai); }
.proc-list li.tool_result .proc-ret { color: var(--bamboo); }
.proc-list code {
  font-size: 11px;
  background: var(--line-soft);
  border-radius: var(--radius-small);
  padding: 2px 6px;
  word-break: break-all;
  white-space: pre-wrap;
}
.proc-live { color: var(--cinnabar); margin-left: 6px; }
.proc-count { color: var(--ink-muted); }

/* 思考块 */
.think {
  border-left: 2px solid var(--line);
  padding-left: 8px;
}
.think summary {
  cursor: pointer;
  user-select: none;
  list-style: none;
  color: var(--dai);
  font-size: 12px;
}
.think summary::before { content: '▸ '; }
.think[open] summary::before { content: '▾ '; }
.think-dur { color: var(--ink-muted); margin-left: 6px; font-size: 11px; }
.think-body {
  font-size: 11px;
  color: var(--ink-muted);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
  overflow-y: auto;
  padding: 4px 0 2px;
}

/* 破坏性命令确认门 */
.confirm-gate {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
  border: 1px solid var(--cinnabar);
  border-radius: var(--radius-small);
  padding: 8px 12px;
  margin-bottom: 4px;
  max-width: 640px;
  background: rgba(198, 79, 79, .04);
}
.confirm-gate.resolved { border-color: var(--line); background: transparent; color: var(--ink-muted); }
.confirm-text { color: var(--ink); line-height: 1.6; }
.confirm-text code {
  display: block;
  margin-top: 6px;
  font-size: 11px;
  background: var(--line-soft);
  border-radius: var(--radius-small);
  padding: 4px 8px;
  word-break: break-all;
  white-space: pre-wrap;
  max-height: 120px;
  overflow-y: auto;
}
.confirm-actions { display: flex; gap: 8px; }
.confirm-actions .danger {
  border-color: var(--cinnabar);
  color: var(--cinnabar);
}

/* markdown-lite 渲染（深选择器穿透 scoped） */
.md :deep(.md-p) { margin: 0; }
.md :deep(.md-pre) {
  margin: 8px 0;
  padding: 10px 12px;
  background: var(--bg-soft);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-small);
  font-family: var(--font-mono);
  font-size: 12.5px;
  overflow-x: auto;
  white-space: pre;
}
.md :deep(.md-ic) {
  font-family: var(--font-mono);
  font-size: .92em;
  background: var(--bg-soft);
  border: 1px solid var(--line-soft);
  border-radius: 5px;
  padding: 1px 5px;
}
.md :deep(.md-h) { font-family: var(--font-kai); letter-spacing: 1px; color: var(--cinnabar); }
.md :deep(.md-li) { display: block; padding-left: 14px; position: relative; }
.md :deep(.md-li)::before {
  content: '·';
  position: absolute;
  left: 2px;
  color: var(--rouge);
  font-weight: 700;
}
.md :deep(.md-li) :deep(.md-ol) { color: var(--rouge); }
.md :deep(.md-li):has(.md-ol)::before { content: none; }
.md :deep(.md-quote) {
  display: block;
  border-left: 3px solid var(--gold-line);
  padding-left: 10px;
  color: var(--ink-soft);
}
.md :deep(a) { color: var(--dai); text-decoration: underline; text-underline-offset: 2px; }

/* ── 输入坞 ── */
.composer {
  border-top: 1px solid var(--line-soft);
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  padding: 12px 16px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.composer textarea {
  width: 100%;
  resize: none;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card-solid);
  padding: 10px 12px;
  font-size: 14px;
  line-height: 1.7;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.composer textarea:focus {
  outline: none;
  border-color: var(--rouge);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.composer textarea:disabled { opacity: .6; }
.cp-bar { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.cp-opts { display: flex; gap: 8px; }
.cp-select {
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
  background: var(--card-solid);
  padding: 4px 12px;
  font-size: 12px;
  color: var(--ink-soft);
}
.cp-send {
  padding: 7px 22px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  font-family: var(--font-kai);
  letter-spacing: 3px;
  box-shadow: var(--shadow-seal);
  transition: transform .18s ease, box-shadow .18s ease, opacity .18s ease;
}
.cp-send:hover:not(:disabled) { transform: translateY(-1px); box-shadow: var(--shadow-lift); }
.cp-send:disabled { opacity: .45; cursor: not-allowed; box-shadow: none; }
.confirm-gate pre, .proc pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 200px; overflow: auto; }
.confirm-gate .mini-btn { padding: 6px 12px; border: 1px solid var(--line); border-radius: var(--radius-small); background: var(--card-solid); }
.confirm-gate button:disabled { opacity: .5; }
.msg, .bubble, .proc { min-width: 0; max-width: 100%; }
.msg-meta { flex-wrap: wrap; }
@media (max-width: 640px) {
  .hero { padding: 16px; gap: 10px; }
  .hero-gate { display: none; }
  .hero-title { font-size: 26px; }
  .conv-head { padding: 8px; }
  .ch-title { flex-wrap: wrap; gap: 5px; }
  .transcript { padding: 12px; }
  .cp-bar, .cp-opts { flex-wrap: wrap; }
  .composer { padding: 8px; }
}
</style>

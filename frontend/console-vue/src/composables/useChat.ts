// Copyright (c) 2026 QianChang-official
//
// 宛委·枢忆 is licensed under Mulan PSL v2.
// You can use this software according to the terms of the Mulan PSL v2.
// You may obtain a copy of Mulan PSL v2 at:
// http://license.coscl.org.cn/MulanPSL2
//
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.

/**
 * 会话状态 —— 按智能体分轨的对话记录。
 *
 * 对话记录仅持久化在本机浏览器 localStorage（ww-chat:<agent_id>），
 * 不上传、不与后端同步；发送失败（含网关 502）以错误气泡如实呈现。
 */

import { reactive, ref } from 'vue'
import { api, isGatewayUnavailable } from '@/api/client'
import type { Agent, ChatResponse } from '@/api/types'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  time: string
  /** 发送中占位 */
  pending?: boolean
  /** 发送失败标记（text 为错误说明） */
  failed?: boolean
  /** 网关未就绪 —— 引导去设置页配置模型 */
  gatewayDown?: boolean
  meta?: {
    engine: string
    provider_used: string
    context_tokens: number
    memory_injection: string
    run_id: string
  }
}

const transcripts = reactive<Record<string, ChatMessage[]>>({})
const sending = ref(false)

function storageKey(agentId: string): string {
  return `ww-chat:${agentId}`
}

function load(agentId: string): ChatMessage[] {
  if (transcripts[agentId]) return transcripts[agentId]
  let messages: ChatMessage[] = []
  try {
    const raw = localStorage.getItem(storageKey(agentId))
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) messages = parsed.filter((m) => m && typeof m.text === 'string')
    }
  } catch {
    messages = []
  }
  transcripts[agentId] = messages
  return messages
}

function persist(agentId: string): void {
  try {
    // 只落盘最近的 200 条，避免无限膨胀
    localStorage.setItem(storageKey(agentId), JSON.stringify(transcripts[agentId].slice(-200)))
  } catch { /* 存储满或隐私模式：静默降级为仅内存 */ }
}

function newId(): string {
  return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function now(): string {
  return new Date().toISOString()
}

function messagesOf(agentId: string): ChatMessage[] {
  return load(agentId)
}

async function send(agent: Agent, text: string): Promise<void> {
  const message = text.trim()
  if (!message || sending.value) return
  const list = load(agent.id)
  list.push({ id: newId(), role: 'user', text: message, time: now() })
  const placeholder: ChatMessage = { id: newId(), role: 'assistant', text: '', time: now(), pending: true }
  list.push(placeholder)
  sending.value = true
  persist(agent.id)
  try {
    const res: ChatResponse = await api.chat({ message, agent_id: agent.id })
    Object.assign(placeholder, {
      pending: false,
      text: res.reply,
      meta: {
        engine: res.engine,
        provider_used: res.provider_used,
        context_tokens: res.context_tokens,
        memory_injection: res.memory_injection,
        run_id: res.run_id,
      },
    })
  } catch (err) {
    const gatewayDown = isGatewayUnavailable(err)
    Object.assign(placeholder, {
      pending: false,
      failed: true,
      gatewayDown,
      text: gatewayDown
        ? '模型网关未就绪：尚未配置可用的模型服务商，或上游请求失败。请到「设置 · 模型接入」完成配置后重试。'
        : `发送失败：${err instanceof Error ? err.message : String(err)}`,
    })
  } finally {
    sending.value = false
    persist(agent.id)
  }
}

function clear(agentId: string): void {
  transcripts[agentId] = []
  persist(agentId)
}

export function useChat() {
  return { sending, messagesOf, send, clear }
}

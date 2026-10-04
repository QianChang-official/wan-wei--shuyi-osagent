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
 * 控制台真实交互行为测试（vitest + @vue/test-utils + jsdom）。
 * 挂载真实组件、打真实事件，fetch 全局 mock 到内存应答；
 * 不启动后端、不访问网络。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

import ConversationRoot from '../src/shell/ConversationRoot.vue'
import SidebarRoot from '../src/shell/SidebarRoot.vue'
import SettingsModal from '../src/shell/SettingsModal.vue'
import AgentEditor from '../src/shell/AgentEditor.vue'
import DetailsPanel from '../src/shell/DetailsPanel.vue'
import { useAgents } from '../src/composables/useAgents'
import { useChat } from '../src/composables/useChat'
import type { Agent, ChatResponse } from '../src/api/types'

const mkAgent = (id: string, name: string): Agent => ({
  id, name, role: '助手', persona: '', depth: 'medium', gear: 'sandbox',
  permissions: { fs_read: true, fs_write: false, shell: false, network: false, git: false },
  provider_pid: 'test-provider', model: 'test-model', goal: '', created_at: '',
})
const alpha = mkAgent('ag_alpha', '书僮')

const agents = useAgents()
const chat = useChat()

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const chatFinal = (text = '真实回答'): ChatResponse => ({
  reply: text, context_tokens: 17, run_id: 'run-1', depth: 'medium', gear: 'sandbox',
  engine: 'gateway', provider_used: 'test-provider', agent_id: alpha.id, memory_injection: 'ok',
})

let fetchMock: ReturnType<typeof vi.fn>
let chatStatus = 200
let chatReply = chatFinal()
const wrappers: VueWrapper[] = []

function defaultFetch(path: string, init?: RequestInit): Response {
  if (path === '/platform/agents' && !init?.method) return json({ items: [alpha], total: 1 })
  if (path === '/platform/agents' && init?.method === 'POST') return json(alpha, 201)
  if (path === '/platform/agents/chat') return json(chatReply, chatStatus)
  if (path.startsWith('/platform/agents/runs')) return json({ items: [], total: 0, limit: 50, offset: 0 })
  if (path.startsWith('/platform/agents/context-size')) {
    return json({ agent_id: alpha.id, system_prompt: 5, memory_instructions: 5, history: 0, total_tokens: 10, limit: 100 })
  }
  if (path === '/platform/providers/configs') {
    return json([{ pid: 'test-provider', configured: true, enabled: true, base_url: 'https://example.test', model: 'test-model', has_api_key: true, api_key_tail: '1234', api_key_masked: '****1234', extra: {}, updated_at: '' }])
  }
  if (path === '/platform/providers/catalog') {
    return json([{ id: 'test-provider', name: '测试服务商', kind: 'cloud', base_url: 'https://example.test', models: ['test-model'], auth_modes: ['api_key'], docs_url: '', aux_capable: false, description: '' }])
  }
  if (path === '/platform/memory/instructions') return json({ lines: [], count: 0, max: 200, updated_at: '' })
  if (path === '/health') return json({ status: 'ok', name: 'wanwei-shuyi-memoryops-autopilot', version: 'v1.0.0' })
  return json({})
}

function render(component: object, props = {}) {
  const wrapper = mount(component as never, { attachTo: document.body, props })
  wrappers.push(wrapper)
  return wrapper
}

const findButton = (w: VueWrapper, text: string) => {
  const result = w.findAll('button').find((b) => b.text().includes(text))
  if (!result) throw new Error(`Missing button: ${text}`)
  return result
}

beforeEach(async () => {
  chatStatus = 200
  chatReply = chatFinal()
  fetchMock = vi.fn((path: string, init?: RequestInit) => Promise.resolve(defaultFetch(String(path), init)))
  vi.stubGlobal('fetch', fetchMock)
  localStorage.clear()
  chat.clear(alpha.id)
  await agents.refresh()
  agents.select(alpha.id)
  await flushPromises()
  fetchMock.mockClear()
})

afterEach(async () => {
  wrappers.splice(0).forEach((w) => w.unmount())
  await flushPromises()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('会话区真实交互', () => {
  it('发送消息：POST 带上 agent_id，回复经 markdown 渲染入气泡', async () => {
    chatReply = chatFinal('**加粗** 与 [链接](https://example.test/x)')
    const w = render(ConversationRoot)
    await w.get('textarea').setValue('你好')
    await w.get('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    const chatCalls = fetchMock.mock.calls.filter(([p, i]) => String(p) === '/platform/agents/chat' && i?.method === 'POST')
    expect(chatCalls.length).toBe(1)
    expect(JSON.parse(String(chatCalls[0][1]?.body))).toMatchObject({ agent_id: 'ag_alpha', message: '你好' })
    await flushPromises()
    expect(w.find('.msg.assistant .md strong').exists()).toBe(true)
    expect(w.text()).toContain('真实回答'.slice(0, 0) || '加粗')
  })

  it('网关未就绪（502 gateway_unavailable）：诚实错误气泡 + 直达模型接入的引导', async () => {
    chatStatus = 502
    chatReply = { detail: { error: 'gateway_unavailable', reason: 'no provider configured' } } as never
    const w = render(ConversationRoot)
    await w.get('textarea').setValue('在吗')
    await w.get('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.find('.msg.failed').exists()).toBe(true)
    expect(w.text()).toContain('模型网关未就绪')
    const cta = findButton(w, '去配置模型')
    await cta.trigger('click')
    expect(w.emitted('open-settings')?.[0]).toEqual(['providers'])
  })

  it('markdown 消毒：伪协议链接不生成 href', async () => {
    chatReply = chatFinal('[点我](javascript:alert(1)) 与 <b>原文</b>')
    const w = render(ConversationRoot)
    await w.get('textarea').setValue('测一下')
    await w.get('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    const md = w.find('.msg.assistant .md')
    expect(md.exists()).toBe(true)
    expect(md.find('a').exists()).toBe(false)
    expect(md.html()).not.toContain('javascript:')
    expect(md.html()).toContain('&lt;b&gt;')
  })
})

describe('侧栏与编辑', () => {
  it('侧栏列出智能体并显示后端在线版本', async () => {
    const w = render(SidebarRoot)
    await flushPromises()
    expect(w.text()).toContain('书僮')
    expect(w.text()).toContain('后端在线')
    expect(w.text()).toContain('v1.0.0')
  })

  it('新建智能体：表单校验 + POST + 事件', async () => {
    const w = render(AgentEditor)
    const createBtn = findButton(w, '创建')
    expect(createBtn.attributes('disabled')).toBeDefined()
    await w.get('input[placeholder="例如：书僮"]').setValue('新帮手')
    await createBtn.trigger('click')
    await flushPromises()
    const posts = fetchMock.mock.calls.filter(([p, i]) => String(p) === '/platform/agents' && i?.method === 'POST')
    expect(posts.length).toBe(1)
    expect(w.emitted('saved')).toBeTruthy()
    expect(w.emitted('close')).toBeTruthy()
  })
})

describe('设置与详情', () => {
  it('设置·模型接入：渲染真实服务商配置与目录名', async () => {
    const w = render(SettingsModal, { initialSection: 'providers' })
    await flushPromises()
    expect(w.text()).toContain('测试服务商')
    expect(w.text()).toContain('已启用')
  })

  it('设置·关于：后端版本实时取自 /health', async () => {
    const w = render(SettingsModal, { initialSection: 'about' })
    await flushPromises()
    expect(w.text()).toContain('wanwei-shuyi-memoryops-autopilot')
    expect(w.text()).toContain('v1.0.0')
    expect(w.text()).toContain('Mulan PSL v2')
  })

  it('详情栏：档案 + 上下文玉环 + 空运行记录', async () => {
    const w = render(DetailsPanel)
    await flushPromises()
    expect(w.text()).toContain('智能体档案')
    expect(w.text()).toContain('书僮')
    expect(w.text()).toContain('10 / 100')
    expect(w.text()).toContain('尚无运行记录')
  })
})

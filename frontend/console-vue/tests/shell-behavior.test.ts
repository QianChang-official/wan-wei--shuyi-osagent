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

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import ConversationRoot from '../src/shell/ConversationRoot.vue'
import SettingsModal from '../src/shell/SettingsModal.vue'
import DetailsPanel from '../src/shell/DetailsPanel.vue'
import { api, getApiKey, setApiKey } from '../src/api/client'
import { apiGet } from '../src/api/platform'
import { useAgents } from '../src/composables/useAgents'
import { useChat, useChatLifecycle } from '../src/composables/useChat'
import { useRuns } from '../src/composables/useRuns'
import type { Agent, ChatResponse } from '../src/api/types'

const agent = (id: string): Agent => ({ id, name: id, role: '助手', persona: '', depth: 'medium', gear: 'sandbox', permissions: { fs_read: true, fs_write: false, shell: false, network: false, git: false }, provider_pid: 'test-provider', model: 'test-model', goal: '', created_at: '' })
const a = agent('alpha')
const b = agent('beta')
const agents = useAgents()
const chat = useChat()
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const final = (run_id = 'run-1', extra = {}): ChatResponse => ({ reply: '真实回答', run_id, context_tokens: 17, depth: 'high', gear: 'human_review', engine: 'test', provider_used: 'test-provider', agent_id: a.id, memory_injection: 'ok', status: 'done', ...extra })
const wrappers: VueWrapper[] = []
let fetchMock: ReturnType<typeof vi.fn>
let keyCounter = 0
let streams: ReturnType<typeof stream>[]
let overrides: (path: string, init: RequestInit) => Response | Promise<Response> | undefined

function stream(signal?: AbortSignal) {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  let closed = false
  const body = new ReadableStream<Uint8Array>({
    start(c) { controller = c },
    cancel() { closed = true },
  })
  signal?.addEventListener('abort', () => {
    if (!closed) { closed = true; controller.error(new DOMException('aborted', 'AbortError')) }
  }, { once: true })
  return {
    response: new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }),
    raw(text: string) { if (!closed) controller.enqueue(new TextEncoder().encode(text)) },
    event(name: string, body: unknown) { this.raw(`event: ${name}\ndata: ${JSON.stringify(body)}\n\n`) },
    end() { if (!closed) { closed = true; controller.close() } },
  }
}
function defaultFetch(path: string, init: RequestInit = {}): Response | Promise<Response> {
  const result = overrides(path, init)
  if (result) return result
  if (path.endsWith('/chat/stream')) {
    const s = stream(init.signal ?? undefined)
    streams.push(s)
    return s.response
  }
  if (path === '/platform/agents') return json({ items: [a, b], total: 2 })
  if (path.includes('/runs')) return json({ items: [], total: 0 })
  if (path.includes('/context-size')) return json({ agent_id: a.id, total_tokens: 10, limit: 100, system_prompt: 5, memory_instructions: 5, history: 0 })
  if (path === '/platform/providers/configs') return json([{ pid: 'test-provider', configured: true, enabled: true, base_url: 'https://example.test', model: 'test-model', has_api_key: true, api_key_masked: '***' }])
  if (path === '/platform/providers/catalog') return json([{ id: 'test-provider', name: '测试服务商', models: ['test-model'], kind: 'cloud', base_url: 'https://example.test' }])
  if (path === '/platform/memory/instructions') return json({ lines: [], count: 0, max: 10 })
  if (path === '/health') return json({ status: 'ok', version: 'test', name: 'backend' })
  return json({})
}
function render(component: any, props = {}) {
  const wrapper = mount(component, { attachTo: document.body, props, global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
  wrappers.push(wrapper)
  return wrapper
}
const button = (w: VueWrapper, text: string) => {
  const result = w.findAll('button').find(b => b.text() === text)
  if (!result) throw new Error(`Missing button: ${text}`)
  return result
}
const requests = (suffix: string) => fetchMock.mock.calls.filter(([path]) => String(path).endsWith(suffix))

beforeEach(async () => {
  streams = []
  overrides = () => undefined
  fetchMock = vi.fn((path, init) => Promise.resolve(defaultFetch(String(path), init)))
  vi.stubGlobal('fetch', fetchMock)
  setApiKey(`identity-${++keyCounter}`)
  await agents.refresh()
  agents.select(a.id)
  await flushPromises()
  fetchMock.mockClear()
})
afterEach(async () => {
  for (const id of [a.id, b.id]) if (chat.sending[id]) await chat.cancel(id)
  wrappers.splice(0).forEach(w => w.unmount())
  await flushPromises()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('real Vue conversation interactions', () => {
  it('updates first-load SSE steps/final reactively and sends the chosen controls', async () => {
    const w = render(ConversationRoot)
    await w.get('[aria-label="思考深度"]').setValue('high')
    await w.get('[aria-label="工作档位"]').setValue('human_review')
    await w.get('textarea').setValue('请检查')
    await w.get('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(JSON.parse(requests('/chat/stream')[0][1].body)).toMatchObject({ agent_id: a.id, depth: 'high', gear: 'human_review', previous_run_id: null })
    streams[0].event('step', { kind: 'run_started', run_id: 'run-1' })
    // Deliberately split CRLF, JSON and delimiter across reads.
    streams[0].raw('event:step\r\ndata:{"kind":"tool_call","tool":"read_file","args":"visible-live"}\r')
    streams[0].raw('\n\r\n')
    await flushPromises()
    expect(w.text()).toContain('visible-live')
    expect(w.find('[aria-label^="处理运行中"]').exists()).toBe(true)
    expect(w.text()).not.toContain('真实回答')
    streams[0].event('final', final())
    await flushPromises()
    expect(w.text()).toContain('真实回答')
    expect(w.text()).toContain('17 tok')
    expect(w.find('[aria-label^="处理运行中"]').exists()).toBe(false)
    expect(chat.sending[a.id]).toBe(false)
    await w.get('textarea').setValue('继续')
    await button(w, '发送').trigger('click')
    await flushPromises()
    expect(JSON.parse(requests('/chat/stream')[1][1].body)).toMatchObject({ previous_run_id: 'run-1' })
    expect(JSON.parse(requests('/chat/stream')[1][1].body)).not.toHaveProperty('history')
    streams[1].event('final', final('run-2'))
  })

  it('keeps agents independent; stop aborts the stream and cancels the known run', async () => {
    const one = chat.send(a, 'one')
    const two = chat.send(b, 'two')
    await flushPromises()
    streams[0].event('step', { kind: 'run_started', run_id: 'run-alpha' })
    await flushPromises()
    const w = render(ConversationRoot)
    await button(w, '停止').trigger('click')
    await one
    expect(chat.sending[a.id]).toBe(false)
    expect(chat.sending[b.id]).toBe(true)
    expect(requests('/runs/run-alpha/cancel')).toHaveLength(1)
    expect(w.text()).toContain('已停止接收')
    agents.select(b.id)
    await nextTick()
    expect(button(w, '停止').exists()).toBe(true)
    streams[1].event('final', final('run-beta'))
    await two
    expect(w.text()).toContain('真实回答')
  })

  it('settles EOF without final as an error, not a forever pending bubble', async () => {
    const w = render(ConversationRoot)
    const work = chat.send(a, 'one')
    await flushPromises()
    streams[0].event('step', { kind: 'thinking', text: '阶段说明' })
    streams[0].end()
    await work
    await nextTick()
    expect(w.text()).toContain('未收到最终结果')
    expect(chat.sending[a.id]).toBe(false)
    expect(w.get('textarea').attributes('disabled')).toBeUndefined()
    expect(chat.messagesOf(a.id).at(-1)?.failed).toBe(true)
  })

  it('connect timeout clears pending and permits retry', async () => {
    vi.useFakeTimers()
    overrides = (path, init) => path.endsWith('/chat/stream') ? new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('abort', 'AbortError')))
    }) : undefined
    const w = render(ConversationRoot)
    const work = chat.send(a, 'connect')
    await vi.advanceTimersByTimeAsync(30_001)
    await work
    await nextTick()
    expect(chat.sending[a.id]).toBe(false)
    expect(w.text()).toContain('超时')
    expect(w.get('textarea').attributes('disabled')).toBeUndefined()
  })

  it('handles HTTP auth and terminal SSE errors visibly', async () => {
    overrides = path => path.endsWith('/chat/stream') ? json({ detail: 'invalid key' }, 401) : undefined
    const w = render(ConversationRoot)
    await chat.send(a, 'one')
    await nextTick()
    expect(button(w, '更新访问密钥').exists()).toBe(true)
    overrides = () => undefined
    const work = chat.send(a, 'two')
    await flushPromises()
    streams[0].event('error', { error: 'gateway_unavailable', reason: 'upstream failed' })
    await work
    await nextTick()
    expect(button(w, '去配置模型').exists()).toBe(true)
    expect(chat.sending[a.id]).toBe(false)
  })

  it('shows every ticket, waits for the response, blocks double submit and honors ok:false', async () => {
    const w = render(ConversationRoot)
    const work = chat.send(a, 'two operations')
    await flushPromises()
    streams[0].event('step', { kind: 'tool_result', tool: 'write_file', result: { path: '/private/a' }, confirm_token: 'ticket-first' })
    streams[0].event('final', final('approval-run', { status: 'awaiting_review', pending_confirmations: [
      { confirm_token: 'ticket-first', operation: 'write_file', path: '/private/a' },
      { confirm_token: 'ticket-second', operation: 'run_command', command: 'allowed command' },
    ] }))
    await work
    await nextTick()
    expect(w.findAll('.confirm-gate')).toHaveLength(2)
    let respond!: (r: Response) => void
    overrides = path => path.endsWith('/chat/confirm') ? new Promise(resolve => { respond = resolve }) : undefined
    const first = w.findAll('.confirm-gate')[0]
    await first.get('button').trigger('click')
    await first.get('button').trigger('click')
    expect(requests('/chat/confirm')).toHaveLength(1)
    expect(first.get('button').attributes('disabled')).toBeDefined()
    expect(first.text()).not.toContain('操作成功')
    respond(json({ ok: false, exit_code: 13, stderr: 'Permission denied', run_id: 'approval-run', status: 'awaiting_review', pending_confirmations: [{ confirm_token: 'ticket-second' }] }))
    await flushPromises()
    expect(first.text()).toContain('后端报告操作失败')
    expect(first.text()).toContain('Permission denied')
    expect(first.text()).toContain('13')
    overrides = path => path.endsWith('/chat/confirm') ? json({ ok: true, exit_code: 0, stdout: 'actual output', run_id: 'approval-run', status: 'done', pending_confirmations: [] }) : undefined
    await w.findAll('.confirm-gate')[1].get('button').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('actual output')
    expect(w.text()).toContain('后端已确认操作成功')
    expect(chat.revision.value).toBeGreaterThan(0)
  })

  it('denial invalidates sibling tickets rather than leaving clickable dead approvals', async () => {
    const w = render(ConversationRoot)
    const work = chat.send(a, 'approval')
    await flushPromises()
    streams[0].event('final', final('approval-run', { status: 'awaiting_review', pending_confirmations: [{ confirm_token: 'ticket-one' }, { confirm_token: 'ticket-two' }] }))
    await work
    overrides = path => path.endsWith('/chat/confirm') ? json({ ok: false, denied: true, status: 'failed', pending_confirmations: [] }) : undefined
    await button(w, '拒绝').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('已拒绝，未执行')
    expect(w.findAll('.confirm-gate button')).toHaveLength(0)
  })
  it('shows unknown confirmation outcomes without allowing unsafe replay', async () => {
    const w = render(ConversationRoot)
    const work = chat.send(a, 'approval')
    await flushPromises()
    streams[0].event('final', final('approval-run', { status: 'awaiting_review', pending_confirmations: [{ confirm_token: 'ticket-one' }] }))
    await work
    overrides = path => path.endsWith('/chat/confirm') ? Promise.reject(new TypeError('network disconnected')) : undefined
    await button(w, '放行执行').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('操作结果未知')
    expect(w.text()).toContain('勿重复执行')
    expect(w.findAll('.confirm-gate button')).toHaveLength(0)
  })

  it('never uses failed bubbles or a cleared transcript as continuity', async () => {
    const good = chat.send(a, 'good')
    await flushPromises()
    streams[0].event('final', final('good-run'))
    await good
    const bad = chat.send(a, 'bad')
    await flushPromises()
    streams[1].event('error', { error: 'failed' })
    await bad
    const again = chat.send(a, 'again')
    await flushPromises()
    expect(JSON.parse(requests('/chat/stream').at(-1)![1].body).previous_run_id).toBe('good-run')
    streams[2].event('final', final('next-good'))
    await again
    chat.clear(a.id)
    const fresh = chat.send(a, 'fresh')
    await flushPromises()
    expect(JSON.parse(requests('/chat/stream').at(-1)![1].body).previous_run_id).toBeNull()
    streams[3].event('final', final('fresh'))
    await fresh
  })

  it('scope change aborts an active stream and ignores its old response', async () => {
    const work = chat.send(a, 'private old message')
    await flushPromises()
    setApiKey('replaced-identity')
    await work
    await flushPromises()
    expect(chat.messagesOf(a.id)).toHaveLength(0)
    expect(chat.sending[a.id]).toBeFalsy()
    const w = render(ConversationRoot)
    expect(w.text()).not.toContain('private old message')
  })

  it('idle deadline and malformed events settle as explicit failures', async () => {
    vi.useFakeTimers()
    const work = chat.send(a, 'idle')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(60_001)
    await work
    expect(chat.messagesOf(a.id).at(-1)?.text).toContain('超时')
    const bad = chat.send(a, 'malformed')
    await flushPromises()
    streams[1].raw('event: step\ndata: {broken\n\n')
    await bad
    expect(chat.messagesOf(a.id).at(-1)?.failed).toBe(true)
    expect(chat.sending[a.id]).toBe(false)
  })
})

describe('settings, scope and retained tools', () => {
  it('renders initial authentication failure distinctly from an empty account', async () => {
    overrides = path => path === '/platform/agents' ? json({ detail: 'unauthorized' }, 401) : undefined
    agents.agents.value = []
    await agents.refresh()
    const w = render(ConversationRoot)
    expect(w.text()).toContain('访问鉴权失败')
    expect(w.text()).not.toContain('说第一句话')
    expect(button(w, '重试').exists()).toBe(true)
  })

  it('refreshes shared data on key save, clears continuity, and shares the key with advanced APIs', async () => {
    const work = chat.send(a, 'old identity')
    await flushPromises()
    streams[0].event('final', final('old-run'))
    await work
    const w = render(SettingsModal, { initialSection: 'general' })
    await flushPromises()
    await w.get('[aria-label="控制台访问密钥"]').setValue('new-identity')
    await button(w, '保存').trigger('click')
    await flushPromises()
    expect(getApiKey()).toBe('new-identity')
    expect(chat.messagesOf(a.id)).toHaveLength(0)
    expect(w.text()).toContain('共享数据已重新加载')
    const newCalls = requests('/platform/agents').filter(([, init]) => init.headers.get('X-API-Key') === 'new-identity')
    expect(newCalls.length).toBeGreaterThan(0)
    await apiGet('/test')
    expect(requests('/platform/test')[0][1].headers.get('X-API-Key')).toBe('new-identity')
    await apiGet('/test', { credential: 'mobile-lan' })
    expect(requests('/platform/test')[1][1].headers.get('X-API-Key')).toBe('mobile-lan')
    expect(getApiKey()).toBe('new-identity')
    const next = chat.send(a, 'new identity')
    await flushPromises()
    expect(JSON.parse(requests('/chat/stream').at(-1)![1].body).previous_run_id).toBeNull()
    streams.at(-1)!.event('final', final('new-run'))
    await next
  })

  it('keeps provider save/test failures inline and the form retryable', async () => {
    const w = render(SettingsModal, { initialSection: 'providers' })
    await flushPromises()
    await button(w, '配置').trigger('click')
    overrides = path => path === '/platform/providers/configs/test-provider' ? json({ detail: 'save denied' }, 403)
      : path === '/platform/providers/test' ? json({ ok: false, reason: 'upstream refused', pid: 'test-provider' }) : undefined
    await button(w, '保存').trigger('click')
    await flushPromises()
    expect(w.get('.pr-form [role="alert"]').text()).toContain('save denied')
    expect(button(w, '保存').attributes('disabled')).toBeUndefined()
    await button(w, '测试').trigger('click')
    await flushPromises()
    expect(w.get('.pr-test').text()).toContain('upstream refused')
  })

  it('focuses and traps the settings dialog, Escape closes and restores focus', async () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    const w = render(SettingsModal, { initialSection: 'general' })
    await flushPromises()
    expect(w.get('[role="dialog"]').element.contains(document.activeElement)).toBe(true)
    const save = button(w, '保存')
    ;(save.element as HTMLButtonElement).focus()
    await save.trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(w.findAll('button')[0].element)
    await w.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    expect(w.emitted('close')).toHaveLength(1)
    w.unmount()
    expect(document.activeElement).toBe(opener)
    wrappers.splice(wrappers.indexOf(w), 1)
  })

  it('refreshes runs/context after chat outcomes and shows failed loads instead of empty', async () => {
    const w = render(DetailsPanel)
    await flushPromises()
    const before = requests('/platform/agents/runs?limit=50&agent_id=alpha').length
    overrides = path => path.includes('/context-size') ? json({ detail: 'context unavailable' }, 503) : undefined
    const work = chat.send(a, 'refresh')
    await flushPromises()
    streams[0].event('final', final())
    await work
    await flushPromises()
    expect(requests('/platform/agents/runs?limit=50&agent_id=alpha').length).toBeGreaterThan(before)
    expect(w.text()).toContain('context unavailable')
    expect(w.findAll('[role="alert"]').length).toBeGreaterThan(0)
  })

  it('chat awaiting_review exposes per-tool instructions and cancel, not generic run approval', async () => {
    overrides = path => path.includes('/runs?') ? json({ items: [{ id: 'chat-run', agent_id: a.id, kind: 'chat', status: 'awaiting_review', steps: [], created_at: '', task: 'operation' }], total: 1 }) : undefined
    const w = render(DetailsPanel)
    await flushPromises()
    expect(w.text()).toContain('逐项确认')
    expect(w.findAll('button').some(b => b.text() === '放行')).toBe(false)
    expect(button(w, '取消').exists()).toBe(true)
    const work = chat.send(a, 'approve')
    await flushPromises()
    streams[0].event('final', final('chat-run', { status: 'awaiting_review', pending_confirmations: [{ confirm_token: 'pending-ticket' }] }))
    await work
    overrides = path => path.endsWith('/chat-run/cancel') ? json({ id: 'chat-run', status: 'cancelled' }) : undefined
    await button(w, '取消').trigger('click')
    await flushPromises()
    expect(chat.messagesOf(a.id).at(-1)?.confirmations?.[0].state).toBe('cancelled')
    expect(requests('/chat-run/approve')).toHaveLength(0)
  })

  it('requests selected-agent history before pagination and keeps polling old active runs', async () => {
    vi.useFakeTimers()
    const oldRun = { id: 'old-alpha', agent_id: a.id, kind: 'solo', status: 'running', steps: [], created_at: '', task: 'old selected-agent run' }
    const newerOthers = Array.from({ length: 50 }, (_, i) => ({ ...oldRun, id: `new-${i}`, agent_id: b.id, task: 'other-agent run' }))
    overrides = path => path.includes('/runs?') ? json({ items: new URL(path, 'http://localhost').searchParams.get('agent_id') === a.id ? [oldRun] : newerOthers, total: 51 }) : undefined
    const w = render(DetailsPanel)
    await flushPromises()
    expect(w.text()).toContain('old selected-agent run')
    expect(w.text()).not.toContain('other-agent run')
    expect(useRuns().hasActive(a.id)).toBe(true)
    await vi.advanceTimersByTimeAsync(4001)
    expect(requests('/platform/agents/runs?limit=50&agent_id=alpha').length).toBeGreaterThan(1)
    expect(requests('/platform/agents/runs?limit=50')).toHaveLength(0)
  })

  it('expires approvals and unblocks composer/clear with no details panel after five minutes', async () => {
    vi.useFakeTimers()
    const expires = Date.now() + 300_000
    const ticket = { confirm_token: 'ttl-ticket', expires_at: new Date(expires).toISOString(), run_id: 'ttl-run' }
    const Application = defineComponent({ setup() { useChatLifecycle(); return () => h(ConversationRoot) } })
    const w = render(Application)
    const work = chat.send(a, 'pending with hidden details')
    await flushPromises()
    streams[0].event('final', final('ttl-run', { status: 'awaiting_review', pending_confirmations: [ticket] }))
    await work
    await nextTick()
    overrides = path => path.endsWith('/runs/ttl-run') ? json({ id: 'ttl-run', status: Date.now() >= expires ? 'failed' : 'awaiting_review', error: Date.now() >= expires ? 'approval_expired' : '', pending_confirmations: Date.now() >= expires ? [] : [ticket] }) : undefined
    await w.get('textarea').setValue('next turn')
    expect(button(w, '发送').attributes('disabled')).toBeDefined()
    expect(w.get('[aria-label="清空此页会话"]').attributes('disabled')).toBeDefined()
    expect(w.findComponent(DetailsPanel).exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(300_001)
    await flushPromises()
    expect(chat.messagesOf(a.id).at(-1)?.confirmations?.[0].state).toBe('expired')
    expect(w.text()).toContain('确认期限已过')
    expect(button(w, '发送').attributes('disabled')).toBeUndefined()
    expect(w.get('[aria-label="清空此页会话"]').attributes('disabled')).toBeUndefined()
    expect(requests('/chat/confirm')).toHaveLength(0)
    const polls = requests('/runs/ttl-run').length
    expect(polls).toBeGreaterThan(0)
    expect(polls).toBeLessThanOrEqual(76)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(requests('/runs/ttl-run')).toHaveLength(polls)
  })

  it('reconciles a remote cancellation without the details panel or a local confirmation', async () => {
    vi.useFakeTimers()
    const ticket = { confirm_token: 'remote-ticket', expires_at: new Date(Date.now() + 300_000).toISOString() }
    const Application = defineComponent({ setup() { useChatLifecycle(); return () => h(ConversationRoot) } })
    const w = render(Application)
    const work = chat.send(a, 'cancelled elsewhere')
    await flushPromises()
    streams[0].event('final', final('remote-run', { status: 'awaiting_review', pending_confirmations: [ticket] }))
    await work
    overrides = path => path.endsWith('/runs/remote-run') ? json({ id: 'remote-run', status: 'cancelled', pending_confirmations: [] }) : undefined
    await vi.advanceTimersByTimeAsync(4001)
    expect(chat.messagesOf(a.id).at(-1)?.confirmations?.[0].state).toBe('cancelled')
    expect(w.findAll('.confirm-gate button')).toHaveLength(0)
    expect(w.text()).not.toContain('操作成功')
    const polls = requests('/runs/remote-run').length
    await vi.advanceTimersByTimeAsync(20_000)
    expect(requests('/runs/remote-run')).toHaveLength(polls)
  })

  it('local expiry still unlocks offline and unmount cancels reconciliation timers/requests', async () => {
    vi.useFakeTimers()
    const ticket = { confirm_token: 'offline-ticket', expires_at: new Date(Date.now() + 5000).toISOString() }
    const Application = defineComponent({ setup() { useChatLifecycle(); return () => h(ConversationRoot) } })
    const w = render(Application)
    const work = chat.send(a, 'offline approval')
    await flushPromises()
    streams[0].event('final', final('offline-run', { status: 'awaiting_review', pending_confirmations: [ticket] }))
    await work
    let requestSignal: AbortSignal | undefined
    overrides = (path, init) => path.endsWith('/runs/offline-run') ? new Promise((_resolve, reject) => {
      requestSignal = init.signal ?? undefined
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }) : undefined
    await vi.advanceTimersByTimeAsync(5001)
    expect(chat.messagesOf(a.id).at(-1)?.confirmations?.[0].state).toBe('expired')
    expect(w.get('[aria-label="清空此页会话"]').attributes('disabled')).toBeUndefined()
    expect(requests('/runs/offline-run')).toHaveLength(1)
    expect(requestSignal?.aborted).toBe(false)
    w.unmount()
    wrappers.splice(wrappers.indexOf(w), 1)
    await flushPromises()
    expect(requestSignal?.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(requests('/runs/offline-run')).toHaveLength(1)
  })

  it('preserves advanced and mobile deep links while the new shell is the default', async () => {
    const { router } = await import('../src/router')
    expect(router.resolve('/').name).toBe('console')
    for (const path of ['/advanced', '/platform/agents', '/platform/sessions', '/platform/knowledge', '/audit', '/governance', '/exports', '/platform/providers', '/platform/settings', '/mobile']) {
      expect(router.resolve(path).name).not.toBe('notFound')
      const component = router.resolve(path).matched.at(-1)?.components?.default
      expect(component).toBeTypeOf('function')
      // Real lazy imports prove retained files and their transitive dependencies still compile.
      expect(await (component as Function)()).toHaveProperty('default')
    }
  })
})

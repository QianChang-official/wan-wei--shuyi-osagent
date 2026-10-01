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

/** 智能体列表与选中状态 —— 模块级单例，侧栏/会话/详情三栏共享 */

import { computed, ref } from 'vue'
import { api, isAuthError, onApiKeyChange } from '@/api/client'
import type { Agent, AgentInput } from '@/api/types'

const agents = ref<Agent[]>([])
const loading = ref(false)
const error = ref('')
const authError = ref(false)
let requestVersion = 0
const selectedId = ref<string | null>(null)

const SELECTED_KEY = 'ww-console-selected-agent'

try {
  selectedId.value = localStorage.getItem(SELECTED_KEY)
} catch { /* ignore */ }

const selectedAgent = computed<Agent | null>(
  () => agents.value.find((a) => a.id === selectedId.value) ?? null,
)

async function refresh(): Promise<void> {
  const version = ++requestVersion
  loading.value = true
  error.value = ''
  authError.value = false
  try {
    const res = await api.listAgents()
    if (version !== requestVersion) return
    agents.value = res.items
    if (selectedId.value && !agents.value.some((a) => a.id === selectedId.value)) {
      select(agents.value[0]?.id ?? null)
    }
    if (!selectedId.value && agents.value.length > 0) select(agents.value[0].id)
  } catch (err) {
    if (version !== requestVersion) return
    authError.value = isAuthError(err)
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

function select(id: string | null): void {
  selectedId.value = id
  try {
    if (id) localStorage.setItem(SELECTED_KEY, id)
    else localStorage.removeItem(SELECTED_KEY)
  } catch { /* ignore */ }
}

async function create(input: AgentInput): Promise<Agent> {
  const created = await api.createAgent(input)
  await refresh()
  select(created.id)
  return created
}

async function update(id: string, patch: Partial<AgentInput>): Promise<Agent> {
  const updated = await api.updateAgent(id, patch)
  await refresh()
  return updated
}

async function remove(id: string): Promise<void> {
  await api.deleteAgent(id)
  if (selectedId.value === id) select(null)
  await refresh()
}

onApiKeyChange(() => {
  requestVersion++
  agents.value = []
  select(null)
  void refresh()
})

export function useAgents() {
  return { agents, loading, error, authError, selectedId, selectedAgent, refresh, select, create, update, remove }
}

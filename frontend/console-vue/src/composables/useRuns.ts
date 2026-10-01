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

/** 运行记录 —— 详情栏轮询当前智能体的运行，支持人工审查放行/驳回与取消 */

import { computed, ref } from 'vue'
import { useChat } from './useChat'
import { useAgents } from './useAgents'
import { api, getCredentialRevision, onApiKeyChange } from '@/api/client'
import type { Run } from '@/api/types'

const runs = ref<Run[]>([])
const loading = ref(false)
const acting = ref<string>('')
const error = ref('')
const actionError = ref('')
let requestVersion = 0

/** 仍有生命周期的状态 —— 存在时才继续轮询 */
const ACTIVE_STATUSES = new Set(['queued', 'running', 'awaiting_review'])

function agentRuns(agentId: string | null) {
  return computed<Run[]>(() =>
    agentId ? runs.value.filter((r) => r.agent_id === agentId) : [],
  )
}

function hasActive(agentId: string | null): boolean {
  if (!agentId) return false
  return runs.value.some((r) => r.agent_id === agentId && ACTIVE_STATUSES.has(r.status))
}

async function refresh(): Promise<void> {
  const version = ++requestVersion
  const agentId = useAgents().selectedId.value
  error.value = ''
  if (!agentId) { runs.value = []; loading.value = false; return }
  loading.value = true
  try {
    // Agent scope must precede server pagination; filtering a global newest-50 page loses old runs.
    const res = await api.listRuns(50, agentId)
    if (version === requestVersion) {
      runs.value = res.items
      useChat().syncRuns(res.items)
    }
  } catch (err) {
    if (version === requestVersion) error.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

async function approve(id: string, approved: boolean): Promise<void> {
  if (acting.value) return
  const scope = getCredentialRevision()
  acting.value = id
  actionError.value = ''
  try {
    const updated = await api.approveRun(id, approved)
    if (scope !== getCredentialRevision()) return
    useChat().syncRuns([updated])
    runs.value = runs.value.map((r) => (r.id === id ? updated : r))
  } catch (err) {
    if (scope !== getCredentialRevision()) return
    actionError.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (scope === getCredentialRevision()) acting.value = ''
  }
}

async function cancel(id: string): Promise<void> {
  if (acting.value) return
  const scope = getCredentialRevision()
  acting.value = id
  actionError.value = ''
  try {
    const updated = await api.cancelRun(id)
    if (scope !== getCredentialRevision()) return
    useChat().syncRuns([updated])
    runs.value = runs.value.map((r) => (r.id === id ? updated : r))
  } catch (err) {
    if (scope !== getCredentialRevision()) return
    actionError.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (scope === getCredentialRevision()) acting.value = ''
  }
}

onApiKeyChange(() => {
  requestVersion++
  runs.value = []
  error.value = ''
  actionError.value = ''
  acting.value = ''
})

export function useRuns() {
  return { runs, loading, error, actionError, acting, agentRuns, hasActive, refresh, approve, cancel }
}

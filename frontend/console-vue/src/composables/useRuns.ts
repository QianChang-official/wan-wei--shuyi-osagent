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
import { api } from '@/api/client'
import type { Run } from '@/api/types'

const runs = ref<Run[]>([])
const loading = ref(false)
const acting = ref<string>('')

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
  loading.value = true
  try {
    const res = await api.listRuns(50)
    runs.value = res.items
  } catch {
    // 详情栏静默失败：下一轮轮询自愈
  } finally {
    loading.value = false
  }
}

async function approve(id: string, approved: boolean): Promise<void> {
  acting.value = id
  try {
    const updated = await api.approveRun(id, approved)
    runs.value = runs.value.map((r) => (r.id === id ? updated : r))
  } finally {
    acting.value = ''
  }
}

async function cancel(id: string): Promise<void> {
  acting.value = id
  try {
    const updated = await api.cancelRun(id)
    runs.value = runs.value.map((r) => (r.id === id ? updated : r))
  } finally {
    acting.value = ''
  }
}

export function useRuns() {
  return { runs, loading, acting, agentRuns, hasActive, refresh, approve, cancel }
}

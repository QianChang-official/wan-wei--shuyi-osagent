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
 * CodingWorkbench — 万枢编程工作台（三栏布局）。
 *
 * 左：编程会话 + 工作区树 ｜ 中：计划 + 事件时间线 ｜ 右：审批/工具/待办/记忆/策略
 * 顶栏：品牌 + 模型网关状态 + 权限档 + 返回对话模式。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import CodingSidebar from './CodingSidebar.vue'
import CodingStage from './CodingStage.vue'
import CodingInspector from './CodingInspector.vue'
import NewSessionDialog from './NewSessionDialog.vue'
import { useCoding } from '@/composables/useCoding'

const emit = defineEmits<{ (e: 'exit'): void }>()

const {
  overview, tools, skills, roles, policy,
  sessions, activeId, activeBrief, detail, events, tree, memory,
  isRunning, busy, error, toolResult,
  bootstrap, selectSession, createSession, deleteSession,
  generatePlan, confirmPlan, run, resume,
  invokeTool, resolveApproval, addTodos, updateTodo, runSubagent,
  writeMemory, forgetMemory, lastForgetEvidence, stopStream, clearError,
} = useCoding()

const dialogOpen = ref(false)

onMounted(async () => {
  await bootstrap()
  if (!activeId.value && sessions.value.length) {
    await selectSession(sessions.value[0].id)
  }
})

onBeforeUnmount(stopStream)

async function onCreate(payload: { task: string; workspace: string; policy_mode: string; title?: string }) {
  const created = await createSession(payload)
  if (created) dialogOpen.value = false
}

async function onDelete(id: string) {
  if (window.confirm('删除该编程会话？其事件流与记忆关联将解除。')) await deleteSession(id)
}

async function onInvoke(toolId: string, params: Record<string, unknown>) {
  await invokeTool(toolId, params)
}
</script>

<template>
  <div class="wb">
    <header class="wb-bar">
      <span class="seal wb-seal">编</span>
      <div class="wb-brand">
        <h1 class="wb-title">{{ overview?.name || '万枢编程框架' }}</h1>
        <p class="wb-sub">{{ overview?.positioning || '以万枢智能体/记忆/模型网关为内核的 AI 编程框架' }}</p>
      </div>

      <div class="wb-chips">
        <span class="wb-chip" :data-on="overview?.llm.available">
          模型网关 {{ overview?.llm.available ? '可用' : '未配置 · 启发式' }}
        </span>
        <span class="wb-chip">工具 {{ overview?.counts.tools ?? 0 }}</span>
        <span class="wb-chip">技能 {{ overview?.counts.skills ?? 0 }}</span>
        <span v-if="activeBrief" class="wb-chip" data-on>{{ activeBrief.policy_label }}档</span>
      </div>

      <button class="wb-back" type="button" @click="emit('exit')">返回对话</button>
    </header>

    <div v-if="error" class="wb-alert">
      <span>{{ error }}</span>
      <button type="button" aria-label="关闭" @click="clearError()">×</button>
    </div>

    <div class="wb-grid">
      <CodingSidebar
        :sessions="sessions"
        :active-id="activeId"
        :tree="tree"
        @select="selectSession"
        @create="dialogOpen = true"
        @delete="onDelete"
      />
      <CodingStage
        :detail="detail"
        :events="events"
        :is-running="isRunning"
        :busy="busy"
        @plan="(useLlm) => generatePlan(useLlm)"
        @confirm="(approved) => confirmPlan(approved)"
        @run="run()"
        @resume="resume()"
      />
      <CodingInspector
        :detail="detail"
        :tools="tools"
        :skills="skills"
        :roles="roles"
        :policy="policy"
        :memory="memory"
        :overview="overview"
        :busy="busy"
        :tool-result="toolResult"
        @approve="(id, ok) => resolveApproval(id, ok)"
        @invoke-tool="onInvoke"
        @add-todos="addTodos"
        @update-todo="updateTodo"
        @run-subagent="runSubagent"
        @write-memory="writeMemory"
        @forget-memory="forgetMemory"
        :forget-evidence="lastForgetEvidence"
      />
    </div>

    <NewSessionDialog
      v-if="dialogOpen"
      :submitting="busy.create"
      @close="dialogOpen = false"
      @create="onCreate"
    />
  </div>
</template>

<style scoped>
.wb { height: 100%; display: flex; flex-direction: column; min-height: 0; }

.wb-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--card) 70%, transparent);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
.wb-seal { width: 32px; height: 32px; font-size: 16px; }
.wb-brand { min-width: 0; }
.wb-title { font-family: var(--font-kai); font-size: 17px; letter-spacing: 3px; color: var(--ink); }
.wb-sub {
  margin-top: 2px;
  font-size: 11px;
  color: var(--ink-muted);
  letter-spacing: .5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 44vw;
}
.wb-chips { margin-left: auto; display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.wb-chip {
  padding: 3px 11px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line);
  background: var(--line-soft);
  color: var(--ink-muted);
  font-size: 11px;
  letter-spacing: .5px;
}
.wb-chip[data-on='true'] {
  border-color: color-mix(in srgb, var(--bamboo) 40%, transparent);
  background: color-mix(in srgb, var(--bamboo) 12%, transparent);
  color: color-mix(in srgb, var(--bamboo) 66%, var(--ink));
}
.wb-back {
  padding: 6px 14px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line);
  background: transparent;
  color: var(--ink-soft);
  font-size: 12px;
  letter-spacing: 1px;
  transition: all .18s ease;
}
.wb-back:hover { border-color: var(--gold-line); color: var(--ink); transform: translateY(-1px); }

.wb-alert {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 20px;
  background: color-mix(in srgb, var(--cinnabar) 12%, transparent);
  border-bottom: 1px solid var(--line-cinnabar);
  color: var(--cinnabar-deep);
  font-size: 12.5px;
}
.wb-alert span { flex: 1 1 auto; }
.wb-alert button {
  width: 22px; height: 22px;
  border: 0; border-radius: 6px;
  background: transparent;
  color: inherit;
  font-size: 16px;
  line-height: 1;
}
.wb-alert button:hover { background: color-mix(in srgb, var(--cinnabar) 18%, transparent); }

.wb-grid {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: 296px minmax(0, 1fr) 336px;
  overflow: hidden;
}

@media (max-width: 1320px) {
  .wb-grid { grid-template-columns: 258px minmax(0, 1fr) 300px; }
}
@media (max-width: 1080px) {
  .wb-grid { grid-template-columns: 240px minmax(0, 1fr); }
  .wb-grid :deep(.ins) {
    position: fixed;
    top: 0; right: 0; bottom: 0;
    width: min(360px, 90vw);
    z-index: 70;
    box-shadow: var(--shadow-lift);
    background: var(--bg);
  }
  .wb-sub { max-width: 30vw; }
}
</style>

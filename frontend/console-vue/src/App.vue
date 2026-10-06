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
 * App —— 宛委·枢忆控制台外壳（信息架构对齐 DeepSeek Harness Web UI）：
 *   侧栏（品牌 / 新智能体 / 列表 / 设置入口）
 *   中栏会话（英雄位 / 消息流 / 输入坞）
 *   右栏详情（档案 / 上下文 / 运行，可收起）
 *   设置与智能体编辑为模态浮层，不占路由。
 * 视觉：国风 gf 设计体系 + PetalFall 花瓣雨画布 + 双主题令牌。
 *
 * 双模式：``chat``（对话，默认）与 ``coding``（万枢编程工作台）。
 * 编程模式是"大于万枢平台"的形态——把智能体/记忆/模型网关作为内核，
 * 向外提供工具沙箱、计划待办、子智能体编排与可审计编程记忆。
 */
import { onMounted, ref } from 'vue'
import PetalFall from '@/components/gf/PetalFall.vue'
import ScrollProgress from '@/components/gf/ScrollProgress.vue'
import SidebarRoot from '@/shell/SidebarRoot.vue'
import ConversationRoot from '@/shell/ConversationRoot.vue'
import DetailsPanel from '@/shell/DetailsPanel.vue'
import SettingsModal from '@/shell/SettingsModal.vue'
import AgentEditor from '@/shell/AgentEditor.vue'
import CodingWorkbench from '@/views/coding/CodingWorkbench.vue'
import { useAgents } from '@/composables/useAgents'
import type { Agent } from '@/api/types'

const { selectedAgent, refresh, remove } = useAgents()

/** 顶层模式：chat=对话（默认） / coding=编程工作台 */
const mode = ref<'chat' | 'coding'>('chat')

const settingsOpen = ref(false)
const settingsSection = ref<string>('appearance')
const editorOpen = ref(false)
const editorAgent = ref<Agent | null>(null)
const detailsOpen = ref(true)

function openSettings(section?: string) {
  settingsSection.value = section ?? 'appearance'
  settingsOpen.value = true
}

function openNewAgent() {
  editorAgent.value = null
  editorOpen.value = true
}

function openEditAgent() {
  editorAgent.value = selectedAgent.value
  editorOpen.value = true
}

async function deleteSelectedAgent() {
  const agent = selectedAgent.value
  if (!agent) return
  if (window.confirm(`删除智能体「${agent.name}」？其本机对话记录与运行历史将不再关联。`)) {
    await remove(agent.id)
  }
}

onMounted(refresh)
</script>

<template>
  <div class="shell" :class="{ 'shell--full': mode === 'coding' }">
    <PetalFall />
    <ScrollProgress />

    <!-- 编程模式：万枢编程工作台（整屏） -->
    <CodingWorkbench v-if="mode === 'coding'" @exit="mode = 'chat'" />

    <!-- 对话模式：智能体控制台 -->
    <template v-else>
      <SidebarRoot
        @new-agent="openNewAgent"
        @open-settings="openSettings()"
      />

      <ConversationRoot
        @new-agent="openNewAgent"
        @open-settings="openSettings"
        @toggle-details="detailsOpen = !detailsOpen"
      />

      <Transition name="slide-x">
        <DetailsPanel
          v-if="detailsOpen"
          @edit-agent="openEditAgent"
          @delete-agent="deleteSelectedAgent"
        />
      </Transition>

      <SettingsModal
        v-if="settingsOpen"
        :key="settingsSection"
        :initial-section="settingsSection"
        @close="settingsOpen = false"
      />
      <AgentEditor
        v-if="editorOpen"
        :agent="editorAgent"
        @close="editorOpen = false"
        @saved="editorOpen = false"
      />
    </template>

    <!-- 模式切换入口（仅在对话模式显示） -->
    <button v-if="mode === 'chat'" class="mode-fab" type="button" title="进入万枢编程工作台" @click="mode = 'coding'">
      <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
        <path d="M6 4 2 8l4 4M10 4l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6"
              stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      编程
    </button>
  </div>
</template>

<style scoped>
.shell {
  height: 100%;
  display: grid;
  grid-template-columns: 272px minmax(0, 1fr) auto;
  overflow: hidden;
}
/* 编程模式：整屏单列，交给工作台自身三栏布局 */
.shell--full { grid-template-columns: minmax(0, 1fr); }

/* 模式切换悬浮入口（对话模式） */
.mode-fab {
  position: fixed;
  top: 16px;
  right: 18px;
  z-index: 60;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 15px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line-cinnabar);
  background: color-mix(in srgb, var(--card-solid) 82%, transparent);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  color: var(--cinnabar-deep);
  font-size: 12.5px;
  letter-spacing: 2px;
  box-shadow: var(--shadow-card);
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
}
.mode-fab:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lift);
  border-color: var(--rouge);
}

/* 右栏收起动画 */
.slide-x-enter-active,
.slide-x-leave-active {
  transition: transform .22s cubic-bezier(.4, 0, .2, 1), opacity .22s ease;
}
.slide-x-enter-from,
.slide-x-leave-to {
  transform: translateX(24px);
  opacity: 0;
}
@media (prefers-reduced-motion: reduce) {
  .slide-x-enter-active,
  .slide-x-leave-active { transition: none; }
}

/* 窄屏：侧栏收窄，详情栏覆盖式浮层 */
@media (max-width: 1080px) {
  .shell { grid-template-columns: 232px minmax(0, 1fr); }
  .shell :deep(.details) {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(340px, 88vw);
    z-index: 70;
    box-shadow: var(--shadow-lift);
  }
}
</style>

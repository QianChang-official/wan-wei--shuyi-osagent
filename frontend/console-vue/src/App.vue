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
 */
import { onMounted, ref } from 'vue'
import PetalFall from '@/components/gf/PetalFall.vue'
import ScrollProgress from '@/components/gf/ScrollProgress.vue'
import SidebarRoot from '@/shell/SidebarRoot.vue'
import ConversationRoot from '@/shell/ConversationRoot.vue'
import DetailsPanel from '@/shell/DetailsPanel.vue'
import SettingsModal from '@/shell/SettingsModal.vue'
import AgentEditor from '@/shell/AgentEditor.vue'
import { useAgents } from '@/composables/useAgents'
import type { Agent } from '@/api/types'

const { selectedAgent, refresh, remove } = useAgents()

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
  <div class="shell">
    <PetalFall />
    <ScrollProgress />

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
  </div>
</template>

<style scoped>
.shell {
  height: 100%;
  display: grid;
  grid-template-columns: 272px minmax(0, 1fr) auto;
  overflow: hidden;
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

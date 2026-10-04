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
/** CodingSidebar — 左栏：编程会话列表 + 工作区文件树 */
import { computed, ref } from 'vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import { formatTime } from '@/utils/format'
import type { FileNode, SessionBrief } from '@/api/coding'

const props = defineProps<{
  sessions: SessionBrief[]
  activeId: string
  tree: FileNode[]
}>()

const emit = defineEmits<{
  (e: 'select', id: string): void
  (e: 'create'): void
  (e: 'delete', id: string): void
}>()

/** 会话状态 → 标签色调 */
const STATE_TONE: Record<string, 'rouge' | 'dai' | 'bamboo' | 'gold' | 'ink'> = {
  drafting: 'ink', planning: 'dai', awaiting: 'gold',
  running: 'rouge', paused: 'gold', done: 'bamboo', failed: 'rouge', cancelled: 'ink',
}

const expanded = ref<Record<string, boolean>>({})
function toggle(path: string) { expanded.value[path] = !expanded.value[path] }

const hasTree = computed(() => props.tree.length > 0)

function progress(s: SessionBrief): number {
  if (!s.plan_total) return 0
  return Math.round((s.plan_done / s.plan_total) * 100)
}
</script>

<template>
  <aside class="cs">
    <header class="cs-hd">
      <h2 class="cs-title">编程会话</h2>
      <button class="cs-new" type="button" title="新建会话" @click="emit('create')">
        <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
          <path d="M8 2v12M2 8h12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
        新建
      </button>
    </header>

    <div class="cs-list">
      <GfEmpty v-if="!sessions.length" text="尚无会话，点「新建」开始" />
      <article
        v-for="s in sessions"
        :key="s.id"
        class="cs-item"
        :class="{ 'cs-item--on': s.id === activeId }"
        @click="emit('select', s.id)"
      >
        <div class="cs-item-hd">
          <span class="cs-item-title" :title="s.task">{{ s.title || '未命名会话' }}</span>
          <GfTag :tone="STATE_TONE[s.state] || 'ink'">{{ s.state_label }}</GfTag>
        </div>
        <p class="cs-item-task">{{ s.task }}</p>
        <div class="cs-item-meta">
          <span class="cs-ws" :title="s.workspace">{{ s.workspace }}</span>
          <span class="cs-time">{{ formatTime(s.updated_at) }}</span>
        </div>
        <div class="cs-progress" :aria-label="`计划进度 ${progress(s)}%`">
          <i :style="{ width: progress(s) + '%' }" />
        </div>
        <div class="cs-item-ft">
          <span class="cs-chip">{{ s.policy_label }}档</span>
          <span v-if="s.pending_approvals" class="cs-chip cs-chip--warn">
            {{ s.pending_approvals }} 项待审
          </span>
          <span class="cs-chip">{{ s.plan_done }}/{{ s.plan_total }} 步</span>
          <button class="cs-del" type="button" title="删除会话" @click.stop="emit('delete', s.id)">×</button>
        </div>
      </article>
    </div>

    <section v-if="hasTree" class="cs-tree">
      <h3 class="cs-tree-title">工作区</h3>
      <ul class="cs-tree-list">
        <template v-for="node in tree" :key="node.path">
          <li class="cs-node">
            <button class="cs-node-btn" type="button" @click="node.type === 'dir' && toggle(node.path)">
              <span class="cs-node-icon">{{ node.type === 'dir' ? (expanded[node.path] ? '▾' : '▸') : '·' }}</span>
              <span class="cs-node-name">{{ node.name }}</span>
            </button>
            <ul v-if="node.type === 'dir' && expanded[node.path] && node.children?.length" class="cs-node-kids">
              <li v-for="kid in node.children" :key="kid.path" class="cs-node cs-node--kid">
                <span class="cs-node-icon">{{ kid.type === 'dir' ? '▸' : '·' }}</span>
                <span class="cs-node-name">{{ kid.name }}</span>
              </li>
            </ul>
          </li>
        </template>
      </ul>
    </section>
  </aside>
</template>

<style scoped>
.cs {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg-soft) 42%, transparent);
}
.cs-hd {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px 10px;
}
.cs-title {
  font-family: var(--font-kai);
  font-size: 15px;
  letter-spacing: 3px;
  color: var(--ink);
}
.cs-new {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--line-cinnabar);
  background: color-mix(in srgb, var(--cinnabar) 9%, transparent);
  color: var(--cinnabar-deep);
  font-size: 12px;
  letter-spacing: 1px;
  transition: all .18s ease;
}
.cs-new:hover { background: color-mix(in srgb, var(--cinnabar) 16%, transparent); transform: translateY(-1px); }

.cs-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  gap: 8px;
  align-content: start;
  padding: 4px 12px 12px;
}
.cs-item {
  display: grid;
  gap: 7px;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  cursor: pointer;
  transition: border-color .18s ease, transform .18s ease, box-shadow .18s ease;
}
.cs-item:hover { border-color: var(--gold-line); transform: translateY(-1px); box-shadow: var(--shadow-card); }
.cs-item--on { border-color: var(--rouge); box-shadow: 0 0 0 3px var(--rouge-glow); }
.cs-item-hd { display: flex; align-items: center; gap: 8px; }
.cs-item-title {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cs-item-task {
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--ink-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.cs-item-meta { display: flex; align-items: center; gap: 8px; font-size: 10.5px; color: var(--ink-muted); }
.cs-ws {
  flex: 1 1 auto;
  min-width: 0;
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  direction: rtl;
  text-align: left;
}
.cs-progress { height: 3px; border-radius: 999px; background: var(--line-soft); overflow: hidden; }
.cs-progress i { display: block; height: 100%; background: linear-gradient(90deg, var(--rouge), var(--gold)); transition: width .3s ease; }
.cs-item-ft { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.cs-chip {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--line-soft);
  color: var(--ink-soft);
  font-size: 10px;
  letter-spacing: .5px;
}
.cs-chip--warn { background: color-mix(in srgb, var(--gold) 18%, transparent); color: color-mix(in srgb, var(--gold) 70%, var(--ink)); }
.cs-del {
  margin-left: auto;
  width: 20px; height: 20px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--ink-muted);
  font-size: 15px;
  line-height: 1;
  opacity: 0;
  transition: all .16s ease;
}
.cs-item:hover .cs-del { opacity: 1; }
.cs-del:hover { color: var(--cinnabar); background: var(--line-soft); }

.cs-tree {
  flex: 0 0 auto;
  max-height: 34%;
  overflow-y: auto;
  border-top: 1px solid var(--line-soft);
  padding: 10px 12px 14px;
}
.cs-tree-title {
  font-family: var(--font-kai);
  font-size: 12.5px;
  letter-spacing: 2px;
  color: var(--ink-soft);
  margin-bottom: 6px;
}
.cs-tree-list { display: grid; gap: 1px; }
.cs-node-btn, .cs-node--kid {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 3px 6px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  text-align: left;
  font-size: 12px;
  color: var(--ink-soft);
}
.cs-node-btn:hover { background: var(--line-soft); color: var(--ink); }
.cs-node-icon { width: 12px; color: var(--gold); font-size: 10px; }
.cs-node-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cs-node-kids { padding-left: 12px; }
.cs-node--kid { cursor: default; color: var(--ink-muted); }
</style>

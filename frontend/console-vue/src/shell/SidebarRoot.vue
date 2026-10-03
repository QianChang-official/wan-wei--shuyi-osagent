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
 * SidebarRoot —— 控制台侧栏（对齐 DeepSeek Harness 的信息架构）：
 * 品牌行（月洞门印章）→「新智能体」主按钮 → 智能体列表 → 底部
 * 主题/花瓣/设置入口与后端在线状态。梅枝 SVG 为手绘装饰。
 */
import { GEAR_LABELS, GEAR_TONES } from '@/utils/platformEnums'
import GfTag from '@/components/gf/GfTag.vue'
import ThemeToggle from '@/components/gf/ThemeToggle.vue'
import { getPetalsEnabled, setPetalsEnabled } from '@/components/gf/shared'
import { ref } from 'vue'
import { useAgents } from '@/composables/useAgents'
import { useHealth } from '@/composables/useHealth'

const emit = defineEmits<{
  (e: 'new-agent'): void
  (e: 'open-settings'): void
}>()

const { agents, loading, selectedId, select } = useAgents()
const { online, version } = useHealth()

const petalsOn = ref(getPetalsEnabled())
function togglePetals() {
  petalsOn.value = !petalsOn.value
  setPetalsEnabled(petalsOn.value)
}

/** 列表印章字：取名称首字 */
function sealChar(name: string): string {
  return (name || '？').trim().charAt(0) || '？'
}
</script>

<template>
  <aside class="sidebar">
    <!-- 品牌行：月洞门 + 名称 -->
    <div class="brand">
      <div class="moon-gate" aria-hidden="true">
        <span class="mg-char">枢</span>
      </div>
      <div class="brand-txt">
        <div class="bt-cn">宛委·枢忆</div>
        <div class="bt-en">花朝台 · 控制台</div>
      </div>
    </div>

    <!-- 新智能体 -->
    <button class="new-agent" type="button" @click="emit('new-agent')">
      <span class="na-plus">＋</span> 新智能体
    </button>

    <!-- 智能体列表 -->
    <nav class="agent-list" aria-label="智能体列表">
      <p v-if="loading && agents.length === 0" class="al-hint">载入中…</p>
      <p v-else-if="agents.length === 0" class="al-hint">尚无智能体，点击上方按钮创建</p>
      <button
        v-for="agent in agents"
        :key="agent.id"
        type="button"
        class="agent-row"
        :class="{ active: agent.id === selectedId }"
        @click="select(agent.id)"
      >
        <span class="ar-seal">{{ sealChar(agent.name) }}</span>
        <span class="ar-main">
          <b>{{ agent.name }}</b>
          <i>{{ agent.role || '通用智能体' }}</i>
        </span>
        <GfTag :tone="GEAR_TONES[agent.gear as keyof typeof GEAR_TONES] ?? 'ink'">
          {{ GEAR_LABELS[agent.gear as keyof typeof GEAR_LABELS] ?? agent.gear }}
        </GfTag>
      </button>
    </nav>

    <!-- 梅枝装饰 -->
    <div class="rail-plum" aria-hidden="true">
      <svg viewBox="0 0 240 84" width="100%" height="84" preserveAspectRatio="xMidYMax meet">
        <path d="M-8 82 Q 58 62 106 46 T 222 10" class="pl-branch" fill="none" />
        <path d="M108 45 Q 140 49 170 42" class="pl-branch pl-branch--thin" fill="none" />
        <path d="M58 64 Q 76 52 92 52" class="pl-branch pl-branch--thin" fill="none" />
        <g class="pl-blossom" transform="translate(96,50)">
          <circle cx="0" cy="-7" r="4" /><circle cx="6.7" cy="-2.2" r="4" />
          <circle cx="4.1" cy="5.8" r="4" /><circle cx="-4.1" cy="5.8" r="4" />
          <circle cx="-6.7" cy="-2.2" r="4" /><circle class="pl-heart" cx="0" cy="0" r="2.2" />
        </g>
        <g class="pl-blossom pl-blossom--soft" transform="translate(172,34) scale(.78)">
          <circle cx="0" cy="-7" r="4" /><circle cx="6.7" cy="-2.2" r="4" />
          <circle cx="4.1" cy="5.8" r="4" /><circle cx="-4.1" cy="5.8" r="4" />
          <circle cx="-6.7" cy="-2.2" r="4" /><circle class="pl-heart" cx="0" cy="0" r="2.2" />
        </g>
        <g class="pl-blossom pl-blossom--soft" transform="translate(216,12) scale(.6)">
          <circle cx="0" cy="-7" r="4" /><circle cx="6.7" cy="-2.2" r="4" />
          <circle cx="4.1" cy="5.8" r="4" /><circle cx="-4.1" cy="5.8" r="4" />
          <circle cx="-6.7" cy="-2.2" r="4" /><circle class="pl-heart" cx="0" cy="0" r="2.2" />
        </g>
        <circle cx="140" cy="46" r="2.4" class="pl-bud" />
        <circle cx="70" cy="60" r="2" class="pl-bud" />
        <circle cx="196" cy="22" r="2" class="pl-bud" />
      </svg>
    </div>

    <!-- 底部：主题 / 花瓣 / 设置 / 状态 -->
    <footer class="rail-foot">
      <div class="rf-actions">
        <ThemeToggle />
        <button
          class="rf-btn"
          type="button"
          :class="{ off: !petalsOn }"
          :aria-pressed="petalsOn"
          :title="petalsOn ? '合上花瓣雨' : '撒下花瓣雨'"
          @click="togglePetals"
        >
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
            <g fill="currentColor">
              <circle cx="8" cy="3.2" r="2.4" /><circle cx="12.6" cy="6.5" r="2.4" />
              <circle cx="11" cy="11.8" r="2.4" /><circle cx="5" cy="11.8" r="2.4" />
              <circle cx="3.4" cy="6.5" r="2.4" />
            </g>
            <circle cx="8" cy="8" r="1.6" fill="var(--gold)" />
          </svg>
        </button>
        <button class="rf-btn" type="button" title="设置" @click="emit('open-settings')">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
            stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 8.6a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 8.92 4.2a1.65 1.65 0 0 0 1-1.51V2.6a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 8.6v0a1.65 1.65 0 0 0 1.51 1h.09a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
          </svg>
        </button>
      </div>
      <div class="rf-status" :class="{ on: online }">
        <span class="status-dot" :class="{ on: online }"></span>
        <span>{{ online ? '后端在线' : '后端离线' }}</span>
        <em v-if="online && version">{{ version }}</em>
      </div>
    </footer>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--card);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border-right: 1px solid var(--line);
}

/* ── 品牌 ── */
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 16px 14px;
}
.moon-gate {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at 50% 38%, var(--rouge-glow), transparent 68%),
    var(--card-solid);
  border: 1.5px solid var(--gold-line);
  box-shadow: var(--shadow-seal);
}
.mg-char {
  font-family: var(--font-kai);
  font-size: 22px;
  font-weight: 700;
  color: var(--cinnabar);
  text-shadow: 0 0 12px var(--rouge-glow);
}
.bt-cn {
  font-family: var(--font-kai);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 2px;
}
.bt-en {
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--ink-muted);
  margin-top: 2px;
}

/* ── 新智能体 ── */
.new-agent {
  margin: 4px 14px 12px;
  padding: 10px 14px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  font-size: 14px;
  font-family: var(--font-kai);
  letter-spacing: 2px;
  box-shadow: var(--shadow-seal);
  transition: transform .2s ease, box-shadow .2s ease;
}
.new-agent:hover { transform: translateY(-2px); box-shadow: var(--shadow-lift); }
.na-plus { margin-right: 6px; font-weight: 700; }

/* ── 列表 ── */
.agent-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.al-hint {
  padding: 18px 8px;
  text-align: center;
  color: var(--ink-muted);
  font-size: 12px;
  letter-spacing: 1px;
}
.agent-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-small);
  background: transparent;
  text-align: left;
  transition: background .18s ease, border-color .18s ease, transform .18s ease;
}
.agent-row:hover { background: var(--bg-soft); transform: translateX(2px); }
.agent-row.active {
  background: var(--bg-soft);
  border-color: var(--gold-line);
  box-shadow: inset 2px 0 0 var(--cinnabar);
}
.ar-seal {
  flex: none;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  font-family: var(--font-kai);
  font-weight: 700;
  font-size: 15px;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: var(--shadow-seal);
}
.ar-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.ar-main b {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ar-main i {
  font-style: normal;
  font-size: 11px;
  color: var(--ink-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── 梅枝 ── */
.rail-plum { padding: 4px 6px 0; pointer-events: none; }
.pl-branch { stroke: var(--ochre); stroke-width: 2.4; stroke-linecap: round; opacity: .55; }
.pl-branch--thin { stroke-width: 1.4; opacity: .4; }
.pl-blossom { fill: var(--rouge); opacity: .8; }
.pl-blossom--soft { opacity: .5; }
.pl-heart { fill: var(--gold); }
.pl-bud { fill: var(--rouge); opacity: .45; }

/* ── 底部 ── */
.rail-foot {
  padding: 10px 14px 14px;
  border-top: 1px solid var(--line-soft);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.rf-actions { display: flex; align-items: center; gap: 8px; }
.rf-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  border: 1px solid var(--gold-line);
  background: var(--card);
  color: var(--rouge);
  transition: transform .2s ease, box-shadow .2s ease, opacity .2s ease;
}
.rf-btn:hover { transform: translateY(-2px); box-shadow: var(--shadow-glow-rouge); }
.rf-btn.off { opacity: .45; }
.rf-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--ink-muted);
  letter-spacing: 1px;
}
.rf-status em { font-style: normal; color: var(--gold); }
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ink-muted);
  box-shadow: 0 0 6px transparent;
}
.status-dot.on {
  background: var(--bamboo);
  box-shadow: 0 0 8px var(--bamboo);
  animation: pulse 2.4s ease-in-out infinite;
}
@keyframes pulse { 50% { opacity: .55; } }
@media (prefers-reduced-motion: reduce) { .status-dot.on { animation: none; } }
</style>

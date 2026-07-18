<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { setApiKey } from '@/api/client'
import { useHealth } from '@/composables/useHealth'
import PetalFall from '@/components/gf/PetalFall.vue'
import ScrollProgress from '@/components/gf/ScrollProgress.vue'
import ThemeToggle from '@/components/gf/ThemeToggle.vue'
import { getPetalsEnabled, setPetalsEnabled } from '@/components/gf/shared'

const { online, version } = useHealth()
const apiKey = ref('')
function updateApiKey() { setApiKey(apiKey.value) }

const route = useRoute()
const pageSeal = computed(() => (route.meta.seal as string) || '枢')
const pageTitle = computed(() => (route.meta.title as string) || '花朝台')

const petalsOn = ref(getPetalsEnabled())
function togglePetals() {
  petalsOn.value = !petalsOn.value
  setPetalsEnabled(petalsOn.value)
}

const navGroups = [
  {
    title: '平台舱室',
    items: [
      { to: '/', seal: '枢', name: '总览', en: 'Overview' },
      { to: '/pillars', seal: '架', name: '主线架构', en: 'Architecture' },
      { to: '/platform', seal: '舱', name: '平台舱室', en: 'Modules' },
      { to: '/model-gateway', seal: '玄', name: '通玄模型舱', en: 'Gateway' },
      { to: '/skills', seal: '工', name: '百工技能舱', en: 'MCP Skills' },
      { to: '/tuning', seal: '南', name: '司南调参舱', en: 'Tuning' },
      { to: '/exports', seal: '笈', name: '云笈导出舱', en: 'Exports' },
    ],
  },
  {
    title: '研究吸收',
    items: [
      { to: '/research-adoption', seal: '研', name: '权威吸收', en: 'Research' },
      { to: '/workflow', seal: '流', name: '工作流闭环', en: 'Workflow Run' },
      { to: '/reproduction', seal: '复', name: '论文复现', en: 'Reproduction' },
      { to: '/deepening', seal: '问', name: '深做追问', en: 'Deepening' },
    ],
  },
  {
    title: '灵魂觉醒',
    items: [
      { to: '/soul', seal: '灵', name: '灵魂状态', en: 'Soul' },
      { to: '/chat', seal: '话', name: '灵魂对话', en: 'Chat' },
      { to: '/dream', seal: '梦', name: '梦境日志', en: 'Dream' },
    ],
  },
  {
    title: '万枢协作',
    items: [
      { to: '/platform/workbench', seal: '枢', name: '万枢工作台', en: 'Workbench' },
      { to: '/platform/providers', seal: '接', name: '模型接入', en: 'Providers' },
      { to: '/platform/agents', seal: '智', name: '智能体', en: 'Agents' },
      { to: '/platform/spaces', seal: '域', name: '空间', en: 'Spaces' },
      { to: '/platform/automation', seal: '自', name: '自动化', en: 'Automation' },
      { to: '/platform/knowledge', seal: '知', name: '知识库', en: 'Knowledge' },
      { to: '/platform/memory', seal: '心', name: '记忆中枢', en: 'Memory' },
      { to: '/platform/sessions', seal: '笺', name: '会话管理', en: 'Sessions' },
      { to: '/platform/settings', seal: '设', name: '通用设置', en: 'Settings' },
      { to: '/platform/help', seal: '助', name: '帮助', en: 'Help' },
    ],
  },
]
</script>

<template>
  <div class="shell">
    <!-- 全站氛围层 -->
    <PetalFall />
    <ScrollProgress />

    <!-- 柔化屏风侧边栏 -->
    <aside class="rail">
      <!-- 月洞门品牌区 -->
      <div class="brand">
        <div class="moon-gate" aria-hidden="true">
          <span class="mg-char">枢</span>
        </div>
        <div class="brand-txt">
          <div class="bt-cn">宛委·枢忆</div>
          <div class="bt-en">花朝台 · MemoryOps</div>
        </div>
      </div>

      <!-- 屏风导航 -->
      <nav class="nav">
        <div v-for="(group, gi) in navGroups" :key="group.title" class="screen-panel" :class="`panel-${gi}`">
          <div class="panel-hinge" v-if="gi > 0"></div>
          <div class="panel-title">
            <span>{{ group.title }}</span>
          </div>
          <RouterLink
            v-for="n in group.items"
            :key="n.to"
            :to="n.to"
            class="nav-item"
          >
            <span class="ni-seal">{{ n.seal }}</span>
            <span class="ni-txt">
              <b>{{ n.name }}</b>
              <i>{{ n.en }}</i>
            </span>
          </RouterLink>
        </div>
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

      <!-- API 密钥 -->
      <div class="api-auth">
        <label for="api-key">密钥</label>
        <input id="api-key" v-model="apiKey" type="password" autocomplete="off"
          placeholder="生产模式密钥…" @input="updateApiKey"/>
      </div>

      <!-- 状态 -->
      <div class="rail-foot">
        <span class="status-dot" :class="{ on: online }"></span>
        <span>{{ online ? '后端在线' : '后端离线' }}</span>
        <em v-if="online">{{ version }}</em>
      </div>
    </aside>

    <!-- 主内容区 -->
    <main class="stage">
      <!-- 顶栏 -->
      <header class="topbar">
        <div class="tb-page">
          <span class="tb-seal">{{ pageSeal }}</span>
          <span class="tb-title">{{ pageTitle }}</span>
        </div>
        <div class="tb-actions">
          <button
            class="tb-petal"
            type="button"
            :class="{ off: !petalsOn }"
            :aria-pressed="petalsOn"
            :title="petalsOn ? '合上花瓣雨' : '撒下花瓣雨'"
            @click="togglePetals"
          >
            <svg viewBox="0 0 16 16" width="15" height="15">
              <g fill="currentColor">
                <circle cx="8" cy="3.2" r="2.4" /><circle cx="12.6" cy="6.5" r="2.4" />
                <circle cx="11" cy="11.8" r="2.4" /><circle cx="5" cy="11.8" r="2.4" />
                <circle cx="3.4" cy="6.5" r="2.4" />
              </g>
              <circle cx="8" cy="8" r="1.5" fill="var(--gold)" />
            </svg>
          </button>
          <ThemeToggle />
        </div>
      </header>

      <div class="stage-body">
        <RouterView v-slot="{ Component }">
          <Transition name="scroll" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </div>
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: 268px 1fr;
  min-height: 100vh;
}

/* ══ 侧边栏：半透明宣纸 + 金线（昼） / 靛青（夜） ══ */
.rail {
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: hidden;
  color: var(--ink-soft);
  background: linear-gradient(180deg, rgba(255, 253, 248, .82), rgba(245, 237, 220, .66));
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-right: 1px solid var(--gold-line);
  box-shadow: 1px 0 18px rgba(51, 46, 42, .05);
  transition: background .3s ease;
}
:root[data-theme='night'] .rail {
  background: linear-gradient(180deg, rgba(27, 30, 46, .9), rgba(18, 20, 31, .84));
  box-shadow: 1px 0 18px rgba(0, 0, 0, .3);
}

/* ── 月洞门品牌区 ── */
.brand {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 20px 18px 16px;
  border-bottom: 1px solid var(--line-soft);
}
.moon-gate {
  width: 54px;
  height: 54px;
  border-radius: 50%;
  border: 1.5px solid var(--gold-line);
  display: grid;
  place-items: center;
  flex-shrink: 0;
  box-shadow: 0 0 0 4px var(--line-soft), 0 0 18px var(--rouge-glow);
  background: var(--card);
}
.mg-char {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-family: var(--font-kai);
  font-size: 18px;
  font-weight: 700;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  box-shadow: 0 0 12px var(--cinnabar-glow);
}
.bt-cn { font-family: var(--font-kai); font-size: 18px; letter-spacing: 4px; color: var(--ink); }
.bt-en { font-size: 9.5px; letter-spacing: 1.5px; color: var(--ink-muted); margin-top: 4px; }

/* ── 屏风导航面板 ── */
.nav {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: thin;
  padding-bottom: 6px;
}
.screen-panel { position: relative; padding: 0 0 4px; }

.panel-hinge {
  height: 1px;
  margin: 6px 16px;
  background: linear-gradient(90deg, transparent, var(--gold-line), transparent);
}

.panel-title {
  font-size: 10px;
  letter-spacing: 3px;
  color: var(--ink-muted);
  padding: 10px 18px 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--gold-line), transparent);
  opacity: .6;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 2px 10px;
  padding: 7px 10px;
  border-radius: var(--radius-small);
  color: var(--ink-soft);
  text-decoration: none;
  transition: background .18s ease, color .18s ease, transform .18s ease;
  position: relative;
}
.nav-item:hover {
  background: var(--rouge-soft);
  color: var(--ink);
  transform: translateX(2px);
}
:root[data-theme='night'] .nav-item:hover { background: rgba(240, 166, 190, .1); }
.nav-item.router-link-exact-active {
  background: linear-gradient(90deg, var(--rouge-soft), transparent 130%);
  color: var(--cinnabar);
  box-shadow: inset 2px 0 0 var(--cinnabar);
}
:root[data-theme='night'] .nav-item.router-link-exact-active {
  background: linear-gradient(90deg, rgba(224, 101, 90, .16), transparent 130%);
}

.ni-seal {
  font-family: var(--font-kai);
  font-size: 13px;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border: 1px solid var(--gold-line);
  border-radius: var(--radius-seal);
  flex-shrink: 0;
  transition: all .18s ease;
}
.nav-item.router-link-exact-active .ni-seal {
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-color: transparent;
  color: #FDF6E9;
  box-shadow: 0 0 10px var(--cinnabar-glow);
}
.ni-txt { display: flex; flex-direction: column; line-height: 1.25; }
.ni-txt b { font-size: 13px; font-weight: 600; letter-spacing: 1px; }
.ni-txt i { font-size: 9.5px; opacity: .5; font-style: normal; letter-spacing: .5px; }

/* ── 梅枝装饰 ── */
.rail-plum {
  padding: 4px 10px 0;
  opacity: .9;
  pointer-events: none;
}
.pl-branch { stroke: var(--gold); stroke-width: 1.6; stroke-linecap: round; opacity: .55; }
.pl-branch--thin { stroke-width: 1.1; opacity: .4; }
.pl-blossom circle { fill: var(--rouge); opacity: .8; }
.pl-blossom--soft circle { opacity: .55; }
.pl-blossom .pl-heart { fill: var(--gold); opacity: .95; }
.pl-bud { fill: var(--rouge); opacity: .45; }

/* ── API 密钥 ── */
.api-auth {
  padding: 10px 16px;
  border-top: 1px solid var(--line-soft);
}
.api-auth label {
  display: block;
  font-size: 10px;
  letter-spacing: 2px;
  color: var(--ink-muted);
  margin-bottom: 6px;
  font-family: var(--font-kai);
}
.api-auth input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 7px 10px;
  font-size: 11px;
  font-family: var(--font-mono);
  transition: border-color .18s ease, box-shadow .18s ease;
}
.api-auth input:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.api-auth input::placeholder { color: var(--ink-muted); opacity: .6; }

/* ── 状态栏 ── */
.rail-foot {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  color: var(--ink-muted);
  padding: 10px 16px 14px;
  border-top: 1px solid var(--line-soft);
}
.status-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--line); flex-shrink: 0;
  transition: background .2s ease;
}
.status-dot.on {
  background: var(--bamboo);
  box-shadow: 0 0 8px var(--bamboo);
}
.rail-foot em {
  margin-left: auto; font-style: normal;
  font-size: 9.5px; font-family: var(--font-mono);
  color: var(--ink-muted); opacity: .7;
}

/* ══ 主内容区 ══ */
.stage { min-height: 100vh; position: relative; }

.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 32px;
  background: var(--card);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--line-soft);
}
.tb-page { display: flex; align-items: center; gap: 10px; min-width: 0; }
.tb-seal {
  font-family: var(--font-kai);
  font-size: 12px;
  font-weight: 700;
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  color: #FDF6E9;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  border-radius: var(--radius-seal);
  box-shadow: 0 0 8px var(--cinnabar-glow);
  flex-shrink: 0;
}
.tb-title {
  font-family: var(--font-kai);
  font-size: 16px;
  letter-spacing: 4px;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tb-actions { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.tb-petal {
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
.tb-petal:hover { transform: translateY(-2px) rotate(-10deg); box-shadow: var(--shadow-glow-rouge); }
.tb-petal.off { opacity: .38; filter: grayscale(.6); }

.stage-body { padding: 28px 40px 48px; }

/* ══ 柔和卷轴过渡：fade + translateY(14px) + scale(.98)，280ms ══ */
.scroll-enter-active {
  transition: opacity .28s ease-out, transform .28s ease-out;
}
.scroll-leave-active {
  transition: opacity .16s ease-in, transform .16s ease-in;
}
.scroll-enter-from { opacity: 0; transform: translateY(14px) scale(.98); }
.scroll-leave-to { opacity: 0; transform: translateY(-6px) scale(.99); }

/* ══ 窄屏：侧栏折叠为顶部横排 ══ */
@media (max-width: 860px) {
  .shell { grid-template-columns: 1fr; }
  .rail {
    position: relative;
    height: auto;
    border-right: none;
    border-bottom: 1px solid var(--gold-line);
  }
  .brand { padding: 14px 16px 10px; }
  .moon-gate { width: 44px; height: 44px; }
  .mg-char { width: 30px; height: 30px; font-size: 15px; }
  .nav {
    display: flex;
    overflow-x: auto;
    overflow-y: hidden;
    padding-bottom: 4px;
  }
  .screen-panel {
    display: flex;
    align-items: center;
    flex-shrink: 0;
    padding: 0 6px;
  }
  .panel-hinge {
    width: 1px;
    height: 28px;
    margin: 0 6px;
    align-self: center;
    background: linear-gradient(180deg, transparent, var(--gold-line), transparent);
  }
  .panel-title { display: none; }
  .nav-item { margin: 4px 2px; padding: 6px 9px; }
  .ni-txt i { display: none; }
  .rail-plum { display: none; }
  .api-auth { border-top: 1px solid var(--line-soft); }
  .stage-body { padding: 20px 18px 40px; }
  .topbar { padding: 10px 18px; }
}
</style>

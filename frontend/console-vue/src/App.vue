<script setup lang="ts">
import { ref } from 'vue'
import { setApiKey } from '@/api/client'
import { useHealth } from '@/composables/useHealth'

const { online, version } = useHealth()
const apiKey = ref('')
function updateApiKey() { setApiKey(apiKey.value) }

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
    title: '运行闭环',
    items: [
      { to: '/capsules', seal: '忆', name: '记忆容器', en: 'Capsules' },
      { to: '/search', seal: '琅', name: '可信检索', en: 'Search' },
      { to: '/command', seal: '司', name: '指挥闭环', en: 'Command' },
      { to: '/reflection', seal: '省', name: '复盘演化', en: 'Reflection' },
      { to: '/audit', seal: '台', name: '审计流水', en: 'Audit' },
    ],
  },
]
</script>

<template>
  <div class="shell">
    <!-- 屏风式侧边栏 -->
    <aside class="rail">
      <!-- 品牌印章 -->
      <div class="brand">
        <div class="brand-seal">
          <span>枢</span>
          <span>忆</span>
        </div>
        <div class="brand-txt">
          <div class="bt-cn">宛委·枢忆</div>
          <div class="bt-en">MemoryOps Console</div>
        </div>
      </div>

      <!-- 屏风导航 -->
      <nav class="nav">
        <div v-for="(group, gi) in navGroups" :key="group.title" class="screen-panel" :class="`panel-${gi}`">
          <!-- 屏风折叠线 -->
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
      <RouterView v-slot="{ Component }">
        <Transition name="scroll" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: 268px 1fr;
  min-height: 100vh;
}

/* ══ 屏风侧边栏 ══ */
.rail {
  background: linear-gradient(180deg, #1C1914 0%, #141210 100%);
  color: #EAE0C8;
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: hidden;
  /* 屏风竖纹 */
  background-image:
    linear-gradient(180deg, #1C1914 0%, #141210 100%),
    repeating-linear-gradient(90deg,
      transparent 0px, transparent 30px,
      rgba(200,153,31,.04) 30px, rgba(200,153,31,.04) 31px
    );
  border-right: 2px solid rgba(200,153,31,.25);
  /* 右侧金线阴影模拟屏风边框 */
  box-shadow: 2px 0 12px rgba(0,0,0,.35), inset -1px 0 0 rgba(200,153,31,.1);
}

/* ── 品牌区 ── */
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 16px 14px;
  border-bottom: 1px solid rgba(200,153,31,.2);
  background: rgba(0,0,0,.15);
}
.brand-seal {
  font-family: var(--kai);
  font-size: 16px;
  font-weight: 700;
  line-height: 1.1;
  width: 44px;
  height: 44px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--cinnabar);
  color: #F8EDD8;
  border-radius: 2px;
  flex-shrink: 0;
  box-shadow: 0 0 20px rgba(178,58,46,.5), 0 0 6px rgba(178,58,46,.3);
  position: relative;
}
.brand-seal::before {
  content: '';
  position: absolute;
  inset: 3px;
  border: 1px solid rgba(248,237,216,.3);
  border-radius: 1px;
}
.bt-cn { font-family: var(--kai); font-size: 16px; letter-spacing: 3px; color: #F0E4C8; }
.bt-en { font-size: 9.5px; letter-spacing: 1.5px; color: rgba(234,224,200,.4); margin-top: 3px; }

/* ── 屏风导航面板 ── */
.nav {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: thin;
  scrollbar-color: rgba(178,58,46,.25) transparent;
}

.screen-panel {
  position: relative;
  padding: 0 0 6px;
  /* 每块面板有轻微的透视感 */
  background: linear-gradient(180deg,
    rgba(255,255,255,.025) 0%,
    rgba(255,255,255,.01) 100%
  );
}

/* 屏风折叠线（面板间的铰链） */
.panel-hinge {
  height: 8px;
  background:
    linear-gradient(180deg,
      rgba(0,0,0,.4) 0%,
      rgba(200,153,31,.15) 40%,
      rgba(200,153,31,.15) 60%,
      rgba(0,0,0,.3) 100%
    );
  margin: 0;
  position: relative;
}
.panel-hinge::before,
.panel-hinge::after {
  content: '';
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(200,153,31,.5);
  box-shadow: 0 0 4px rgba(200,153,31,.4);
}
.panel-hinge::before { left: 20px; }
.panel-hinge::after { right: 20px; }

.panel-title {
  font-size: 9.5px;
  letter-spacing: 3px;
  color: rgba(234,224,200,.35);
  padding: 10px 16px 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, rgba(200,153,31,.2), transparent);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 14px;
  color: #C4B898;
  text-decoration: none;
  transition: background .15s, color .15s;
  position: relative;
  border-left: 2px solid transparent;
}
.nav-item:hover {
  background: rgba(234,224,200,.06);
  color: #EAE0C8;
  border-left-color: rgba(200,153,31,.3);
}
.nav-item.router-link-exact-active {
  background: rgba(178,58,46,.15);
  color: #F3E9CE;
  border-left-color: var(--cinnabar);
}
/* 激活态右侧印章光晕 */
.nav-item.router-link-exact-active::after {
  content: '';
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: linear-gradient(180deg, transparent, rgba(178,58,46,.4), transparent);
}

.ni-seal {
  font-family: var(--kai);
  font-size: 13px;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(196,184,152,.25);
  border-radius: 2px;
  flex-shrink: 0;
  transition: all .15s;
}
.nav-item.router-link-exact-active .ni-seal {
  background: rgba(178,58,46,.25);
  border-color: rgba(178,58,46,.55);
  box-shadow: 0 0 8px rgba(178,58,46,.25);
}
.ni-txt { display: flex; flex-direction: column; line-height: 1.2; }
.ni-txt b { font-size: 13px; font-weight: 600; }
.ni-txt i { font-size: 9.5px; opacity: .45; font-style: normal; }

/* ── API 密钥 ── */
.api-auth {
  padding: 10px 14px;
  border-top: 1px solid rgba(200,153,31,.15);
  background: rgba(0,0,0,.1);
}
.api-auth label {
  display: block;
  font-size: 9px;
  letter-spacing: 2px;
  color: rgba(234,224,200,.4);
  margin-bottom: 6px;
  font-family: var(--kai);
}
.api-auth input {
  width: 100%;
  border: 1px solid rgba(234,224,200,.12);
  border-radius: 1px;
  background: rgba(255,255,255,.04);
  color: #EAE0C8;
  padding: 6px 9px;
  font-size: 11px;
  font-family: var(--mono);
}
.api-auth input:focus {
  outline: none;
  border-color: rgba(178,58,46,.5);
}
.api-auth input::placeholder { color: rgba(234,224,200,.2); }

/* ── 状态栏 ── */
.rail-foot {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  color: rgba(234,224,200,.45);
  padding: 10px 14px;
  border-top: 1px solid rgba(200,153,31,.12);
  background: rgba(0,0,0,.15);
}
.status-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: rgba(234,224,200,.2); flex-shrink: 0;
}
.status-dot.on {
  background: #6A9E7F;
  box-shadow: 0 0 7px #4E7A62, 0 0 3px #6A9E7F;
}
.rail-foot em {
  margin-left: auto; font-style: normal;
  font-size: 9.5px; font-family: var(--mono);
  color: rgba(234,224,200,.3);
}

/* ══ 主内容区 ══ */
.stage {
  padding: 36px 44px;
  background-color: var(--xuan);
  background-image: url('@/assets/shanshui.svg');
  background-size: cover;
  background-position: center top;
  background-repeat: no-repeat;
  background-attachment: fixed;
  min-height: 100vh;
}

/* ══ 卷轴展开动效 ══ */
.scroll-enter-active {
  animation: unroll .35s cubic-bezier(.22,.68,0,1.2);
  transform-origin: top center;
}
.scroll-leave-active {
  animation: rollup .22s ease-in;
  transform-origin: top center;
}
@keyframes unroll {
  from { transform: scaleY(0.04); opacity: 0; }
  to   { transform: scaleY(1);    opacity: 1; }
}
@keyframes rollup {
  from { transform: scaleY(1);    opacity: 1; }
  to   { transform: scaleY(0.04); opacity: 0; }
}

@media (max-width: 860px) {
  .shell { grid-template-columns: 1fr; }
  .rail { position: relative; height: auto; }
  .stage { padding: 24px 20px; background-attachment: scroll; }
}
</style>

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
    <aside class="rail">
      <!-- 品牌印章区 -->
      <div class="brand">
        <div class="brand-seal seal">
          <span>枢</span>
          <span>忆</span>
        </div>
        <div class="brand-txt">
          <div class="bt-cn">宛委·枢忆</div>
          <div class="bt-en">MemoryOps Console</div>
        </div>
      </div>

      <div class="ink-divider rail-divider"></div>

      <!-- 导航 -->
      <nav class="nav">
        <section v-for="group in navGroups" :key="group.title" class="nav-group">
          <div class="nav-title">
            <span class="nav-title-line"></span>
            <span>{{ group.title }}</span>
            <span class="nav-title-line"></span>
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
            <span class="ni-arrow">›</span>
          </RouterLink>
        </section>
      </nav>

      <div class="ink-divider rail-divider"></div>

      <!-- API 密钥 -->
      <div class="api-auth">
        <label for="api-key">
          <span class="auth-icon">🔑</span> API Key
        </label>
        <input
          id="api-key"
          v-model="apiKey"
          type="password"
          autocomplete="off"
          placeholder="生产模式密钥…"
          @input="updateApiKey"
        />
        <small>仅保存在当前页面内存，不上传</small>
      </div>

      <!-- 状态栏 -->
      <div class="rail-foot">
        <span class="status-dot" :class="{ on: online }"></span>
        <span class="status-txt">{{ online ? '后端在线' : '后端离线' }}</span>
        <em v-if="online" class="status-ver">{{ version }}</em>
      </div>
    </aside>

    <main class="stage">
      <RouterView v-slot="{ Component }">
        <Transition name="page" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>
  </div>
</template>

<style scoped>
/* ── 整体布局 ── */
.shell {
  display: grid;
  grid-template-columns: 272px 1fr;
  min-height: 100vh;
}

/* ── 侧边栏 ── */
.rail {
  background:
    linear-gradient(180deg, #1E1B16 0%, #161310 60%, #0F0D0A 100%);
  color: #EAE0C8;
  padding: 20px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 0;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: hidden;
  border-right: 1px solid rgba(200,153,31,.2);
  /* 竖向暗纹 */
  background-image:
    linear-gradient(180deg, #1E1B16 0%, #161310 60%, #0F0D0A 100%),
    repeating-linear-gradient(
      90deg,
      transparent,
      transparent 31px,
      rgba(200,153,31,.025) 31px,
      rgba(200,153,31,.025) 32px
    );
}

/* ── 品牌区 ── */
.brand {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-bottom: 18px;
}
.brand-seal {
  font-family: var(--kai);
  font-size: 17px;
  font-weight: 700;
  line-height: 1.1;
  width: 46px;
  height: 46px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--cinnabar);
  color: #F8EDD8;
  border-radius: 3px;
  box-shadow: var(--shadow-seal);
  flex-shrink: 0;
  position: relative;
}
.brand-seal::before {
  content: '';
  position: absolute;
  inset: 3px;
  border: 1px solid rgba(248,237,216,.25);
  border-radius: 1px;
}
.bt-cn {
  font-family: var(--kai);
  font-size: 17px;
  letter-spacing: 3px;
  color: #F0E4C8;
}
.bt-en {
  font-size: 10px;
  letter-spacing: 1.5px;
  color: rgba(234,224,200,.45);
  margin-top: 3px;
}

/* ── 分隔线 ── */
.rail-divider {
  background: linear-gradient(90deg, transparent, rgba(200,153,31,.3) 30%, rgba(200,153,31,.3) 70%, transparent);
  height: 1px;
  margin: 0 -16px;
}

/* ── 导航 ── */
.nav {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 14px 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
  scrollbar-width: thin;
  scrollbar-color: rgba(178,58,46,.3) transparent;
}
.nav-group { display: flex; flex-direction: column; gap: 2px; }

.nav-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  letter-spacing: 2.5px;
  color: rgba(234,224,200,.35);
  padding: 2px 4px 8px;
}
.nav-title-line {
  flex: 1;
  height: 1px;
  background: rgba(200,153,31,.18);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-radius: 2px;
  color: #C4B898;
  text-decoration: none;
  transition: background .15s, color .15s, border-color .15s;
  border: 1px solid transparent;
  position: relative;
}
.nav-item:hover {
  background: rgba(234,224,200,.07);
  color: #EAE0C8;
  border-color: rgba(200,153,31,.15);
}
.nav-item.router-link-exact-active {
  background: rgba(178,58,46,.18);
  color: #F3E9CE;
  border-color: rgba(178,58,46,.45);
}
.nav-item.router-link-exact-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 2px;
  background: var(--cinnabar);
  border-radius: 0 1px 1px 0;
}

.ni-seal {
  font-family: var(--kai);
  font-size: 14px;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(196,184,152,.3);
  border-radius: 2px;
  flex-shrink: 0;
  transition: background .15s, border-color .15s;
}
.nav-item.router-link-exact-active .ni-seal {
  background: rgba(178,58,46,.3);
  border-color: rgba(178,58,46,.6);
}
.ni-txt {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
  flex: 1;
}
.ni-txt b { font-size: 13.5px; font-weight: 600; }
.ni-txt i { font-size: 10px; opacity: .5; font-style: normal; margin-top: 1px; }
.ni-arrow {
  font-size: 14px;
  opacity: 0;
  color: var(--cinnabar);
  transition: opacity .15s;
}
.nav-item:hover .ni-arrow,
.nav-item.router-link-exact-active .ni-arrow { opacity: .7; }

/* ── API 密钥 ── */
.api-auth {
  padding: 14px 0 10px;
}
.api-auth label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  letter-spacing: 1.5px;
  color: rgba(234,224,200,.45);
  margin-bottom: 7px;
}
.auth-icon { font-size: 11px; }
.api-auth input {
  width: 100%;
  border: 1px solid rgba(234,224,200,.15);
  border-radius: 2px;
  background: rgba(255,255,255,.04);
  color: #EAE0C8;
  padding: 7px 10px;
  font-size: 12px;
  font-family: var(--mono);
  transition: border-color .15s;
}
.api-auth input:focus {
  outline: none;
  border-color: rgba(178,58,46,.6);
  background: rgba(255,255,255,.06);
}
.api-auth input::placeholder { color: rgba(234,224,200,.25); }
.api-auth small {
  display: block;
  margin-top: 5px;
  font-size: 9px;
  color: rgba(234,224,200,.3);
  letter-spacing: .5px;
}

/* ── 状态栏 ── */
.rail-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: rgba(234,224,200,.55);
  padding-top: 12px;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: rgba(234,224,200,.2);
  flex-shrink: 0;
}
.status-dot.on {
  background: var(--jade-light);
  box-shadow: 0 0 8px var(--jade), 0 0 3px var(--jade-light);
}
.status-txt { flex: 1; }
.status-ver {
  font-style: normal;
  font-size: 10px;
  font-family: var(--mono);
  color: rgba(234,224,200,.35);
  background: rgba(255,255,255,.05);
  padding: 2px 6px;
  border-radius: 2px;
  border: 1px solid rgba(234,224,200,.1);
}

/* ── 主内容区 ── */
.stage {
  padding: 36px 44px;
  background: var(--xuan);
  min-height: 100vh;
  background-image:
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 27px,
      rgba(26,23,20,.022) 27px,
      rgba(26,23,20,.022) 28px
    );
}

/* ── 页面切换动效 ── */
.page-enter-active,
.page-leave-active {
  transition: opacity .2s ease, transform .2s ease;
}
.page-enter-from {
  opacity: 0;
  transform: translateX(12px);
}
.page-leave-to {
  opacity: 0;
  transform: translateX(-8px);
}

/* ── 响应式 ── */
@media (max-width: 860px) {
  .shell { grid-template-columns: 1fr; }
  .rail { position: relative; height: auto; }
  .stage { padding: 24px 20px; }
}
</style>

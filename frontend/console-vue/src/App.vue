<script setup lang="ts">
import { RouterView, RouterLink } from 'vue-router'
import { useHealth } from '@/composables/useHealth'

const { online, version } = useHealth()

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
      <div class="brand">
        <div class="brand-seal">枢<br/>忆</div>
        <div class="brand-txt">
          <div class="bt-cn">宛委·枢忆</div>
          <div class="bt-en">OSAgent Console</div>
        </div>
      </div>
      <nav class="nav">
        <section v-for="group in navGroups" :key="group.title" class="nav-group">
          <div class="nav-title">{{ group.title }}</div>
          <RouterLink v-for="n in group.items" :key="n.to" :to="n.to" class="nav-item">
            <span class="ni-seal">{{ n.seal }}</span>
            <span class="ni-txt"><b>{{ n.name }}</b><i>{{ n.en }}</i></span>
          </RouterLink>
        </section>
      </nav>
      <div class="rail-foot">
        <span class="dot" :class="{ on: online }"></span>
        <span>{{ online ? '后端在线' : '后端离线' }}</span>
        <em v-if="online">{{ version }}</em>
      </div>
    </aside>
    <main class="stage">
      <RouterView v-slot="{ Component }">
        <Transition name="fade" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>
  </div>
</template>

<style scoped>
.shell { display: grid; grid-template-columns: 264px 1fr; min-height: 100vh; }
.rail {
  background: linear-gradient(180deg, #211E1A, #17150F);
  color: #E9DFC8; padding: 18px 14px; display: flex; flex-direction: column;
  border-right: 3px solid var(--cinnabar); position: sticky; top: 0; height: 100vh;
  overflow: hidden;
}
.brand { display: flex; gap: 12px; align-items: center; padding-bottom: 20px; border-bottom: 1px solid rgba(233,223,200,.15); }
.brand-seal {
  font-family: var(--font-kai); font-weight: 700; font-size: 20px; line-height: 1.05;
  color: #F3E9CE; background: var(--cinnabar); padding: 8px 11px; border-radius: 4px;
  text-align: center; box-shadow: 0 0 18px rgba(178,58,46,.5);
}
.bt-cn { font-family: var(--font-kai); font-size: 18px; letter-spacing: 2px; }
.bt-en { font-size: 11px; opacity: .6; letter-spacing: 1px; }
.nav { margin-top: 16px; display: flex; flex-direction: column; gap: 14px; flex: 1; overflow: auto; padding-right: 4px; }
.nav-group { display: flex; flex-direction: column; gap: 3px; }
.nav-title { font-size: 10px; letter-spacing: 2px; color: rgba(233,223,200,.42); padding: 3px 4px 5px; }
.nav-item {
  display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 6px;
  color: #C9BC9E; text-decoration: none; transition: all .18s; border: 1px solid transparent;
}
.nav-item:hover { background: rgba(233,223,200,.06); color: #F3E9CE; }
.nav-item.router-link-exact-active {
  background: rgba(178,58,46,.16); color: #F3E9CE; border-color: rgba(178,58,46,.5);
}
.ni-seal {
  font-family: var(--font-kai); font-size: 15px; width: 30px; height: 30px;
  display: grid; place-items: center; border: 1px solid currentColor; border-radius: 4px; opacity: .8;
}
.ni-txt { display: flex; flex-direction: column; line-height: 1.25; }
.ni-txt b { font-size: 14px; font-weight: 600; }
.ni-txt i { font-size: 10.5px; opacity: .55; font-style: normal; }
.rail-foot { display: flex; align-items: center; gap: 8px; font-size: 12px; opacity: .8; padding-top: 14px; border-top: 1px solid rgba(233,223,200,.15); }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--ink-soft); }
.dot.on { background: var(--jade); box-shadow: 0 0 8px var(--jade); }
.rail-foot em { margin-left: auto; font-style: normal; font-size: 10.5px; opacity: .6; }
.stage { padding: 34px 40px; background: var(--paper); min-height: 100vh; }
.fade-enter-active, .fade-leave-active { transition: opacity .22s, transform .22s; }
.fade-enter-from { opacity: 0; transform: translateY(8px); }
.fade-leave-to { opacity: 0; transform: translateY(-8px); }
@media (max-width: 820px) { .shell { grid-template-columns: 1fr; } .rail { position: relative; height: auto; } }
</style>

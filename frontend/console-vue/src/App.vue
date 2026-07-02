<script setup lang="ts">
import { RouterView, RouterLink } from 'vue-router'
import { useHealth } from '@/composables/useHealth'

const { online, version } = useHealth()

const nav = [
  { to: '/', seal: '枢', name: '总览', en: 'Overview' },
  { to: '/pillars', seal: '架', name: '九枢架构', en: 'Nine Pillars' },
  { to: '/capsules', seal: '忆', name: '记忆容器', en: 'Capsules' },
  { to: '/search', seal: '琅', name: '可信检索', en: 'Search' },
  { to: '/command', seal: '司', name: '指挥闭环', en: 'Command' },
  { to: '/reflection', seal: '省', name: '复盘演化', en: 'Reflection' },
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
        <RouterLink v-for="n in nav" :key="n.to" :to="n.to" class="nav-item">
          <span class="ni-seal">{{ n.seal }}</span>
          <span class="ni-txt"><b>{{ n.name }}</b><i>{{ n.en }}</i></span>
        </RouterLink>
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
.shell { display: grid; grid-template-columns: 248px 1fr; min-height: 100vh; }
.rail {
  background: linear-gradient(180deg, #211E1A, #17150F);
  color: #E9DFC8; padding: 22px 16px; display: flex; flex-direction: column;
  border-right: 3px solid var(--cinnabar); position: sticky; top: 0; height: 100vh;
}
.brand { display: flex; gap: 12px; align-items: center; padding-bottom: 20px; border-bottom: 1px solid rgba(233,223,200,.15); }
.brand-seal {
  font-family: var(--font-kai); font-weight: 700; font-size: 20px; line-height: 1.05;
  color: #F3E9CE; background: var(--cinnabar); padding: 8px 11px; border-radius: 4px;
  text-align: center; box-shadow: 0 0 18px rgba(178,58,46,.5);
}
.bt-cn { font-family: var(--font-kai); font-size: 18px; letter-spacing: 2px; }
.bt-en { font-size: 11px; opacity: .6; letter-spacing: 1px; }
.nav { margin-top: 18px; display: flex; flex-direction: column; gap: 3px; flex: 1; }
.nav-item {
  display: flex; align-items: center; gap: 11px; padding: 10px 12px; border-radius: 6px;
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

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import CapsuleDetail from '@/components/CapsuleDetail.vue'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'

const route = useRoute()

const items = ref<any[]>([])
const selected = ref<any | null>(null)
const loading = ref(true)
const err = ref('')

const LIFECYCLE_COLOR: Record<string,string> = {
  active: 'var(--dai)', reinforced: 'var(--bamboo)', candidate: 'var(--gold)',
  quarantined: 'var(--cinnabar)', rejected: 'var(--cinnabar)', deprecated: 'var(--ink-soft)',
  forgotten: 'var(--ink-soft)', conflicted: 'var(--gold)',
}

async function load() {
  loading.value = true; err.value = ''
  try {
    const r = await api.listCapsules(50)
    items.value = r.items || []
    const id = typeof route.query.id === 'string' ? route.query.id : ''
    if (id) await open(id)
  } catch (e: any) { err.value = String(e) }
  loading.value = false
}
async function open(id: string) {
  try { selected.value = await api.getCapsule(id) } catch (e: any) { err.value = String(e) }
}
onMounted(load)
</script>

<template>
  <div>
    <div class="hero-wrap">
      <PageHero
        seal="忆"
        title="枢忆核"
        en="Memory Capsules"
        sub="MemoryCapsule 2.0 浏览器 — 点击查看治理 / 状态 / 溯源"
      />
      <GfButton class="hero-act" variant="ghost" small @click="load">刷新</GfButton>
    </div>

    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="loading" class="loading">研墨中…</div>
    <GfEmpty v-else-if="!items.length" text="匣中尚无记忆容器 — 可去「司契指挥」或「写入」创建一枚" />

    <div class="cap-layout" v-else>
      <GfCard :pad="false" class="cap-list-card">
        <ul class="cap-list">
          <li v-for="c in items" :key="c.capsule_id" @click="open(c.capsule_id)"
              :class="{ sel: selected?.capsule_id === c.capsule_id }">
            <span class="cap-class">{{ c.memory_class }}</span>
            <span class="cap-dot" :style="{ background: LIFECYCLE_COLOR[c.state?.lifecycle] || 'var(--ink-soft)' }"></span>
            <span class="cap-life">{{ c.state?.lifecycle }}</span>
            <span class="cap-id">{{ c.capsule_id }}</span>
          </li>
        </ul>
      </GfCard>
      <CapsuleDetail :capsule="selected" />
    </div>
  </div>
</template>

<style scoped>
.hero-wrap { position: relative; }
.hero-act { position: absolute; top: 6px; right: 0; }
.err {
  color: var(--cinnabar);
  font-size: 13px;
  margin-bottom: 12px;
  padding: 10px 14px;
  border: 1px solid color-mix(in srgb, var(--cinnabar) 32%, transparent);
  background: color-mix(in srgb, var(--cinnabar) 7%, transparent);
  border-radius: var(--radius-small);
}
.loading {
  font-family: var(--font-kai);
  font-size: 14px;
  letter-spacing: 4px;
  color: var(--ink-muted);
  padding: 40px 0;
  text-align: center;
}
.cap-layout { display: grid; grid-template-columns: 340px 1fr; gap: 20px; align-items: start; }
.cap-list-card:hover { transform: none; }
.cap-list { max-height: 62vh; overflow-y: auto; list-style: none; }
.cap-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 14px;
  border-bottom: 1px solid var(--line-soft);
  cursor: pointer;
  font-size: 12px;
  transition: background .18s ease, box-shadow .18s ease;
}
.cap-list li:last-child { border-bottom: none; }
.cap-list li:hover { background: color-mix(in srgb, var(--rouge) 8%, transparent); }
.cap-list li.sel {
  background: color-mix(in srgb, var(--rouge) 13%, transparent);
  box-shadow: inset 3px 0 0 var(--cinnabar);
}
.cap-class { font-weight: 700; color: var(--dai); min-width: 74px; letter-spacing: 1px; }
.cap-dot { width: 8px; height: 8px; border-radius: 50%; box-shadow: 0 0 6px var(--rouge-glow); flex-shrink: 0; }
.cap-life { color: var(--ink-soft); min-width: 72px; }
.cap-id { font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); margin-left: auto; }
@media (max-width: 900px) { .cap-layout { grid-template-columns: 1fr; } }
</style>

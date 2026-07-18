<script setup lang="ts">
/**
 * SoulView — 灵魂状态「灵鉴」
 * 圆月盘面可视化 persona + PAD affect；支持结契(connect)、命格编辑(persona update)、心绪触发(affect transition)。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import GfEmpty from '@/components/gf/GfEmpty.vue'
import InkDivider from '@/components/gf/InkDivider.vue'
import { api } from '@/api/client'

const SOUL_KEY = 'gf-soul-id'

interface AffectState {
  pleasure: number
  arousal: number
  dominance: number
  current_mood: string
  mood_intensity: number
}

const soulId = ref<string>(localStorage.getItem(SOUL_KEY) || '')
const inputId = ref('')
const state = ref<any>(null)
const affect = ref<AffectState | null>(null)
const loading = ref(false)
const connecting = ref(false)
const errorMsg = ref('')

/* ── 命格编辑表单 ── */
const editing = ref(false)
const saving = ref(false)
const savedOk = ref(false)
const form = reactive({
  name: '',
  voice: '',
  coreTraits: '',
  soulValues: '',
  selfNarrative: '',
})

/* ── 心绪触发 ── */
const triggering = ref('')
const triggers = [
  { key: 'user_thank', label: '谢' },
  { key: 'user_complaint', label: '怨' },
  { key: 'praise', label: '赞' },
  { key: 'manual', label: '静' },
]

const MOOD_LABEL: Record<string, string> = {
  calm: '宁静',
  happy: '欣喜',
  sad: '低回',
  angry: '微愠',
  excited: '雀跃',
  anxious: '萦虑',
  grateful: '感念',
  tired: '倦怠',
}

const persona = computed(() => state.value?.persona ?? null)
const coreMemories = computed<any[]>(() => state.value?.core_memories ?? [])
const moodLabel = computed(() => {
  const m = affect.value?.current_mood || 'calm'
  return MOOD_LABEL[m] || m
})

/* ── 月盘三环（PAD） ── */
function arc(r: number, value: number): string {
  const c = 2 * Math.PI * r
  const v = Math.max(0, Math.min(1, value))
  return `${(v * c).toFixed(2)} ${(c - v * c).toFixed(2)}`
}
const pad = computed(() => ({
  pleasure: affect.value?.pleasure ?? 0.5,
  arousal: affect.value?.arousal ?? 0.4,
  dominance: affect.value?.dominance ?? 0.5,
}))
const moodIntensityPct = computed(() => Math.round((affect.value?.mood_intensity ?? 0) * 100))

function splitList(text: string): string[] {
  return text.split(/[,，、\n]/).map((s) => s.trim()).filter(Boolean)
}

function fillForm(): void {
  const p = persona.value
  if (!p) return
  form.name = p.name || ''
  form.voice = p.voice || ''
  form.coreTraits = (p.core_traits || []).join('、')
  form.soulValues = (p.soul_values || []).join('、')
  form.selfNarrative = p.self_narrative || ''
}

async function refresh(): Promise<void> {
  if (!soulId.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    const [s, a] = await Promise.all([
      api.soulState(soulId.value),
      api.soulAffect(soulId.value),
    ])
    state.value = s
    affect.value = a
    if (!editing.value) fillForm()
  } catch (e: any) {
    errorMsg.value = `灵鉴蒙尘：${e?.message || e}`
  } finally {
    loading.value = false
  }
}

async function connect(useInput: boolean): Promise<void> {
  connecting.value = true
  errorMsg.value = ''
  try {
    const id = useInput ? inputId.value.trim() : ''
    const res = await api.soulConnect(id || undefined)
    soulId.value = res.soul_id
    localStorage.setItem(SOUL_KEY, res.soul_id)
    state.value = { persona: res.persona, core_memories: [] }
    await refresh()
  } catch (e: any) {
    errorMsg.value = `结契未成：${e?.message || e}`
  } finally {
    connecting.value = false
  }
}

function disconnect(): void {
  localStorage.removeItem(SOUL_KEY)
  soulId.value = ''
  inputId.value = ''
  state.value = null
  affect.value = null
  editing.value = false
  errorMsg.value = ''
}

async function savePersona(): Promise<void> {
  if (!soulId.value) return
  saving.value = true
  savedOk.value = false
  errorMsg.value = ''
  try {
    await api.soulPersonaUpdate(soulId.value, {
      name: form.name,
      voice: form.voice,
      core_traits: splitList(form.coreTraits),
      soul_values: splitList(form.soulValues),
      self_narrative: form.selfNarrative,
    })
    savedOk.value = true
    editing.value = false
    await refresh()
  } catch (e: any) {
    errorMsg.value = `命格未镌：${e?.message || e}`
  } finally {
    saving.value = false
  }
}

async function triggerAffect(key: string): Promise<void> {
  if (!soulId.value || triggering.value) return
  triggering.value = key
  errorMsg.value = ''
  try {
    const res = await api.soulAffectPut(soulId.value, key, 1.0)
    if (res?.affect) affect.value = { ...affect.value, ...res.affect } as AffectState
  } catch (e: any) {
    errorMsg.value = `心绪未动：${e?.message || e}`
  } finally {
    triggering.value = ''
  }
}

onMounted(() => {
  if (soulId.value) refresh()
})
</script>

<template>
  <div class="soul-view">
    <PageHero
      seal="灵"
      title="灵魂状态"
      en="Soul Mirror"
      sub="灵鉴圆月 · 照见心魂。命格、心绪与灵犀记忆，皆映于此盘。"
    />

    <p v-if="errorMsg" class="soul-error">{{ errorMsg }}</p>

    <!-- 未结契：鉴灵入口 -->
    <GfCard v-if="!soulId" title="鉴灵结契" seal="契" class="connect-card">
      <p class="connect-hint">
        尚未照见任何灵魂。可结契一缕新魂，或凭既有 <code>soul_id</code> 重续前缘。
      </p>
      <div class="connect-row">
        <input
          v-model="inputId"
          class="gf-input"
          placeholder="soul_id（留空则结契新魂）"
          @keyup.enter="connect(true)"
        />
        <GfButton :disabled="connecting" @click="connect(!!inputId.trim())">
          {{ connecting ? '研墨中…' : '结契鉴灵' }}
        </GfButton>
      </div>
    </GfCard>

    <template v-else>
      <div class="soul-grid">
        <!-- 灵鉴月盘 -->
        <GfCard title="灵鉴月盘" seal="鉴" class="moon-card">
          <div class="moon-stage">
            <svg viewBox="0 0 240 240" class="moon-svg" role="img" aria-label="灵鉴月盘">
              <defs>
                <radialGradient id="moonGlow" cx="50%" cy="42%" r="60%">
                  <stop offset="0%" style="stop-color: var(--rouge-glow); stop-opacity: .55" />
                  <stop offset="100%" style="stop-color: var(--rouge-glow); stop-opacity: 0" />
                </radialGradient>
              </defs>
              <!-- 月晕 -->
              <circle cx="120" cy="120" r="112" fill="url(#moonGlow)" />
              <!-- 月洞门环 -->
              <circle cx="120" cy="120" r="104" fill="none" stroke="var(--gold-line)" stroke-width="1.2" />
              <!-- 三环轨道 -->
              <circle cx="120" cy="120" r="90" fill="none" stroke="var(--line-soft)" stroke-width="10" />
              <circle cx="120" cy="120" r="72" fill="none" stroke="var(--line-soft)" stroke-width="10" />
              <circle cx="120" cy="120" r="54" fill="none" stroke="var(--line-soft)" stroke-width="10" />
              <!-- 愉悦（胭脂） -->
              <circle
                cx="120" cy="120" r="90" fill="none"
                stroke="var(--rouge)" stroke-width="10" stroke-linecap="round"
                :stroke-dasharray="arc(90, pad.pleasure)"
                transform="rotate(-90 120 120)" class="pad-arc"
              />
              <!-- 唤起（藤黄） -->
              <circle
                cx="120" cy="120" r="72" fill="none"
                stroke="var(--gold)" stroke-width="10" stroke-linecap="round"
                :stroke-dasharray="arc(72, pad.arousal)"
                transform="rotate(-90 120 120)" class="pad-arc"
              />
              <!-- 主宰（黛蓝） -->
              <circle
                cx="120" cy="120" r="54" fill="none"
                stroke="var(--dai)" stroke-width="10" stroke-linecap="round"
                :stroke-dasharray="arc(54, pad.dominance)"
                transform="rotate(-90 120 120)" class="pad-arc"
              />
              <!-- 梅影点缀 -->
              <g fill="var(--rouge)" opacity=".8">
                <circle cx="196" cy="58" r="3" /><circle cx="201.5" cy="62.4" r="3" />
                <circle cx="199.8" cy="68.4" r="3" /><circle cx="192.2" cy="68.4" r="3" />
                <circle cx="190.5" cy="62.4" r="3" />
              </g>
              <circle cx="196" cy="63.4" r="1.7" fill="var(--gold)" />
            </svg>
            <div class="moon-center">
              <div class="moon-mood">{{ moodLabel }}</div>
              <div class="moon-mood-en">{{ affect?.current_mood || 'calm' }}</div>
              <div class="moon-intensity">
                <span class="mi-track"><span class="mi-fill" :style="{ width: moodIntensityPct + '%' }"></span></span>
                <span class="mi-num">{{ moodIntensityPct }}%</span>
              </div>
            </div>
          </div>

          <div class="pad-legend">
            <div class="pl-row">
              <span class="pl-dot" data-tone="rouge"></span>
              <span class="pl-name">愉悦</span>
              <span class="pl-bar"><span class="pl-fill" data-tone="rouge" :style="{ width: pad.pleasure * 100 + '%' }"></span></span>
              <span class="pl-num">{{ pad.pleasure.toFixed(2) }}</span>
            </div>
            <div class="pl-row">
              <span class="pl-dot" data-tone="gold"></span>
              <span class="pl-name">唤起</span>
              <span class="pl-bar"><span class="pl-fill" data-tone="gold" :style="{ width: pad.arousal * 100 + '%' }"></span></span>
              <span class="pl-num">{{ pad.arousal.toFixed(2) }}</span>
            </div>
            <div class="pl-row">
              <span class="pl-dot" data-tone="dai"></span>
              <span class="pl-name">主宰</span>
              <span class="pl-bar"><span class="pl-fill" data-tone="dai" :style="{ width: pad.dominance * 100 + '%' }"></span></span>
              <span class="pl-num">{{ pad.dominance.toFixed(2) }}</span>
            </div>
          </div>

          <InkDivider label="心绪一触" />
          <div class="trigger-row">
            <button
              v-for="t in triggers"
              :key="t.key"
              class="trigger-seal"
              :class="{ 'trigger-seal--busy': triggering === t.key }"
              :disabled="!!triggering"
              :title="t.key"
              @click="triggerAffect(t.key)"
            >{{ t.label }}</button>
          </div>

          <div class="moon-actions">
            <GfButton variant="ghost" small :disabled="loading" @click="refresh">
              {{ loading ? '研墨中…' : '重拭灵鉴' }}
            </GfButton>
            <GfButton variant="danger" small @click="disconnect">别过此魂</GfButton>
          </div>
        </GfCard>

        <!-- 右栏 -->
        <div class="soul-side">
          <GfCard title="命格" seal="命">
            <template v-if="persona">
              <div v-if="!editing" class="persona-show">
                <div class="persona-head">
                  <span class="persona-avatar">{{ (persona.name || '灵').slice(0, 1) }}</span>
                  <div>
                    <div class="persona-name">{{ persona.name || '未名' }}</div>
                    <div class="persona-voice">{{ persona.voice || '声线未调' }}</div>
                  </div>
                  <GfButton variant="ghost" small class="persona-edit" @click="editing = true">镌改</GfButton>
                </div>
                <div class="persona-block">
                  <div class="pb-label">性情</div>
                  <div class="pb-tags">
                    <GfTag v-for="t in persona.core_traits || []" :key="t" tone="rouge">{{ t }}</GfTag>
                    <span v-if="!(persona.core_traits || []).length" class="pb-none">未镌</span>
                  </div>
                </div>
                <div class="persona-block">
                  <div class="pb-label">所守</div>
                  <div class="pb-tags">
                    <GfTag v-for="v in persona.soul_values || []" :key="v" tone="bamboo">{{ v }}</GfTag>
                    <span v-if="!(persona.soul_values || []).length" class="pb-none">未镌</span>
                  </div>
                </div>
                <div class="persona-block">
                  <div class="pb-label">自述</div>
                  <p class="pb-narrative">{{ persona.self_narrative || '——' }}</p>
                </div>
                <p v-if="savedOk" class="saved-ok">命格已镌，灵鉴重明。</p>
              </div>

              <div v-else class="persona-form">
                <label class="pf-field">
                  <span>名讳</span>
                  <input v-model="form.name" class="gf-input" placeholder="灵魂之名" />
                </label>
                <label class="pf-field">
                  <span>声线</span>
                  <input v-model="form.voice" class="gf-input" placeholder="说话的气质" />
                </label>
                <label class="pf-field">
                  <span>性情（、分隔）</span>
                  <input v-model="form.coreTraits" class="gf-input" placeholder="严谨、有温度" />
                </label>
                <label class="pf-field">
                  <span>所守（、分隔）</span>
                  <input v-model="form.soulValues" class="gf-input" placeholder="诚实、成长" />
                </label>
                <label class="pf-field">
                  <span>自述</span>
                  <textarea v-model="form.selfNarrative" class="gf-input gf-textarea" rows="3"></textarea>
                </label>
                <div class="pf-actions">
                  <GfButton :disabled="saving" @click="savePersona">{{ saving ? '镌刻中…' : '镌刻命格' }}</GfButton>
                  <GfButton variant="ghost" :disabled="saving" @click="editing = false; fillForm()">作罢</GfButton>
                </div>
              </div>
            </template>
            <GfEmpty v-else text="命格未镌 · 此魂尚在混沌" />
          </GfCard>

          <GfCard title="灵犀记忆" seal="忆">
            <template v-if="coreMemories.length">
              <ul class="memory-list">
                <li v-for="m in coreMemories" :key="m.capsule_id" class="memory-item">
                  <span class="mi-petal" aria-hidden="true">
                    <svg viewBox="0 0 16 16" width="14" height="14">
                      <g fill="var(--rouge)" opacity=".7">
                        <circle cx="8" cy="3.4" r="2.2" /><circle cx="12.4" cy="6.4" r="2.2" />
                        <circle cx="10.8" cy="11.4" r="2.2" /><circle cx="5.2" cy="11.4" r="2.2" />
                        <circle cx="3.6" cy="6.4" r="2.2" />
                      </g>
                    </svg>
                  </span>
                  <span class="mi-text">{{ m.text }}</span>
                  <span class="mi-score" :title="`importance ${m.importance_score}`">
                    <span class="mi-score-fill" :style="{ width: (m.importance_score || 0) * 100 + '%' }"></span>
                  </span>
                </li>
              </ul>
            </template>
            <GfEmpty v-else text="灵犀未通 · 尚无深刻记忆" />
          </GfCard>
        </div>
      </div>

      <p class="soul-foot">当前照见：<code>{{ soulId }}</code></p>
    </template>
  </div>
</template>

<style scoped>
.soul-view { padding-bottom: 24px; }

.soul-error {
  margin-bottom: 14px;
  padding: 10px 16px;
  border-radius: var(--radius-small);
  border: 1px solid color-mix(in srgb, var(--cinnabar) 40%, transparent);
  background: color-mix(in srgb, var(--cinnabar) 8%, transparent);
  color: var(--cinnabar);
  font-size: 13px;
  letter-spacing: 1px;
}

/* ── 结契入口 ── */
.connect-card { max-width: 640px; }
.connect-hint {
  font-size: 13px;
  color: var(--ink-soft);
  line-height: 1.9;
  margin-bottom: 14px;
}
.connect-hint code { font-family: var(--font-mono); font-size: 12px; color: var(--dai); }
.connect-row { display: flex; gap: 12px; flex-wrap: wrap; }

.gf-input {
  flex: 1;
  min-width: 200px;
  padding: 9px 14px;
  border-radius: var(--radius-small);
  border: 1px solid var(--line);
  background: var(--card);
  font-size: 13px;
  color: var(--ink);
  transition: border-color .18s ease, box-shadow .18s ease;
}
.gf-input:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.gf-textarea { resize: vertical; line-height: 1.8; font-family: var(--font-sans); }

/* ── 布局 ── */
.soul-grid {
  display: grid;
  grid-template-columns: minmax(320px, 420px) 1fr;
  gap: 20px;
  align-items: start;
}
.soul-side { display: grid; gap: 20px; }

/* ── 月盘 ── */
.moon-stage {
  position: relative;
  display: grid;
  place-items: center;
}
.moon-svg { width: 100%; max-width: 300px; height: auto; display: block; }
.pad-arc { transition: stroke-dasharray .6s ease; filter: drop-shadow(0 0 6px var(--rouge-glow)); }
.moon-center {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 4px;
  pointer-events: none;
}
.moon-mood {
  font-family: var(--font-kai);
  font-size: 30px;
  font-weight: 700;
  letter-spacing: 6px;
  color: var(--ink);
  text-shadow: 0 0 14px var(--rouge-glow);
}
.moon-mood-en {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: var(--ink-muted);
}
.moon-intensity {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.mi-track {
  width: 72px;
  height: 5px;
  border-radius: 999px;
  background: var(--line-soft);
  overflow: hidden;
  display: block;
}
.mi-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--rouge), var(--cinnabar));
  transition: width .5s ease;
}
.mi-num { font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); }

/* ── PAD 图例 ── */
.pad-legend { margin-top: 16px; display: grid; gap: 8px; }
.pl-row { display: flex; align-items: center; gap: 10px; }
.pl-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.pl-dot[data-tone='rouge'] { background: var(--rouge); box-shadow: 0 0 6px var(--rouge-glow); }
.pl-dot[data-tone='gold'] { background: var(--gold); }
.pl-dot[data-tone='dai'] { background: var(--dai); }
.pl-name { font-family: var(--font-kai); font-size: 13px; letter-spacing: 2px; color: var(--ink-soft); width: 34px; }
.pl-bar {
  flex: 1;
  height: 6px;
  border-radius: 999px;
  background: var(--line-soft);
  overflow: hidden;
}
.pl-fill { display: block; height: 100%; border-radius: 999px; transition: width .5s ease; }
.pl-fill[data-tone='rouge'] { background: linear-gradient(90deg, var(--rouge-soft), var(--rouge)); }
.pl-fill[data-tone='gold'] { background: linear-gradient(90deg, var(--gold-line), var(--gold)); }
.pl-fill[data-tone='dai'] { background: linear-gradient(90deg, var(--dai-deep), var(--dai)); }
.pl-num { font-family: var(--font-mono); font-size: 11px; color: var(--ink-muted); width: 34px; text-align: right; }

/* ── 心绪印章触发 ── */
.trigger-row { display: flex; gap: 12px; justify-content: center; }
.trigger-seal {
  width: 42px;
  height: 42px;
  border-radius: var(--radius-seal);
  border: 1px solid color-mix(in srgb, var(--cinnabar) 45%, transparent);
  background: var(--card);
  color: var(--cinnabar);
  font-family: var(--font-kai);
  font-size: 17px;
  font-weight: 700;
  transition: transform .18s ease, box-shadow .18s ease, background .18s ease;
}
.trigger-seal:hover:not(:disabled) {
  transform: translateY(-2px) rotate(-3deg);
  background: color-mix(in srgb, var(--cinnabar) 10%, transparent);
  box-shadow: 0 0 14px var(--cinnabar-glow);
}
.trigger-seal:disabled { opacity: .5; cursor: wait; }
.trigger-seal--busy { animation: sealPulse 1s ease infinite; }
@keyframes sealPulse {
  50% { box-shadow: 0 0 18px var(--cinnabar-glow); transform: scale(1.06); }
}

.moon-actions { display: flex; justify-content: center; gap: 12px; margin-top: 16px; }

/* ── 命格 ── */
.persona-head { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }
.persona-avatar {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-family: var(--font-kai);
  font-size: 24px;
  font-weight: 700;
  color: var(--cinnabar);
  background: var(--card-solid);
  border: 1.5px solid var(--gold-line);
  box-shadow: 0 0 16px var(--rouge-glow);
  flex-shrink: 0;
}
.persona-name { font-family: var(--font-kai); font-size: 22px; font-weight: 700; letter-spacing: 3px; color: var(--ink); }
.persona-voice { font-size: 12px; color: var(--ink-muted); letter-spacing: 1px; margin-top: 2px; }
.persona-edit { margin-left: auto; }

.persona-block { margin-bottom: 12px; }
.pb-label {
  font-size: 11px;
  letter-spacing: 2px;
  color: var(--ink-muted);
  margin-bottom: 6px;
}
.pb-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.pb-none { font-size: 12px; color: var(--ink-muted); }
.pb-narrative {
  font-size: 13px;
  line-height: 1.9;
  color: var(--ink-soft);
  padding: 10px 14px;
  border-left: 2px solid var(--gold-line);
  background: var(--line-soft);
  border-radius: 0 var(--radius-small) var(--radius-small) 0;
}
.saved-ok { font-size: 12px; color: var(--bamboo); letter-spacing: 2px; margin-top: 4px; }

.persona-form { display: grid; gap: 12px; }
.pf-field { display: grid; gap: 5px; }
.pf-field > span { font-size: 11px; letter-spacing: 2px; color: var(--ink-muted); }
.pf-field .gf-input { width: 100%; min-width: 0; }
.pf-actions { display: flex; gap: 12px; }

/* ── 灵犀记忆 ── */
.memory-list { list-style: none; display: grid; gap: 10px; }
.memory-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: var(--radius-small);
  background: var(--line-soft);
  transition: background .18s ease;
}
.memory-item:hover { background: color-mix(in srgb, var(--rouge) 8%, transparent); }
.mi-petal { flex-shrink: 0; display: grid; place-items: center; }
.mi-text { flex: 1; font-size: 13px; color: var(--ink-soft); line-height: 1.7; }
.mi-score {
  width: 46px;
  height: 5px;
  border-radius: 999px;
  background: var(--line);
  overflow: hidden;
  flex-shrink: 0;
}
.mi-score-fill { display: block; height: 100%; background: var(--gold); border-radius: 999px; }

.soul-foot {
  margin-top: 18px;
  text-align: center;
  font-size: 11px;
  letter-spacing: 2px;
  color: var(--ink-muted);
}
.soul-foot code { font-family: var(--font-mono); color: var(--dai); }

@media (max-width: 900px) {
  .soul-grid { grid-template-columns: 1fr; }
}
</style>

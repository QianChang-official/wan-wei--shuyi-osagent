<script setup lang="ts">
import { ref } from 'vue'
import PageHero from '@/components/gf/PageHero.vue'
import GfCard from '@/components/gf/GfCard.vue'
import GfTag from '@/components/gf/GfTag.vue'
import GfButton from '@/components/gf/GfButton.vue'
import { useHealth } from '@/composables/useHealth'

const { online, version } = useHealth(30000)

/* ── 帮助中心 FAQ ── */
interface Faq { q: string; a: string }
const faqs: Faq[] = [
  {
    q: '如何配置模型？',
    a: '进入「模型接入」舱室，新增或编辑 provider：填写 api_base、模型名与密钥，保存后即可在「通玄模型舱」做 Dry-run 或真实 smoke 验证。密钥仅在本机加密落盘，列表中只展示掩码；后端离线时可在设置页先保存偏好，联机后自动生效。',
  },
  {
    q: '智能体的工作档位有什么区别？',
    a: '工作档位决定智能体被允许触达的执行面：人工审查（每步动作需你确认后执行）、沙盒工作（在隔离沙盒内自由执行，不碰真实系统）、整台设备（可直接操作本机，请仅对可信任务开启）。另有思考深度档位：浅思、常思、深思、极思、穷思、超码，越深推理越充分、耗时与消耗也越高。',
  },
  {
    q: '记忆指令怎么用？',
    a: '「记忆中枢」保存着你的偏好、项目背景与长期指令。在对话中说「记住：……」即可写入；也可在记忆中枢页面直接增删。记忆仅存放在本机数据中，不会上传到任何服务器。',
  },
  {
    q: '如何用手机控制？',
    a: '在本应用「通用设置 → 局域网手机控制」中点击开启，页面会显示一个局域网地址。手机与电脑连入同一网络后，用手机浏览器打开该地址即可访问控制台。关闭后地址立即失效。',
  },
  {
    q: 'git 空间是做什么的？',
    a: '「空间」舱室用于管理工作区：每个空间对应一个本地目录，可绑定 git 仓库，查看分支与变更状态，让智能体在指定空间内读写代码。真实推送（push）等外部动作只有在配置就绪后才会启用，未就绪时会明确标注为模拟。',
  },
  {
    q: '开发模拟器是什么？',
    a: '开发模拟器用于在本机拉起一套隔离的运行环境（面向麒麟 Linux 目标平台），便于验证智能体的设备级操作而不影响真实系统。镜像在「通用设置 → 开发模拟器」中下载，下载服务配置就绪前展示的是离线示例。',
  },
]

/* ── 反馈问题（无后端，存本机 localStorage） ── */
const FEEDBACK_KEY = 'gf-feedback'
const fbTypes = ['功能异常', '体验建议', '性能问题', '数据与安全', '其他']
const fbType = ref(fbTypes[0])
const fbDesc = ref('')
const fbContact = ref('')
const fbDone = ref(false)
const fbError = ref('')
const fbCount = ref(0)
const fbMsg = ref('')

interface FeedbackItem {
  type: string
  desc: string
  contact: string
  at: string
}

function readFeedback(): FeedbackItem[] {
  try {
    const raw = localStorage.getItem(FEEDBACK_KEY)
    const list = raw ? JSON.parse(raw) : []
    if (!Array.isArray(list)) return []
    return list.filter(
      (x): x is FeedbackItem => x !== null && typeof x === 'object' && typeof (x as FeedbackItem).desc === 'string',
    )
  } catch {
    return []
  }
}

const fbList = ref<FeedbackItem[]>(readFeedback())
const fbOpen = ref(false)
fbCount.value = fbList.value.length

function submitFeedback() {
  fbError.value = ''
  fbDone.value = false
  fbMsg.value = ''
  const desc = fbDesc.value.trim()
  if (!desc) { fbError.value = '请填写问题描述。'; return }
  const item = {
    type: fbType.value,
    desc,
    contact: fbContact.value.trim(),
    at: new Date().toISOString(),
  }
  try {
    const arr = readFeedback()
    arr.push(item)
    localStorage.setItem(FEEDBACK_KEY, JSON.stringify(arr))
    fbList.value = arr
    fbCount.value = arr.length
  } catch {
    fbError.value = '本机存储不可用，反馈未能记录，请稍后再试。'
    return
  }
  fbDesc.value = ''
  fbContact.value = ''
  fbDone.value = true
  window.setTimeout(() => { fbDone.value = false }, 5000)
}

/* ── 反馈查看 / 导出（08-#38：后端无反馈端点，仅操作本机 localStorage 副本） ── */
function fmtFbTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso || '—'
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function legacyCopyText(text: string): void {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
}

function exportFeedback() {
  fbMsg.value = ''
  const items = readFeedback()
  if (!items.length) { fbMsg.value = '本机暂无反馈记录可导出。'; return }
  const payload = {
    exported_at: new Date().toISOString(),
    storage: `本机浏览器 localStorage（键名 ${FEEDBACK_KEY}），未外发`,
    count: items.length,
    items,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `wanwei-feedback-${new Date().toISOString().slice(0, 10)}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  fbMsg.value = `已导出 ${items.length} 条反馈，JSON 文件保存在浏览器下载目录。`
}

async function copyFeedback() {
  fbMsg.value = ''
  const items = readFeedback()
  if (!items.length) { fbMsg.value = '本机暂无反馈记录可复制。'; return }
  const text = JSON.stringify(items, null, 2)
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text)
    else legacyCopyText(text)
    fbMsg.value = `已复制 ${items.length} 条反馈 JSON 到剪贴板。`
  } catch {
    fbMsg.value = '复制失败，请改用「导出 JSON」。'
  }
}

function clearFeedback() {
  fbMsg.value = ''
  try { localStorage.removeItem(FEEDBACK_KEY) } catch { /* 忽略存储异常 */ }
  fbList.value = []
  fbCount.value = 0
  fbOpen.value = false
  fbMsg.value = '本机反馈记录已清空。'
}

/* ── 关于 ── */
const techStack = ['FastAPI 后端', 'Vue 3 + TypeScript + Vite', 'Electron 桌面端', 'SQLite / JSON 本机落盘', '目标平台：麒麟 Linux']
</script>

<template>
  <div>
    <PageHero
      seal="助"
      title="帮助与关于"
      en="HELP & ABOUT"
      sub="常见问题、反馈通道、版本理念与协议文本。本页内容为纯前端说明，反馈仅记录在本机。"
    />

    <div class="grid">
      <!-- ══ 帮助中心 ══ -->
      <GfCard title="帮助中心" seal="助" class="span-2">
        <div class="faq-list">
          <details v-for="(item, i) in faqs" :key="i" class="faq">
            <summary>
              <span class="faq-q">{{ item.q }}</span>
              <svg class="faq-arrow" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </summary>
            <p class="faq-a">{{ item.a }}</p>
          </details>
        </div>
      </GfCard>

      <!-- ══ 反馈问题 ══ -->
      <GfCard title="反馈问题" seal="馈">
        <p class="hint">反馈通道尚未接入后端，提交内容仅记录在本机浏览器中（localStorage），不会外发。</p>
        <form class="fb-form" @submit.prevent="submitFeedback">
          <label>
            类型
            <select v-model="fbType">
              <option v-for="t in fbTypes" :key="t" :value="t">{{ t }}</option>
            </select>
          </label>
          <label>
            问题描述
            <textarea v-model="fbDesc" rows="4" placeholder="请描述你遇到的问题或建议…" required></textarea>
          </label>
          <label>
            联系方式（选填）
            <input v-model.trim="fbContact" type="text" placeholder="邮箱或其他联系方式，仅本机保存" autocomplete="off" />
          </label>
          <div class="fb-actions">
            <button class="form-submit" type="submit">提交反馈</button>
            <span v-if="fbCount > 0" class="hint">本机已记录 {{ fbCount }} 条反馈</span>
          </div>
          <p v-if="fbError" class="fb-msg error" role="alert">{{ fbError }}</p>
          <p v-else-if="fbDone" class="fb-msg ok" role="status">已记录在本机，感谢你的反馈。</p>
        </form>

        <!-- 本机反馈查看 / 导出（后端无反馈端点，仅操作 localStorage 副本） -->
        <div class="fb-tools">
          <GfButton variant="ghost" small :disabled="!fbCount" @click="fbOpen = !fbOpen">
            {{ fbOpen ? '收起本机反馈' : '查看本机反馈' }}
          </GfButton>
          <GfButton variant="ghost" small :disabled="!fbCount" @click="exportFeedback">导出 JSON</GfButton>
          <GfButton variant="ghost" small :disabled="!fbCount" @click="copyFeedback">复制 JSON</GfButton>
          <GfButton variant="ghost" small :disabled="!fbCount" @click="clearFeedback">清空</GfButton>
        </div>
        <p v-if="fbMsg" class="fb-msg ok" role="status">{{ fbMsg }}</p>
        <div v-if="fbOpen && fbList.length" class="fb-list">
          <div v-for="(item, i) in fbList" :key="i" class="fb-item">
            <div class="fb-item-meta">
              <GfTag tone="dai">{{ item.type || '其他' }}</GfTag>
              <span class="fb-item-time">{{ fmtFbTime(item.at) }}</span>
            </div>
            <p class="fb-item-desc">{{ item.desc }}</p>
            <p v-if="item.contact" class="fb-item-contact">联系方式：{{ item.contact }}</p>
          </div>
        </div>
        <p v-else-if="fbOpen" class="hint">本机暂无反馈记录。</p>
        <p class="hint fb-store-hint">
          反馈存储位置：本机浏览器 localStorage（键名 {{ FEEDBACK_KEY }}），不会外发；导出的 JSON 保存在浏览器下载目录。
        </p>
      </GfCard>

      <!-- ══ 关于我们 ══ -->
      <GfCard title="关于我们" seal="委">
        <div class="about-ver">
          <span class="ver-name">宛委·万枢</span>
          <GfTag tone="rouge">建设版 2.0</GfTag>
          <GfTag :tone="online ? 'bamboo' : 'ink'">{{ online ? `后端在线 · ${version || '版本未知'}` : '后端离线' }}</GfTag>
        </div>
        <p class="about-p">
          「宛委」之名，典出会稽宛委山藏书之传说——大禹得金简玉字之地，后人以「宛委别藏」喻珍籍秘存之所。
          「万枢」者，万务之枢机也。宛委·万枢愿做你桌面上那座安静的书房：模型、智能体、记忆与工具各安其位，
          数据不出此机，密钥不离此匣。
        </p>
        <p class="about-p">
          我们相信 AI 协作平台首先应当是一件值得日日相对的器物——本地优先、诚实标注能力边界、
          未就绪的能力绝不伪装成可用；其次才是聪明。国风不是皮肤，而是对「慢、稳、可藏」的致敬。
        </p>
        <div class="block-label">技术栈</div>
        <div class="stack">
          <GfTag v-for="t in techStack" :key="t" tone="dai">{{ t }}</GfTag>
        </div>
      </GfCard>

      <!-- ══ 用户协议与隐私协议 ══ -->
      <GfCard title="用户协议与隐私协议" seal="约" class="span-2">
        <details class="faq agreement">
          <summary>
            <span class="faq-q">用户协议</span>
            <svg class="faq-arrow" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </summary>
          <div class="faq-a long">
            <p>一、软件性质。宛委·万枢是一款运行在你本机的桌面级 AI 聊天与开发协作平台，当前处于建设阶段，按「现状」提供，不构成对特定用途适用性的承诺。</p>
            <p>二、账号与数据。本软件不设云端账号体系，你的配置、对话与记忆均保存在本机；卸载或删除数据目录前请自行备份。</p>
            <p>三、模型服务。调用第三方模型服务所产生的费用由你与相应服务商结算，并需遵守其服务条款；本软件仅在你主动配置并启用后才会与对应服务商通信。</p>
            <p>四、设备操作。「整台设备」档位与局域网控制等能力会触及真实系统，请仅对可信任务开启，由此产生的操作后果由你自行承担。</p>
            <p>五、边界诚实。标注为「模拟」「占位」「离线示例」的功能尚未接入真实外部调用，不代表最终交付形态。</p>
            <p>六、禁止用途。不得将本软件用于违反法律法规、侵害他人权益的用途。</p>
          </div>
        </details>

        <details class="faq agreement">
          <summary>
            <span class="faq-q">隐私协议</span>
            <svg class="faq-arrow" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </summary>
          <div class="faq-a long">
            <p>一、本地数据不出机。对话记录、记忆内容、工作区文件、设置偏好与反馈表单，全部保存在本机数据目录或浏览器本机存储中，本软件不设有任何默认的数据回传通道。</p>
            <p>二、密钥加密存储。模型服务商密钥仅在你主动填写后保存，落盘前经加密处理，界面展示一律为掩码；真实密钥仅在发起对应模型调用时短暂使用，不写入日志。</p>
            <p>三、对外通信最小化。仅当你配置并启用某个外部能力（如模型 API、局域网访问）时，软件才会与对应目标通信；开启局域网手机控制后，访问范围限于同一局域网。</p>
            <p>四、你的控制权。你可以在「记忆中枢」随时查看与删除记忆，在「通用设置」中清除自定义背景与偏好；删除数据目录即完成彻底清理。</p>
            <p>五、反馈数据。本页反馈表单提交的内容仅存于本机浏览器 localStorage，不会发送给任何服务器。</p>
          </div>
        </details>
      </GfCard>
    </div>
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.span-2 { grid-column: span 2; }
.hint { font-size: 11px; color: var(--ink-muted); line-height: 1.7; letter-spacing: .5px; }
.block-label { font-family: var(--font-kai); font-size: 14px; letter-spacing: 2px; color: var(--ink); margin: 14px 0 8px; }

/* ── FAQ 手风琴 ── */
.faq-list { display: grid; gap: 10px; }
.faq {
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  overflow: hidden;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.faq[open] { border-color: var(--gold-line); box-shadow: var(--shadow-card); }
.faq summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  cursor: pointer;
  list-style: none;
  user-select: none;
}
.faq summary::-webkit-details-marker { display: none; }
.faq summary:hover .faq-q { color: var(--cinnabar); }
.faq-q { font-family: var(--font-kai); font-size: 14px; letter-spacing: 2px; color: var(--ink); transition: color .18s ease; }
.faq-arrow { color: var(--gold); flex-shrink: 0; transition: transform .2s ease; }
.faq[open] .faq-arrow { transform: rotate(180deg); }
.faq-a {
  padding: 0 14px 14px;
  font-size: 12px;
  line-height: 1.9;
  color: var(--ink-soft);
}
.faq-a.long p { margin-bottom: 10px; }
.faq-a.long p:last-child { margin-bottom: 0; }
.agreement { margin-top: 10px; }
.agreement:first-of-type { margin-top: 0; }

/* ── 反馈表单 ── */
.fb-form { display: grid; gap: 12px; margin-top: 12px; }
.fb-form label {
  display: grid;
  gap: 6px;
  color: var(--ink-muted);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 1px;
}
.fb-form input, .fb-form textarea, .fb-form select {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  color: var(--ink);
  padding: 8px 12px;
  font: inherit;
  font-size: 12px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.fb-form textarea { resize: vertical; min-height: 88px; }
.fb-form input:focus, .fb-form textarea:focus, .fb-form select:focus {
  outline: none;
  border-color: var(--cinnabar);
  box-shadow: 0 0 0 3px var(--rouge-glow);
}
.fb-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.form-submit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 20px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 13px;
  letter-spacing: 2px;
  font-family: var(--font-kai);
  cursor: pointer;
  background: linear-gradient(135deg, var(--cinnabar), var(--cinnabar-deep));
  color: #FDF6E9;
  box-shadow: 0 2px 12px var(--cinnabar-glow), var(--shadow-card);
  transition: transform .18s ease, box-shadow .18s ease;
}
.form-submit:hover { transform: translateY(-2px); box-shadow: 0 4px 18px var(--cinnabar-glow), var(--shadow-glow-rouge); }
.fb-msg { font-size: 12px; line-height: 1.6; }
.fb-msg.error { color: var(--cinnabar-deep); }
.fb-msg.ok { color: var(--bamboo); }

/* ── 本机反馈查看 / 导出 ── */
.fb-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}
.fb-list {
  display: grid;
  gap: 10px;
  margin-top: 12px;
  max-height: 320px;
  overflow-y: auto;
  scrollbar-width: thin;
}
.fb-item {
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--card);
  padding: 10px 12px;
}
.fb-item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.fb-item-time {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-muted);
}
.fb-item-desc {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.8;
  color: var(--ink);
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.fb-item-contact {
  margin-top: 4px;
  font-size: 11px;
  color: var(--ink-muted);
  overflow-wrap: anywhere;
}
.fb-store-hint { margin-top: 12px; }

/* ── 关于 ── */
.about-ver { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ver-name { font-family: var(--font-kai); font-size: 22px; font-weight: 700; letter-spacing: 4px; color: var(--ink); }
.about-p { margin-top: 12px; font-size: 12.5px; line-height: 2; color: var(--ink-soft); text-align: justify; }
.stack { display: flex; flex-wrap: wrap; gap: 8px; }

@media (max-width: 980px) {
  .grid { grid-template-columns: 1fr; }
  .span-2 { grid-column: auto; }
}
</style>

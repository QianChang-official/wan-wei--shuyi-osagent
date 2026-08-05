/**
 * 前端 XSS 消毒回归测试（源码级契约断言）。
 * 覆盖两处修复：
 *   ResearchAdoptionView  <a :href> 绑后端 source_urls，须经协议白名单，防 javascript:/data: 伪协议
 *   SettingsView          背景图 url("...") 注入 <style>，加载路径须经 data:image//http(s) 白名单，防 CSS 注入
 * 说明：沿用本项目既有约定——无组件级测试基建，以 node:test 做源码级契约断言。
 */
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../', import.meta.url))
const researchPath = path.join(root, 'src/views/ResearchAdoptionView.vue')
const settingsPath = path.join(root, 'src/views/platform/SettingsView.vue')
const knowledgePath = path.join(root, 'src/views/platform/KnowledgeView.vue')

const research = await readFile(researchPath, 'utf8')
const settings = await readFile(settingsPath, 'utf8')
const knowledge = await readFile(knowledgePath, 'utf8')

test('ResearchAdoptionView: source_urls 经 safeSourceUrl 协议白名单后才进 :href', () => {
  // 模板不得再裸绑 url；须绑消毒函数
  assert.doesNotMatch(research, /:href="url"/)
  assert.match(research, /:href="safeSourceUrl\(url\)"/)
  // 白名单实现：仅放行 http(s)://，否则置空
  assert.match(research, /function safeSourceUrl/)
  assert.match(research, /\/\^https\?:\\\/\\\/\/i\.test\(uri\) \? uri : ''/)
})

test('SettingsView: 背景图经 isSafeBackgroundUrl 白名单后才写入 <style>', () => {
  // sink 处先校验后写入
  assert.match(settings, /if \(!isSafeBackgroundUrl\(dataUrl\)\) return/)
  assert.match(settings, /function isSafeBackgroundUrl/)
  // 仅放行 data:image/ 或 http(s)://
  assert.match(settings, /\^data:image\\\//i)
  // 禁止能突破 url\("..."\) 上下文的字符
  assert.match(settings, /\["'\(\)\\\\<>\\r\\n\]/)
})

test('SettingsView: 校验发生在 style.textContent 赋值之前（顺序契约）', () => {
  const guardIdx = settings.indexOf('if (!isSafeBackgroundUrl(dataUrl)) return')
  const sinkIdx = settings.indexOf('style.textContent = `body::before')
  assert.ok(guardIdx > 0, '未找到守卫语句')
  assert.ok(sinkIdx > 0, '未找到 style 注入 sink')
  assert.ok(guardIdx < sinkIdx, '守卫必须在写入 <style> 之前')
})

test('KnowledgeView: 搜索标题仅通过 Vue 文本插值渲染', () => {
  assert.match(knowledge, /<h3 class="hit-title">\{\{\s*hit\.title\s*\}\}<\/h3>/)
  assert.doesNotMatch(knowledge, /class="hit-title"[^>]*v-html/)
})

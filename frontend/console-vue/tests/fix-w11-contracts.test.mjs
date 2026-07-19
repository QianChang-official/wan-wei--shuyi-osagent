/**
 * W11 前端智能体/空间/自动化契约修复 · 针对性测试
 *
 * 项目前端无组件测试运行器（无 vitest），本测试以源码级契约断言验证
 * AgentsView / SpacesView / AutomationView 的关键修复点真实存在于源码中，
 * 配合 `npx vite build`（产物构建）与 `npx vue-tsc --noEmit`（类型检查）形成闭环。
 */
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../', import.meta.url))
const viewsDir = path.join(root, 'src', 'views', 'platform')

async function readView(name) {
  return readFile(path.join(viewsDir, name), 'utf8')
}

/* ══ AgentsView ══ */

test('AgentsView normRun：note 候选链补齐后端 result 字段（08-#16）', async () => {
  const src = await readView('AgentsView.vue')
  assert.match(src, /note:\s*pickStr\(r,\s*\['note',\s*'result',\s*'error',\s*'message',\s*'output'\]\)/)
})

test('AgentsView normRun：子代理字段宽容对齐 kind/parent_run_id 多名候选（08-#16）', async () => {
  const src = await readView('AgentsView.vue')
  assert.match(src, /pickStr\(r,\s*\['kind',\s*'run_kind',\s*'type'\]\)/)
  assert.match(src, /pickStr\(r,\s*\['parent_run_id',\s*'parent_id',\s*'parent',\s*'parentRunId'\]\)/)
  assert.match(src, /kind === 'subagent' \|\| Boolean\(parentRunId\)/)
  // 子代理无 agent_name 时如实显示「子代理」而非「未名」
  assert.match(src, /isSub \? '子代理' : teamId \|\| '未名'/)
  // 模板渲染子代理徽标
  assert.match(src, /v-if="run\.isSub" class="run-kind">子代理</)
})

test('AgentsView saveAgent：新建后按创建响应 id 找回，名称匹配仅作兜底（08-#17）', async () => {
  const src = await readView('AgentsView.vue')
  assert.match(src, /pickStr\(rec,\s*\['id',\s*'agent_id',\s*'pid'\]\)/)
  assert.match(src, /agents\.value\.find\(\(a\) => a\.id === createdId\)/)
  // 响应体可能包一层 agent 对象，读取链兼容
  assert.match(src, /pickStr\(asRecord\(rec\.agent\),\s*\['id',\s*'agent_id',\s*'pid'\]\)/)
})

test('AgentsView 团队弹层：错误内联展示于弹层内（08-#17）', async () => {
  const src = await readView('AgentsView.vue')
  assert.match(src, /const teamError = ref\(''\)/)
  assert.match(src, /teamError\.value = '团队至少需一名成员。'/)
  assert.match(src, /teamError\.value = platformErrText\(e\)/)
  assert.match(src, /v-if="teamError" class="team-error" role="alert"/)
})

/* ══ SpacesView ══ */

test('SpacesView submitCommit：发送 gear 并如实处理 ok:false（08-#20/05-#3）', async () => {
  const src = await readView('SpacesView.vue')
  // payload 携带 gear
  assert.match(src, /gear:\s*commitForm\.value\.gear/)
  // 响应体 ok:false 不当成功，展示 note/error
  assert.match(src, /data\.ok === false/)
  assert.match(src, /commitError\.value = data\.note \|\| data\.error \|\| '提交未通过'/)
  // 档位选择 UI 与提示
  assert.match(src, /COMMIT_GEARS/)
  assert.match(src, /v-model="commitForm\.gear"/)
  // 真实提交成功展示 commit_id
  assert.match(src, /commitResult\.commit_id/)
})

test('SpacesView 默认提交模板只要求一层 scope 括号', async () => {
  const src = await readView('SpacesView.vue')
  const start = src.indexOf('function buildTemplateRegex')
  const end = src.indexOf('\nconst commitHint', start)
  assert.ok(start >= 0 && end > start, '未找到 buildTemplateRegex')

  // 直接执行视图中的纯函数，防止静态断言漏掉转义顺序导致的双括号回归。
  const js = src.slice(start, end)
    .replace('template: string', 'template')
    .replace('types: string[]', 'types')
    .replace('requireScope: boolean', 'requireScope')
    .replace('): RegExp | null', ')')
  const buildTemplateRegex = Function(`return (${js})`)()
  const required = buildTemplateRegex('<type>(<scope>): <subject>', ['feat', 'fix'], true)
  assert.ok(required instanceof RegExp)
  assert.equal(required.test('feat(spaces): 对齐提交模板'), true)
  assert.equal(required.test('feat((spaces)): 双括号不应通过'), false)
  assert.equal(required.test('feat(): 空 scope 不应通过'), false)

  const optional = buildTemplateRegex('<type>(<scope>): <subject>', ['feat'], false)
  assert.equal(optional.test('feat: 无 scope 可通过'), true)
  assert.equal(optional.test('feat(spaces): 有 scope 也可通过'), true)
  assert.equal(optional.test('fix(spaces): 非允许 type 不通过'), false)
})

test('SpacesView lanes：消费后端 ahead_behind 字典与顶层 dirty 计数（08-#19/05-#4）', async () => {
  const src = await readView('SpacesView.vue')
  assert.match(src, /t\?\.ahead_behind/)
  assert.match(src, /ab\[def\.key\]/)
  // main 泳道按主干角色匹配而非硬编码分支名
  assert.match(src, /\(b\.role \?\? ''\)\.includes\('主干'\)/)
  // 顶层 dirty 整数计数落到活跃泳道
  assert.match(src, /isActive && dirtyCount > 0/)
  // 兜底示例与后端真实 payload 同构（branches 数组 + ahead_behind 字典）
  const sample = src.slice(src.indexOf('const SAMPLE_TREE'), src.indexOf('const SAMPLE_TEMPLATE'))
  assert.match(sample, /branches:\s*\[/)
  assert.match(sample, /ahead_behind:\s*\{/)
})

test('SpacesView loadProjects/loadIntegrations：空列表是合法状态，不再 throw empty（08-#21）', async () => {
  const src = await readView('SpacesView.vue')
  assert.equal(src.includes("throw new Error('empty')"), false, '仍存在 throw empty')
})

test('SpacesView bindIntegration：忙态守卫独立前置，无穿透路径（08-#22 残留）', async () => {
  const src = await readView('SpacesView.vue')
  const fnStart = src.indexOf('async function bindIntegration')
  const fnEnd = src.indexOf('async function unbindIntegration')
  const fn = src.slice(fnStart, fnEnd)
  assert.ok(fnStart >= 0 && fnEnd > fnStart)
  const busyGuard = fn.indexOf('if (intgBusy.value) return')
  const tokenCheck = fn.indexOf("if (!token)")
  assert.ok(busyGuard >= 0, '缺少独立忙态守卫')
  assert.ok(busyGuard < tokenCheck, '忙态守卫必须先于 token 校验')
})

/* ══ AutomationView ══ */

test('AutomationView normNextRun：候选链以契约 next_run 为首，保留旧候选兜底（08-#25）', async () => {
  const src = await readView('AutomationView.vue')
  assert.match(src, /raw\.next_run \?\? raw\.next_at \?\? raw\.next_run_at \?\? raw\.time/)
  // approximate 标志透传并以「约」标注
  assert.match(src, /approximate: raw\.approximate === true/)
  assert.match(src, /n\.approximate \? '约 ' : ''/)
})

test('AutomationView RUN_META 补 done；normRun 映射 done/simulated（08-#26）', async () => {
  const src = await readView('AutomationView.vue')
  assert.match(src, /done:\s*\{ label: '成功', tone: 'bamboo' \}/)
  assert.match(src, /done: raw\.done === true \|\| status === 'done'/)
  assert.match(src, /simulated: raw\.simulated === true/)
  // 运行留痕渲染模拟徽标
  assert.match(src, /v-if="run\.simulated" tone="gold">模拟</)
})

test('AutomationView FlowStep 透传 config；applyAi 前置校验 proposedFlow（08-#26）', async () => {
  const src = await readView('AutomationView.vue')
  assert.match(src, /config\?: Record<string, unknown>/)
  assert.match(src, /config: o\.config && typeof o\.config === 'object'/)
  assert.match(src, /AI 方案缺少 proposed_flow，无法应用；请重新解析。/)
})

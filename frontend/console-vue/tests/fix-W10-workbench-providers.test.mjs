/**
 * W10 修复回归测试（前端工作台与厂商）。
 * 覆盖条目：
 *   08-#7  context-size 候选链含 total_tokens、请求带 ?agent_id=
 *   08-#8  三处 Enter 直判补 isComposing（IME 合成期不发送）
 *   08-#9  审批改用后端真实 status，不再本地假置 approved
 *   08-#10 附件大小/数量前端限制与提示
 *   08-#11 FALLBACK_CATALOG pid 与后端 providers.py CATALOG id 键逐一对齐
 *   08-#12 脱敏字段 has_api_key/api_key_tail 读取链对齐
 *   08-#14 OAuth 轮询网络错误退避重试 + verificationUri 仅放行 https
 * 说明：前端无组件级测试基建（不新增第三方依赖），此处以 node:test 做源码级契约断言。
 */
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../', import.meta.url))
const workbenchPath = path.join(root, 'src/views/platform/WorkbenchView.vue')
const providersViewPath = path.join(root, 'src/views/platform/ProvidersView.vue')
const backendProvidersPath = path.join(root, '../../backend/app/platform_api/providers.py')

const workbench = await readFile(workbenchPath, 'utf8')
const providersView = await readFile(providersViewPath, 'utf8')
const backendProviders = await readFile(backendProvidersPath, 'utf8')

test('08-#7 context-size 传 ?agent_id= 且候选链以 total_tokens 为首', () => {
  assert.match(workbench, /\?agent_id=\$\{encodeURIComponent\(currentAgentId\.value\)\}/)
  assert.match(workbench, /res\?\.total_tokens \?\? res\?\.used/)
})

test('08-#8 三处 Enter 处理均含 isComposing 判断', () => {
  const matches = workbench.match(/e\.key === 'Enter' && !e\.isComposing/g) ?? []
  assert.equal(matches.length, 3, `预期 3 处 isComposing 判断，实际 ${matches.length} 处`)
})

test('08-#9 审批使用后端返回的真实 status，无本地假放行', () => {
  assert.match(workbench, /const actual = typeof res\?\.status === 'string'/)
  assert.doesNotMatch(workbench, /approvedLocally/)
  assert.doesNotMatch(workbench, /已在本地标记为已批准/)
})

test('08-#10 附件限制常量与超限提示存在', () => {
  assert.match(workbench, /const ATTACH_MAX_COUNT = 5/)
  assert.match(workbench, /const ATTACH_MAX_SIZE = 10 \* 1024 \* 1024/)
  assert.match(workbench, /附件最多 \$\{ATTACH_MAX_COUNT\} 个/)
  assert.match(workbench, /超过单文件 \$\{fmtSize\(ATTACH_MAX_SIZE\)\} 上限/)
})

test('08-#11 FALLBACK_CATALOG pid 与后端 CATALOG id 键逐一对齐', () => {
  const backendIds = [...backendProviders.matchAll(/^\s+'id': '([^']+)',$/gm)].map((m) => m[1])
  assert.equal(backendIds.length, 31, `后端 CATALOG 预期 31 家，解析到 ${backendIds.length} 家`)
  const fbStart = providersView.indexOf('const FALLBACK_CATALOG')
  const fbEnd = providersView.indexOf('\n]', fbStart)
  const fallbackBlock = providersView.slice(fbStart, fbEnd)
  const fallbackPids = [...fallbackBlock.matchAll(/\{ pid: '([^']+)'/g)].map((m) => m[1])
  assert.deepEqual(fallbackPids, backendIds, 'FALLBACK_CATALOG pid 顺序与后端 CATALOG id 不一致')
})

test('08-#12 脱敏字段读取链以 has_api_key/api_key_tail 优先、历史别名兜底', () => {
  assert.match(providersView, /c\?\.api_key_tail \|\| c\?\.key_tail/)
  assert.match(providersView, /c\?\.has_api_key \|\| c\?\.has_key/)
  assert.match(providersView, /typeof c\.configured === 'boolean'/)
})

test('08-#14 OAuth 轮询网络错误退避重试且 verificationUri 仅放行 https', () => {
  assert.match(providersView, /const OAUTH_POLL_MAX_NET_RETRIES = 3/)
  assert.match(providersView, /isNetworkError\(e\) && netRetries < OAUTH_POLL_MAX_NET_RETRIES/)
  assert.match(providersView, /intervalMs \* 2 \*\* \(netRetries \+ 1\)/)
  assert.match(providersView, /uri\.startsWith\('https:\/\/'\) \? uri : ''/)
  assert.match(providersView, /sanitizeVerificationUri\(res\.verification_uri/)
})

test('头注释不再宣称「全部调用失败均降级为本地示例」', () => {
  assert.doesNotMatch(workbench, /全部调用失败均降级为本地示例/)
  assert.match(workbench, /仅网络异常（isNetworkError）时降级为本地示例/)
})

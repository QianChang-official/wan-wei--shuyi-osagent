// W12 前端会话与架构层修复的针对性测试。
// 覆盖：platform.ts 超时/AbortController（09-#13）、platformEnums 共享枚举（09-#11/#12）、
// 以及 SessionsView / MobileView / HelpView / router / client.ts 的修复要点静态断言。
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createServer } from 'vite'

const root = fileURLToPath(new URL('../', import.meta.url))
const configFile = path.join(root, 'vite.config.ts')

async function withServer(fn) {
  const server = await createServer({
    root,
    configFile,
    logLevel: 'silent',
    server: { middlewareMode: true },
  })
  try {
    await fn(server)
  } finally {
    await server.close()
  }
}

async function importTs(server, url) {
  const transformed = await server.transformRequest(url)
  assert.ok(transformed, `transform failed: ${url}`)
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString('base64')}`
  return import(moduleUrl)
}

function stubFetchOnce(impl) {
  const original = globalThis.fetch
  globalThis.fetch = impl
  return () => { globalThis.fetch = original }
}

/* ── 09-#13：platform.ts 请求超时 ── */

test('platform.ts: 默认调用保持向后兼容（JSON 头 + 响应解析）', async () => {
  await withServer(async (server) => {
    const platform = await importTs(server, '/src/api/platform.ts')
    let seen
    const restore = stubFetchOnce(async (_url, init) => {
      seen = init
      return new Response('{"ok":true}', { headers: { 'Content-Type': 'application/json' } })
    })
    try {
      const res = await platform.apiPost('/echo', { a: 1 })
      assert.deepEqual(res, { ok: true })
      const headers = new Headers(seen.headers)
      assert.equal(headers.get('Content-Type'), 'application/json')
      assert.equal(JSON.parse(seen.body).a, 1)
    } finally {
      restore()
    }
  })
})

test('platform.ts: 超时抛 PlatformApiError(timeout=true, status=0)，可用 isTimeoutError 区分', async () => {
  await withServer(async (server) => {
    const platform = await importTs(server, '/src/api/platform.ts')
    const restore = stubFetchOnce((_url, init) => new Promise((_resolve, reject) => {
      const sig = init?.signal
      if (sig?.aborted) reject(new DOMException('This operation was aborted', 'AbortError'))
      else sig?.addEventListener('abort', () => reject(new DOMException('This operation was aborted', 'AbortError')))
    }))
    try {
      await assert.rejects(
        platform.apiGet('/hang', { timeoutMs: 50 }),
        (err) => {
          assert.ok(err instanceof platform.PlatformApiError, `应为 PlatformApiError，实际 ${err}`)
          assert.equal(err.timeout, true)
          assert.equal(err.status, 0)
          assert.match(err.message, /超时/)
          assert.ok(platform.isTimeoutError(err))
          assert.equal(platform.isNetworkError(err), false, '超时不得误判为网络错误')
          return true
        },
      )
    } finally {
      restore()
    }
  })
})

test('platform.ts: 调用方 signal 中止时不伪装成超时', async () => {
  await withServer(async (server) => {
    const platform = await importTs(server, '/src/api/platform.ts')
    const restore = stubFetchOnce((_url, init) => new Promise((_resolve, reject) => {
      const sig = init?.signal
      if (sig?.aborted) reject(new DOMException('This operation was aborted', 'AbortError'))
      else sig?.addEventListener('abort', () => reject(new DOMException('This operation was aborted', 'AbortError')))
    }))
    try {
      const ac = new AbortController()
      const pending = platform.apiGet('/hang', { signal: ac.signal, timeoutMs: 5000 })
      setTimeout(() => ac.abort(), 20)
      await assert.rejects(pending, (err) => {
        assert.equal(platform.isTimeoutError(err), false, '调用方主动中止不得标记为超时')
        return true
      })
    } finally {
      restore()
    }
  })
})

test('platform.ts: 非 2xx 仍透出后端 detail（回归保护）', async () => {
  await withServer(async (server) => {
    const platform = await importTs(server, '/src/api/platform.ts')
    const restore = stubFetchOnce(async () => new Response(
      JSON.stringify({ detail: '会话 xxx 不存在' }),
      { status: 404, headers: { 'Content-Type': 'application/json' } },
    ))
    try {
      await assert.rejects(platform.apiGet('/missing'), (err) => {
        assert.ok(err instanceof platform.PlatformApiError)
        assert.equal(err.status, 404)
        assert.equal(err.detail, '会话 xxx 不存在')
        assert.equal(err.timeout, false)
        return true
      })
    } finally {
      restore()
    }
  })
})

/* ── 09-#11/#12：共享枚举模块 ── */

test('platformEnums: GEAR_TONES 单源且语义一致', async () => {
  await withServer(async (server) => {
    const enums = await importTs(server, '/src/utils/platformEnums.ts')
    assert.deepEqual(Object.keys(enums.GEAR_TONES).sort(), ['device', 'human_review', 'sandbox'])
    assert.equal(enums.GEAR_TONES.human_review, 'gold')
    assert.equal(enums.GEAR_TONES.sandbox, 'bamboo')
    assert.equal(enums.GEAR_TONES.device, 'rouge')
    for (const g of enums.GEARS) {
      assert.ok(enums.GEAR_LABELS[g], `缺 GEAR_LABELS[${g}]`)
      assert.ok(enums.GEAR_TONES[g], `缺 GEAR_TONES[${g}]`)
    }
  })
})

test('platformEnums: 运行状态标签/分组映射', async () => {
  await withServer(async (server) => {
    const enums = await importTs(server, '/src/utils/platformEnums.ts')
    assert.equal(enums.runStatusLabel('awaiting_review'), '待审查')
    assert.equal(enums.runStatusLabel('cancelled'), '已取消')
    assert.equal(enums.runStatusLabel(''), '未知')
    assert.equal(enums.runStatusLabel('unknown'), '未知')
    assert.equal(enums.runStatusLabel('custom_state'), 'custom_state')
    assert.equal(enums.runStatusGroup('running'), 'run')
    assert.equal(enums.runStatusGroup('awaiting_review'), 'review')
    assert.equal(enums.runStatusGroup('done'), 'ok')
    assert.equal(enums.runStatusGroup('failed'), 'bad')
    assert.equal(enums.runStatusGroup('whatever'), 'idle')
    assert.equal(enums.runStatusTone('awaiting_review'), 'gold')
  })
})

/* ── 视图/路由层修复要点（静态断言） ── */

async function readSrc(rel) {
  return readFile(path.join(root, 'src', rel), 'utf8')
}

test('SessionsView: usage_count 候选链 + /use 上报 + maxlength 200 + 诚实文案（08-#28/#29）', async () => {
  const code = await readSrc('views/platform/SessionsView.vue')
  assert.ok(code.includes('usage_count'), '候选链缺 usage_count')
  assert.ok(code.includes('/use'), '未调用 /phrases/{pid}/use')
  assert.ok(code.includes('maxlength="200"'), 'maxlength 未对齐后端 200')
  assert.equal(code.includes('maxlength="100"'), false, '残留 maxlength 100')
  assert.equal(code.includes('操作将在连接恢复后生效'), false, '误导性文案未移除')
  assert.equal(/s\.pinned = false/.test(code), false, '归档仍本地强置 pinned=false')
})

test('MemoryCenter/Sessions: 仅全网络失败使用示例，鉴权失败清空示例并明示错误', async () => {
  for (const name of ['MemoryCenterView.vue', 'SessionsView.vue']) {
    const code = await readSrc(`views/platform/${name}`)
    const start = code.indexOf('async function loadAll')
    const end = code.indexOf('\nasync function ', start + 1)
    const loadAll = code.slice(start, end)
    assert.ok(start >= 0 && end > start, `${name} 未找到 loadAll`)
    assert.equal(loadAll.includes('else if (failedAll)'), false, `${name} 仍在任意全失败时装载示例`)
    assert.match(loadAll, /offline\.value = allNetwork/)
    assert.match(loadAll, /failedAll && firstFailure && !allNetwork/)
    assert.match(loadAll, /error\.value = errText\(firstFailure\.reason\)/)
  }

  const memory = await readSrc('views/platform/MemoryCenterView.vue')
  assert.ok(memory.includes("instructionsText.value = FALLBACK_LINES.join('\\n')"))
  assert.match(memory, /else \{\s*\/\/[^\n]*\n\s*instructionsText\.value = ''\s*\n\s*savedText\.value = ''/)
  assert.match(memory, /else if \(allNetwork\) \{\s*dreams\.value = FALLBACK_DREAMS/)
  assert.match(memory, /else \{\s*dreams\.value = \[\]/)

  const sessions = await readSrc('views/platform/SessionsView.vue')
  assert.match(sessions, /else if \(allNetwork\) \{\s*sessions\.value = FALLBACK_SESSIONS/)
  assert.match(sessions, /else \{\s*\/\/[^\n]*\n\s*sessions\.value = \[\]/)
  assert.match(sessions, /else if \(allNetwork\) \{\s*phrases\.value = FALLBACK_PHRASES/)
  assert.match(sessions, /else \{\s*phrases\.value = \[\]/)
})

test('MobileView: token 不滞留地址栏 + 共享状态映射 + 浮动窗补救（08-#37）', async () => {
  const code = await readSrc('views/platform/MobileView.vue')
  assert.ok(code.includes('stripTokenFromUrl'), '配对成功后未清除地址栏 token')
  assert.ok(code.includes('maskToken'), '失败文案未做 token 脱敏')
  assert.ok(code.includes('@/utils/platformEnums'), '未采用共享状态映射')
  assert.equal(code.includes('STATUS_LABELS'), false, '残留私有状态映射')
  assert.ok(code.includes('isFloating'), '未识别 floating 浮动窗模式')
  assert.ok(code.includes('submitManualToken'), '缺手动粘贴令牌入口')
})

test('HelpView: 本机反馈可查看/导出/复制（08-#38）', async () => {
  const code = await readSrc('views/platform/HelpView.vue')
  for (const fn of ['exportFeedback', 'copyFeedback', 'clearFeedback', 'fbList']) {
    assert.ok(code.includes(fn), `缺 ${fn}`)
  }
  assert.ok(code.includes('localStorage'), '导出未基于本机 localStorage')
})

test('router: catch-all 404 + 标题守卫 + 平台路由注释更新（09-#9/#14）', async () => {
  const index = await readSrc('router/index.ts')
  assert.ok(index.includes(":pathMatch(.*)*"), '缺 catch-all 路由')
  assert.ok(index.includes('NotFoundView'), '缺 NotFoundView')
  assert.ok(index.includes('afterEach'), '缺标题同步守卫')
  const platform = await readSrc('router/platform.ts')
  assert.equal(platform.includes('最小占位文件'), false, '平台路由仍残留过时注释')
})

test('App.vue: 死路由补侧栏入口（09-#9）', async () => {
  const app = await readSrc('App.vue')
  for (const p of ["'/capsules'", "'/command'", "'/reflection'", "'/audit'", "'/mobile'"]) {
    assert.ok(app.includes(`to: ${p}`), `侧栏缺 ${p} 入口`)
  }
})

test('client.ts: api.soulDream 死方法已删除（09-#10）', async () => {
  const code = await readSrc('api/client.ts')
  assert.equal(/soulDream\s*[:|(]/.test(code.replace(/soulDreamCycle/g, '')), false, 'api.soulDream 仍残留')
  assert.ok(code.includes('soulDreamCycle'), 'soulDreamCycle 被误删')
})

test('NotFoundView: 404 视图存在且为中文引导', async () => {
  const code = await readSrc('views/NotFoundView.vue')
  assert.ok(code.includes('迷途'), 'NotFoundView 缺中文标题')
  assert.ok(code.includes('RouterLink'), 'NotFoundView 缺返回引导')
})

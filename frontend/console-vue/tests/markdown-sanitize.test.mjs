// Copyright (c) 2026 QianChang-official
//
// 宛委·枢忆 is licensed under Mulan PSL v2.
// You can use this software according to the terms of the Mulan PSL v2.
// You may obtain a copy of Mulan PSL v2 at:
// http://license.coscl.org.cn/MulanPSL2
//
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.

/**
 * Markdown 渲染器 XSS 消毒契约测试（源码级断言 + 行为级断言）。
 * 沿用本项目既有约定：无组件级测试基建，以 node:test 做契约断言。
 * 行为级断言通过 vite dev transform 加载 src/utils/markdown.ts 执行。
 */
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createServer } from 'vite'

const root = fileURLToPath(new URL('../', import.meta.url))
const markdownPath = path.join(root, 'src/utils/markdown.ts')

test('markdown.ts 先转义后渲染，链接仅放行 http/https', async () => {
  const source = await readFile(markdownPath, 'utf8')
  // 1. 存在全量 HTML 实体转义
  assert.match(source, /replace\(\/&\/g, '&amp;'\)/)
  assert.match(source, /replace\(\/<\/g, '&lt;'\)/)
  assert.match(source, /replace\(\/>\/g, '&gt;'\)/)
  // 2. URL 白名单仅 http/https
  assert.match(source, /\^https\?:\\\//)
  // 3. 链接强制 noopener + 新窗口
  assert.match(source, /rel="noopener noreferrer"/)
})

test('markdown 行为：脚本注入被转义，伪协议链接被降级', async () => {
  const server = await createServer({
    root,
    configFile: path.join(root, 'vite.config.ts'),
    logLevel: 'silent',
    server: { middlewareMode: true },
  })

  try {
    const transformed = await server.transformRequest('/src/utils/markdown.ts')
    assert.ok(transformed)
    const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString('base64')}`
    const { renderMarkdown, sanitizeUrl } = await import(moduleUrl)

    // 伪协议永不成链
    assert.equal(sanitizeUrl('javascript:alert(1)'), null)
    assert.equal(sanitizeUrl('data:text/html,<script>'), null)
    assert.equal(sanitizeUrl('  https://example.com/x '), 'https://example.com/x')

    // HTML 注入被转义
    const html = renderMarkdown('<img src=x onerror=alert(1)> **加粗** `a<b`')
    assert.ok(!html.includes('<img'), '原始标签不得进入输出')
    assert.ok(html.includes('&lt;img'))
    assert.ok(html.includes('<strong>加粗</strong>'))
    assert.ok(html.includes('<code class="md-ic">a&lt;b</code>'))

    // javascript: 链接降级为纯文本
    const linkHtml = renderMarkdown('[点我](javascript:alert(1))')
    assert.ok(!linkHtml.includes('href'), '伪协议链接不得生成 href')

    // 合法 https 链接正常生成
    const okHtml = renderMarkdown('[文档](https://example.com/doc)')
    assert.ok(okHtml.includes('href="https://example.com/doc"'))
    assert.ok(okHtml.includes('rel="noopener noreferrer"'))

    // 纯数字段落不得被代码块哨兵吞掉
    const numHtml = renderMarkdown('42')
    assert.ok(numHtml.includes('42'))
  } finally {
    await server.close()
  }
})

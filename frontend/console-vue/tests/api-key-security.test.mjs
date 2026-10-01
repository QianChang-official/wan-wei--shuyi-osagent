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

import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { mkdtemp, readdir, readFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { runInNewContext } from 'node:vm'

import { createServer } from 'vite'

const root = fileURLToPath(new URL('../', import.meta.url))
const configFile = path.join(root, 'vite.config.ts')
const developmentApiKey = 'wanwei-dev-key'
const execFileAsync = promisify(execFile)

test('same-origin early bootstrap applies stored theme and handles unavailable storage', async () => {
  const source = await readFile(path.join(root, 'public/theme-init.js'), 'utf8')
  for (const [stored, expected] of [['night', 'night'], ['day', 'day'], [null, 'day'], ['unexpected', 'day']]) {
    const document = { documentElement: { dataset: {} } }
    runInNewContext(source, {
      document,
      localStorage: { getItem(key) { assert.equal(key, 'gf-theme'); return stored } },
    })
    assert.equal(document.documentElement.dataset.theme, expected)
  }
  const document = { documentElement: { dataset: {} } }
  runInNewContext(source, { document, localStorage: { getItem() { throw new Error('storage blocked') } } })
  assert.equal(document.documentElement.dataset.theme, 'day')
})

async function readBundleArtifacts(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = await Promise.all(entries.map(async (entry) => {
    const entryPath = path.join(directory, entry.name)
    if (entry.isDirectory()) return readBundleArtifacts(entryPath)
    return entry.name.endsWith('.js') || entry.name.endsWith('.map') ? [entryPath] : []
  }))
  return files.flat()
}

test('development transform provides the local API key by default', async (context) => {
  const server = await createServer({
    root,
    configFile,
    logLevel: 'silent',
    server: { middlewareMode: true },
  })
  context.after(() => server.close())

  const transformed = await server.transformRequest('/src/api/client.ts')

  assert.ok(transformed)
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString('base64')}`
  const client = await import(moduleUrl)
  const originalFetch = globalThis.fetch
  let requestHeaders
  globalThis.fetch = async (_path, init) => {
    requestHeaders = init.headers
    return new Response('{}', { headers: { 'Content-Type': 'application/json' } })
  }
  context.after(() => {
    globalThis.fetch = originalFetch
  })

  await client.api.health()
  await client.api.writeCapsule({ content: { text: 'local development' } })

  assert.equal(requestHeaders.get('X-API-Key'), developmentApiKey)
})

test('production bundle excludes the local API key and requires only same-origin CSP resources', async (context) => {
  const outDir = await mkdtemp(path.join(os.tmpdir(), 'wanwei-production-bundle-'))
  context.after(() => rm(outDir, { recursive: true, force: true }))
  const viteBin = path.join(root, 'node_modules', 'vite', 'bin', 'vite.js')
  await execFileAsync(process.execPath, [
    viteBin,
    'build',
    '--config',
    configFile,
    '--outDir',
    outDir,
    '--emptyOutDir',
  ], {
    cwd: root,
    env: { ...process.env, NODE_ENV: 'production' },
  })
  const html = await readFile(path.join(outDir, 'index.html'), 'utf8')
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)]
  assert.ok(scripts.length >= 2, 'missing theme bootstrap or app entry')
  for (const [, attributes, body] of scripts) {
    assert.equal(body.trim(), '', 'production HTML contains an inline executable script')
    assert.match(attributes, /\bsrc=["']\/console\/(?!\/)[^"']+["']/, 'script must use the same-origin /console base')
  }
  assert.match(html, /<script src="\/console\/theme-init\.js"><\/script>/)
  assert.ok(html.indexOf('/console/theme-init.js') < html.indexOf('<body>'), 'theme must initialize before first body paint')
  assert.equal(/\son\w+\s*=/i.test(html), false, 'inline event handlers violate script-src self')
  assert.equal(html.includes('cdn.jsdelivr.net'), false, 'remote font CDN is forbidden')
  assert.equal(html.includes('lxgw-wenkai-webfont'), false, 'remote webfont dependency is forbidden')
  for (const [link] of html.matchAll(/<link\b[^>]*>/gi)) {
    if (/\brel=["']stylesheet["']/i.test(link)) {
      assert.match(link, /\bhref=["']\/console\/(?!\/)[^"']+["']/, 'styles must be same-origin')
    }
  }
  assert.equal(await readFile(path.join(outDir, 'theme-init.js'), 'utf8'),
    await readFile(path.join(root, 'public/theme-init.js'), 'utf8'), 'Vite must copy the exact tested bootstrap asset')
  const chunks = await readBundleArtifacts(outDir)

  assert.ok(chunks.length > 0)
  for (const chunk of chunks) {
    const code = await readFile(chunk, 'utf8')
    assert.equal(code.includes(developmentApiKey), false, path.basename(chunk))
  }
})

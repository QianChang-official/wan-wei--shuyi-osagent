import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { mkdtemp, readdir, readFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

import { createServer } from 'vite'

const root = fileURLToPath(new URL('../', import.meta.url))
const configFile = path.join(root, 'vite.config.ts')
const developmentApiKey = 'wanwei-dev-key'
const execFileAsync = promisify(execFile)

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

  await client.api.writeCapsule({ content: { text: 'local development' } })

  assert.equal(requestHeaders.get('X-API-Key'), developmentApiKey)
})

test('production bundle excludes the local API key', async (context) => {
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
  const chunks = await readBundleArtifacts(outDir)

  assert.ok(chunks.length > 0)
  for (const chunk of chunks) {
    const code = await readFile(chunk, 'utf8')
    assert.equal(code.includes(developmentApiKey), false, path.basename(chunk))
  }
})

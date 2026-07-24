#!/usr/bin/env node

const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const args = process.argv.slice(2)
const projectRoot = path.resolve(__dirname, '..')
const registerShim = path.join(projectRoot, 'src/test/register-encoding-lite.cjs')
const vitestBin = path.join(projectRoot, 'node_modules/vitest/vitest.mjs')
const vitestChunksDir = path.join(projectRoot, 'node_modules/vitest/dist/chunks')

const existingNodeOptions = process.env.NODE_OPTIONS ? `${process.env.NODE_OPTIONS} ` : ''
const patchedNodeOptions = `${existingNodeOptions}--require=${registerShim}`.trim()

// Vitest's build emits content-hashed chunk filenames (e.g. index.CyBMJtT7.js),
// so the hash changes on every Vitest upgrade. Search by content instead of a
// pinned filename so this keeps working across version bumps.
function ensureJsdomPatch() {
  let entries
  try {
    entries = fs.readdirSync(vitestChunksDir)
  } catch (err) {
    console.warn('[hf] warning: unable to read Vitest chunks directory', err)
    return
  }
  for (const entry of entries) {
    if (!entry.endsWith('.js')) continue
    const chunkPath = path.join(vitestChunksDir, entry)
    const content = fs.readFileSync(chunkPath, 'utf8')
    if (!content.includes('runScripts = "dangerously"')) continue
    const patched = content.replace(/runScripts = "dangerously"/g, 'runScripts = void 0')
    fs.writeFileSync(chunkPath, patched, 'utf8')
  }
}

ensureJsdomPatch()

const child = spawn(process.execPath, [vitestBin, ...args], {
  stdio: 'inherit',
  env: {
    ...process.env,
    NODE_OPTIONS: patchedNodeOptions,
  },
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
  } else {
    process.exit(code ?? 0)
  }
})

child.on('error', (err) => {
  console.error(err)
  process.exit(1)
})

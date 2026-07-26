import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { findBorderShorthandCollisions } from '../borderShorthandScan'

describe('findBorderShorthandCollisions — scanner semantics', () => {
  it('reports a single object that mixes the border shorthand with borderLeft', () => {
    const src = 'const s = { border: "1px solid red", borderLeft: "3px solid blue" }'
    const findings = findBorderShorthandCollisions(src, 'fixture.js')
    expect(findings).toHaveLength(1)
    expect(findings[0].file).toBe('fixture.js')
    expect(findings[0].line).toBe(1)
    expect(findings[0].keys).toContain('border')
    expect(findings[0].keys).toContain('borderLeft')
  })

  it('reports the border shorthand mixed with any per-side longhand', () => {
    for (const side of ['borderTop', 'borderRight', 'borderBottom', 'borderLeft']) {
      const src = `const s = { border: "none", ${side}: "1px solid #333" }`
      const findings = findBorderShorthandCollisions(src, 'fixture.js')
      expect(findings, side).toHaveLength(1)
      expect(findings[0].keys, side).toEqual(expect.arrayContaining(['border', side]))
    }
  })

  it('reports the collision inside a JSX style={{ ... }} object (proves JSX parsing)', () => {
    const src = 'const el = <div style={{ border: 1, borderTop: 2 }} />'
    const findings = findBorderShorthandCollisions(src, 'fixture.jsx')
    expect(findings).toHaveLength(1)
    expect(findings[0].keys).toEqual(expect.arrayContaining(['border', 'borderTop']))
  })

  it('reports collisions written with quoted (string-literal) keys', () => {
    const src = 'const s = { "border": 1, "borderBottom": 2 }'
    const findings = findBorderShorthandCollisions(src, 'fixture.js')
    expect(findings).toHaveLength(1)
    expect(findings[0].keys).toEqual(expect.arrayContaining(['border', 'borderBottom']))
  })

  it('is clean for an object that only declares the border shorthand', () => {
    const src = 'const s = { border: "1px solid red", background: "white" }'
    expect(findBorderShorthandCollisions(src, 'fixture.js')).toEqual([])
  })

  it('is clean for an object that only declares per-side longhands', () => {
    const src = 'const s = { borderTop: "none", borderBottom: "1px solid #333", borderLeft: "3px solid blue" }'
    expect(findBorderShorthandCollisions(src, 'fixture.js')).toEqual([])
  })

  it('does not flag borderRadius sitting beside the border shorthand', () => {
    const src = 'const s = { border: "1px solid red", borderRadius: 8 }'
    expect(findBorderShorthandCollisions(src, 'fixture.js')).toEqual([])
  })

  it('does not conflate sibling objects — border in one, borderLeft in another', () => {
    const src = 'const a = { border: "1px solid red" }; const b = { borderLeft: "3px solid blue" }'
    expect(findBorderShorthandCollisions(src, 'fixture.js')).toEqual([])
  })

  it('does flag two independent collisions as two findings', () => {
    const src = [
      'const a = { border: 1, borderLeft: 2 }',
      'const b = { border: 3, borderTop: 4 }',
    ].join('\n')
    const findings = findBorderShorthandCollisions(src, 'fixture.js')
    expect(findings).toHaveLength(2)
    expect(findings[0].line).toBe(1)
    expect(findings[1].line).toBe(2)
  })

  it('ignores computed keys (cannot be statically resolved to `border`)', () => {
    const src = 'const k = "border"; const s = { [k]: 1, borderLeft: 2 }'
    expect(findBorderShorthandCollisions(src, 'fixture.js')).toEqual([])
  })

  it('fails closed: an unparseable source yields a finding, never a silent skip', () => {
    const src = 'const s = { border: 1, borderLeft: '
    const findings = findBorderShorthandCollisions(src, 'broken.js')
    expect(findings).toHaveLength(1)
    expect(findings[0].file).toBe('broken.js')
    expect(findings[0].parseError).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// Repo-wide guard: sweep every production *.js / *.jsx module under src/ui/src
// (tests and test infra excluded) and assert not one inline-style object mixes
// the `border` shorthand with a per-side longhand. The sweep walks the tree at
// run time, so a newly added component is covered with no edit to any list. See
// issue #10583 and #10564/#10571/#10579 for the failure this closes.
// ---------------------------------------------------------------------------
const HERE = path.dirname(fileURLToPath(import.meta.url))
const SRC_ROOT = path.resolve(HERE, '../..') // -> src/ui/src

function collectSourceFiles(dir) {
  const out = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === '__tests__' || entry.name === 'test' || entry.name === 'node_modules') continue
      out.push(...collectSourceFiles(full))
    } else if (/\.(jsx?|mjs)$/.test(entry.name) && !/\.(test|spec)\.[cm]?jsx?$/.test(entry.name)) {
      out.push(full)
    }
  }
  return out
}

describe('repo-wide border-shorthand guard (#10583)', () => {
  it('finds source files to scan (sanity — the sweep is not empty)', () => {
    expect(collectSourceFiles(SRC_ROOT).length).toBeGreaterThan(10)
  })

  it('has no inline-style object mixing `border` with a per-side longhand', () => {
    const findings = []
    for (const file of collectSourceFiles(SRC_ROOT)) {
      const src = fs.readFileSync(file, 'utf8')
      findings.push(...findBorderShorthandCollisions(src, path.relative(SRC_ROOT, file)))
    }
    const report = findings.map(f => `  ${f.file}:${f.line} { ${f.keys.join(' + ')} }${f.parseError ? ` (parse error: ${f.parseError})` : ''}`).join('\n')
    expect(findings, `border shorthand/longhand collisions found:\n${report}`).toEqual([])
  })
})

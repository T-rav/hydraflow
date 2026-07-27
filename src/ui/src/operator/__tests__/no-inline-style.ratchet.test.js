/**
 * Inline-style + hardcoded-colour ratchet for the operator console
 * (epic #10556, Phase 2, Task 12).
 *
 * This is the JS/vitest mirror of the repo's Python disturbance ratchet
 * (`tests/test_disturbance_ratchet.py` + `disturbance/baselines/*.yaml`): a
 * grandfathered baseline of tolerated violations that
 *   - MUST NOT grow — a new occurrence in any migrated file fails the gate, and
 *   - MUST shrink honestly — a baseline entry that no longer matches reality has
 *     to be pruned in the same change (a stale entry fails the gate too), so the
 *     baseline can only ratchet downward and never drifts from the truth.
 *
 * The migrated zone is the whole operator feature dir (`src/operator/**`, tests
 * excluded). Task 12 migrated every operator component onto the token/primitive
 * layer (`src/styles/tokens.js` + `src/styles/primitives.jsx`), so BOTH
 * allow-lists below are empty: the end state is that any inline `style={{…}}`
 * literal or any hardcoded colour literal (hex / rgb / hsl) in operator source
 * fails this test. As new work migrates further panels in later PRs, nothing
 * here needs to change — the ratchet is already at zero for this dir.
 *
 * Note the guard targets inline OBJECT LITERALS (`style={{…}}`) specifically.
 * A `style={someTokenBackedObject}` reference (the idiom the migrated components
 * use for their named, token-driven style objects) is fine — the point is that
 * styling values flow from the token layer, not from anonymous inline literals
 * scattered through the JSX.
 */

import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

// vitest runs with cwd = src/ui (see scripts/run-vitest.cjs).
const OPERATOR_DIR = path.resolve(process.cwd(), 'src/operator')

// ── Grandfather allow-lists — "remove the entry when the file is migrated" ────
// Keyed by path relative to src/operator; value = count of tolerated
// occurrences. Both are intentionally empty: Task 12 migrated the whole dir.
const INLINE_STYLE_ALLOWLIST = Object.freeze({
  // (empty) — every operator component styles via primitives + named
  // token-backed style objects; no inline style={{…}} literals remain.
})
const COLOR_LITERAL_ALLOWLIST = Object.freeze({
  // (empty) — every colour resolves through the token layer (theme cssVars /
  // resolved tokens); no hardcoded hex / rgb / hsl literals remain.
})

// ── Scanners ──────────────────────────────────────────────────────────────

/** Recursively collect operator source files, excluding test dirs. */
function collectSourceFiles(dir) {
  const out = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === '__tests__') continue
      out.push(...collectSourceFiles(full))
    } else if (/\.(jsx?|tsx?)$/.test(entry.name)) {
      out.push(full)
    }
  }
  return out
}

/** Strip line + block comments so comment prose never trips the scanners. */
function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
}

/** Count inline object-literal style props: `style={{` (whitespace-tolerant). */
function countInlineStyles(source) {
  const matches = stripComments(source).match(/style\s*=\s*\{\{/g)
  return matches ? matches.length : 0
}

// A hardcoded colour literal: a 3/4/6/8-digit hex colour, or an rgb()/rgba()/
// hsl()/hsla() function. Word-boundary after the hex so issue refs like
// `#10556` (5 digits) and item ids like `#${id}` never match.
const COLOR_LITERAL_RE = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b|\b(?:rgba?|hsla?)\s*\(/g

/** Count hardcoded colour literals (comments stripped first). */
function countColorLiterals(source) {
  const matches = stripComments(source).match(COLOR_LITERAL_RE)
  return matches ? matches.length : 0
}

// ── Gate helpers — new (grew past baseline) + stale (baseline no longer true) ─

function gate(files, counter, allowlist, kind) {
  const actual = {}
  for (const file of files) {
    const rel = path.relative(OPERATOR_DIR, file)
    const n = counter(fs.readFileSync(file, 'utf8'))
    if (n > 0) actual[rel] = n
  }

  const newViolations = []
  for (const [rel, n] of Object.entries(actual)) {
    const allowed = allowlist[rel] ?? 0
    if (n > allowed) newViolations.push(`${rel}: ${n} ${kind} (baseline ${allowed})`)
  }

  const stale = []
  for (const [rel, allowed] of Object.entries(allowlist)) {
    const n = actual[rel] ?? 0
    if (n < allowed) stale.push(`${rel}: baseline ${allowed} but only ${n} present — prune it`)
  }

  return { actual, newViolations, stale }
}

// ── Tests ────────────────────────────────────────────────────────────────

describe('operator inline-style + colour ratchet (#10556 Task 12)', () => {
  const files = collectSourceFiles(OPERATOR_DIR)

  it('scans a non-trivial number of operator source files', () => {
    // Guards against the scanner silently matching nothing (e.g. a bad path).
    expect(files.length).toBeGreaterThan(10)
  })

  it('has no NEW inline style={{…}} beyond the (empty) grandfather baseline', () => {
    const { newViolations } = gate(files, countInlineStyles, INLINE_STYLE_ALLOWLIST, 'inline style')
    expect(newViolations, `new inline style={{…}} introduced:\n${newViolations.join('\n')}`).toEqual([])
  })

  it('keeps the inline-style baseline honest (prune resolved entries)', () => {
    const { stale } = gate(files, countInlineStyles, INLINE_STYLE_ALLOWLIST, 'inline style')
    expect(stale, `stale inline-style baseline entries:\n${stale.join('\n')}`).toEqual([])
  })

  it('has no NEW hardcoded colour literal beyond the (empty) grandfather baseline', () => {
    const { newViolations } = gate(files, countColorLiterals, COLOR_LITERAL_ALLOWLIST, 'colour literal')
    expect(newViolations, `hardcoded colour literals introduced (route through tokens):\n${newViolations.join('\n')}`).toEqual([])
  })

  it('keeps the colour-literal baseline honest (prune resolved entries)', () => {
    const { stale } = gate(files, countColorLiterals, COLOR_LITERAL_ALLOWLIST, 'colour literal')
    expect(stale, `stale colour-literal baseline entries:\n${stale.join('\n')}`).toEqual([])
  })
})

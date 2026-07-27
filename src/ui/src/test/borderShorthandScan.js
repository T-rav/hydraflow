// Structural guard for the StreamCard-class of style bugs (#10564, #10571,
// #10579, #10583): flag any single inline-style object that declares the CSS
// `border` shorthand alongside a per-side longhand (`borderTop` / `borderRight`
// / `borderBottom` / `borderLeft`).
//
// Why structural (AST) rather than a React dev-warning probe: React's
// `validateShorthandPropertyCollisionInDev` only fires when a key is
// added/removed across a re-render, so a mixed object that is always applied
// whole warns for nobody — until the day it is spread over (or under) another
// style object conditionally, at which point it becomes both a console warning
// and a real visual bug. This scanner catches the co-occurrence at rest, in the
// source, before it can ship. See docs/wiki + issue #10583.
//
// Parser: Vite re-exports the oxc parser as `parseAst`. It is the only
// JSX-capable parser available in this app's node_modules without adding a
// dependency, and must be invoked with `{ lang: 'jsx' }` — the intuitive
// `{ jsx: true }` (and the default options) throw on any JSX expression.
import { parseAst } from 'vite'

const SHORTHAND = 'border'
const SIDE_LONGHANDS = ['borderTop', 'borderRight', 'borderBottom', 'borderLeft']

// Resolve a property's static key name, or null when it cannot be resolved to a
// plain string (computed keys, spreads, numeric literal keys). Handles both
// identifier keys (`border:`) and string-literal keys (`'border':`).
function staticKeyName(prop) {
  if (prop.type !== 'Property' || prop.computed) return null
  const key = prop.key
  if (!key) return null
  if (key.type === 'Identifier') return key.name
  if (key.type === 'Literal' || key.type === 'StringLiteral') {
    return typeof key.value === 'string' ? key.value : null
  }
  return null
}

// oxc's parseAst emits byte offsets (node.start) but no line/column, so derive
// the 1-based line by counting newlines up to the offset.
function lineAtOffset(source, offset) {
  if (typeof offset !== 'number' || offset < 0) return 0
  let line = 1
  for (let i = 0; i < offset && i < source.length; i++) {
    if (source.charCodeAt(i) === 10 /* \n */) line++
  }
  return line
}

// Depth-first walk over every node in the ESTree AST, invoking `visit(node)` on
// each object that has a string `type`. Skips positional metadata so we never
// recurse into non-AST bags.
function walk(node, visit) {
  if (!node || typeof node !== 'object') return
  if (Array.isArray(node)) {
    for (const child of node) walk(child, visit)
    return
  }
  if (typeof node.type === 'string') visit(node)
  for (const key in node) {
    if (key === 'loc' || key === 'range' || key === 'parent' || key === 'start' || key === 'end') continue
    walk(node[key], visit)
  }
}

/**
 * Scan a single source string for inline-style objects that mix the `border`
 * shorthand with a per-side longhand.
 *
 * @param {string} source   Raw JS/JSX source text.
 * @param {string} filename Label used in findings (for the guard's report).
 * @returns {Array<{file: string, line: number, keys: string[], parseError?: string}>}
 *   One finding per offending object literal. A parse failure yields a single
 *   finding with `parseError` set — the scanner fails closed and never silently
 *   skips a file it cannot read.
 */
export function findBorderShorthandCollisions(source, filename = '<anonymous>') {
  let ast
  try {
    ast = parseAst(source, { lang: 'jsx' })
  } catch (err) {
    return [{ file: filename, line: 0, keys: [], parseError: err && err.message ? err.message : String(err) }]
  }

  const findings = []
  walk(ast, node => {
    if (node.type !== 'ObjectExpression') return
    const keys = new Set()
    for (const prop of node.properties) {
      const name = staticKeyName(prop)
      if (name) keys.add(name)
    }
    if (!keys.has(SHORTHAND)) return
    const colliding = SIDE_LONGHANDS.filter(longhand => keys.has(longhand))
    if (colliding.length === 0) return
    findings.push({
      file: filename,
      line: lineAtOffset(source, node.start),
      keys: [SHORTHAND, ...colliding],
    })
  })
  return findings
}

/**
 * LoopsPanel — the operator console's "all loops quick view" (epic #10556
 * follow-up).
 *
 * Pure presentational component. Consumes the `toLoops(...)` view model and
 * renders a compact, scannable readout of every background loop grouped by
 * functional area: a collapsible category header carrying the loop count + an
 * ok/total badge, and under it one row per loop showing a colour-coded status
 * dot, the loop name, a restart badge when it has cycled, and the relevant
 * recent message/error (truncated, click to expand to the full text).
 *
 * The colour-coding is the contract the tests pin: each status dot carries an
 * `ok` | `warn` | `bad` | `muted` severity class, and every colour resolves from
 * the token layer via `useTokens()` — no hardcoded hex — so light + dark fall
 * out of the console's ThemeProvider mode. Presentation only: no socket, no
 * side effects.
 */

import React, { useState } from 'react'
import { useTokens, Card, Text, Badge } from '../styles/primitives'

// Severity -> token colour key (for the status dot) + the `Text` tone that
// renders the value. `muted` reads as an intentionally-off (disabled) loop.
const SEVERITY_COLOR_KEY = { ok: 'green', warn: 'yellow', bad: 'red', muted: 'textInactive' }
const SEVERITY_TEXT_TONE = { ok: 'success', warn: 'warning', bad: 'danger', muted: 'inactive' }

function makeStyles(t) {
  return {
    panel: { display: 'flex', flexDirection: 'column', minWidth: 0, padding: 0, overflow: 'hidden' },
    header: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.sm,
      padding: `${t.space.xs}px ${t.space.sm}px`,
      borderBottom: `1px solid ${t.color.border}`,
    },
    spacer: { flex: '1 1 auto' },
    body: { overflowY: 'auto', overflowX: 'hidden', maxHeight: 360, minHeight: 0 },
    empty: { padding: `${t.space.md}px ${t.space.sm}px`, fontSize: t.type.size.sm, color: t.color.textMuted },
    categoryHeader: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.sm,
      width: '100%',
      boxSizing: 'border-box',
      borderTop: `1px solid ${t.color.border}`,
      borderRight: 'none',
      borderBottom: 'none',
      borderLeft: 'none',
      background: t.color.surfaceInset,
      color: t.color.text,
      cursor: 'pointer',
      font: 'inherit',
      textAlign: 'left',
      padding: `${t.space.xs}px ${t.space.sm}px`,
    },
    caret: { flexShrink: 0, width: 12, color: t.color.textMuted, fontSize: t.type.size.xs },
    row: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      padding: `${t.space.xs}px ${t.space.sm}px ${t.space.xs}px ${t.space.md}px`,
    },
    dot: (severity) => ({
      flexShrink: 0,
      alignSelf: 'center',
      width: 8,
      height: 8,
      borderRadius: t.radius.pill,
      backgroundColor: t.color[SEVERITY_COLOR_KEY[severity]] ?? t.color.textMuted,
    }),
    rowMain: { display: 'flex', flexDirection: 'column', gap: t.space.xxs, minWidth: 0, flex: '1 1 auto' },
    nameLine: { display: 'flex', alignItems: 'baseline', gap: t.space.xs, minWidth: 0 },
    name: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
    term: { flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
    message: (expanded) => ({
      cursor: 'pointer',
      textAlign: 'left',
      border: 'none',
      background: 'transparent',
      padding: 0,
      font: 'inherit',
      color: t.color.textMuted,
      fontSize: t.type.size.xs,
      lineHeight: t.type.leading.tight,
      display: 'block',
      minWidth: 0,
      ...(expanded
        ? { whiteSpace: 'pre-wrap', wordBreak: 'break-word' }
        : { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%' }),
    }),
  }
}

// Per-category collapse state persists across reloads, and categories start
// COLLAPSED — the panel opens compact and the operator expands only the areas
// they care about, with that choice remembered. One JSON map under a single key.
const LOOPS_OPEN_KEY = 'hydraflow-operator-loops-open'

function readLoopsOpenState() {
  if (typeof window === 'undefined' || !window.localStorage) return {}
  try {
    const raw = window.localStorage.getItem(LOOPS_OPEN_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function persistLoopsOpenState(key, open) {
  if (typeof window === 'undefined' || !window.localStorage) return
  try {
    const map = readLoopsOpenState()
    map[key] = open
    window.localStorage.setItem(LOOPS_OPEN_KEY, JSON.stringify(map))
  } catch {
    // Ignore persistence failures (private mode / quota) — collapse still works
    // for the session, it just won't be remembered.
  }
}

/** The message an operator most needs: the live error when bad, else the last stats line. */
function relevantMessage(loop) {
  if (loop.severity === 'bad' && loop.lastError) return loop.lastError
  return loop.lastMessage || loop.lastError || null
}

/**
 * One loop row: status dot + name (+ restart badge) + the relevant recent
 * message, truncated and click-to-expand.
 * @param {{ loop: object, styles: object }} props
 */
function LoopRow({ loop, styles }) {
  const [expanded, setExpanded] = useState(false)
  const message = relevantMessage(loop)
  return (
    <div data-testid={`loop-row-${loop.id}`} style={styles.row}>
      <span
        data-testid={`loop-status-${loop.id}`}
        className={`loop-status ${loop.severity}`}
        style={styles.dot(loop.severity)}
        aria-label={`status ${loop.severity}`}
      />
      <div style={styles.rowMain}>
        <div style={styles.nameLine}>
          <Text as="span" size="sm" tone={loop.enabled ? 'default' : 'inactive'} style={styles.name}>
            {loop.name}
          </Text>
          {loop.term && (
            <Text
              as="span"
              size="xs"
              tone="muted"
              data-testid={`loop-term-${loop.id}`}
              style={styles.term}
            >
              {loop.term}
            </Text>
          )}
          {loop.restarts > 0 && (
            <Badge tone="warning" data-testid={`loop-restarts-${loop.id}`}>{`↻${loop.restarts}`}</Badge>
          )}
          {!loop.enabled && <Badge tone="neutral">off</Badge>}
        </div>
        {message ? (
          <button
            type="button"
            data-testid={`loop-message-${loop.id}`}
            aria-expanded={expanded}
            onClick={() => setExpanded(v => !v)}
            style={styles.message(expanded)}
            title="Click to expand"
          >
            {message}
          </button>
        ) : null}
      </div>
    </div>
  )
}

/**
 * One collapsible category: header (name + count + ok/total) then its loop rows.
 * @param {{ category: object, styles: object }} props
 */
function LoopCategory({ category, styles }) {
  // Start collapsed; restore a remembered open state if the operator expanded
  // this category before (persisted per category key across reloads).
  const [open, setOpen] = useState(() => readLoopsOpenState()[category.key] === true)
  const allOk = category.ok === category.count
  const toggle = () => setOpen(prev => {
    const next = !prev
    persistLoopsOpenState(category.key, next)
    return next
  })
  return (
    <div data-testid={`loops-category-${category.key}`}>
      <button
        type="button"
        data-testid={`loops-category-toggle-${category.key}`}
        aria-expanded={open}
        onClick={toggle}
        style={styles.categoryHeader}
      >
        <span style={styles.caret} aria-hidden="true">{open ? '▾' : '▸'}</span>
        <Text as="span" size="xs" weight="semibold" uppercase>{category.name}</Text>
        <span style={styles.spacer} />
        <Badge tone="neutral">{category.count}</Badge>
        <Badge tone={allOk ? 'success' : 'warning'}>{`${category.ok}/${category.count}`}</Badge>
      </button>
      {open && category.loops.map(loop => (
        <LoopRow key={loop.id} loop={loop} styles={styles} />
      ))}
    </div>
  )
}

/**
 * @param {{ loops?: { categories: Array, totals: object } }} props
 */
export function LoopsPanel({ loops }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const categories = loops?.categories ?? []
  const totals = loops?.totals ?? { ok: 0, total: 0, restarted: 0, disabled: 0 }
  const allOk = totals.ok === totals.total

  return (
    <Card as="section" data-testid="loops-panel" style={styles.panel} aria-label="Background loops">
      <div style={styles.header}>
        <Text size="xs" weight="semibold" tone="muted" uppercase>Loops</Text>
        <span style={styles.spacer} />
        {totals.restarted > 0 && (
          <Badge tone="warning" data-testid="loops-restarted">{`↻${totals.restarted}`}</Badge>
        )}
        <Badge tone={allOk ? 'success' : 'warning'} data-testid="loops-health">
          {`${totals.ok}/${totals.total}`}
        </Badge>
      </div>
      <div style={styles.body}>
        {categories.length === 0 ? (
          <div data-testid="loops-empty" style={styles.empty}>No loops reported yet.</div>
        ) : (
          categories.map(category => (
            <LoopCategory key={category.key} category={category} styles={styles} />
          ))
        )}
      </div>
    </Card>
  )
}

export default LoopsPanel

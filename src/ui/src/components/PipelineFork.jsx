import React from 'react'

/**
 * Shared pipeline fork visuals for the Header pipeline row and StreamView's
 * PipelineFlow (#9564). Both components render the SAME fork topology — the
 * hitl/merged terminal fork off REVIEW — so it can no longer drift between the
 * two.
 *
 * Only the topology + arrows live here. Each caller keeps its OWN sizing and
 * compactness by passing a `styles` bundle plus render-props for the per-stage
 * body (compact pills in Header, larger flow stages in StreamView). The
 * `styles` bundle maps the canonical fork-slot names to the caller's own
 * styles:
 *   - fork:       the vertical fork container
 *   - forkTop:    a top/branch row (terminal arm)
 *   - forkArrow:  the diagonal branch arrow (↗ / ↘)
 */

/**
 * Terminal fork off REVIEW: each end-state (hitl, merged) is a parallel arm —
 * the first takes the ↗ arrow, the rest take ↘ — because after REVIEW an issue
 * goes to a human OR gets merged, never both. Renders nothing when there are no
 * terminal stages.
 *
 * @param {Array} items  Terminal items, in pipeline order (hitl before merged).
 * @param {(item:any)=>string} keyOf  Maps an item to its React key / stage key.
 * @param {(item:any)=>React.ReactNode} renderItem  Renders one stage body.
 * @param {object} styles  Canonical fork-slot → caller-style map (see above).
 * @param {string} [testId]  data-testid for the fork container.
 */
export function TerminalFork({ items, keyOf = (i) => i.key, renderItem, styles, testId }) {
  if (!items || items.length === 0) return null
  return (
    <span style={styles.fork} data-testid={testId}>
      {items.map((item, idx) => (
        <span style={styles.forkTop} key={keyOf(item)}>
          <span style={styles.forkArrow}>{idx === 0 ? '↗' : '↘'}</span>
          {renderItem(item)}
        </span>
      ))}
    </span>
  )
}

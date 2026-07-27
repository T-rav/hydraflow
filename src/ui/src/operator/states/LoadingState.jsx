/**
 * LoadingState — the operator console's first-paint skeleton (epic #10556,
 * Task 10).
 *
 * Shown on the very first load, before the socket has connected and any data
 * has arrived. It mirrors the console's grid geometry (header / pipeline /
 * detail / vitals / drawer) with neutral skeleton blocks so that when real data
 * lands the layout does NOT jump — the grid areas and their footprints are
 * already in place. No spinner, no changing copy.
 */

import React from 'react'
import { theme } from '../../theme'

const shimmer = {
  background: theme.surfaceInset,
  border: `1px solid ${theme.border}`,
  borderRadius: 8,
  opacity: 0.6,
}

const styles = {
  grid: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) 280px',
    gridTemplateAreas: '"header header" "pipeline vitals" "detail vitals" "drawer drawer"',
    gap: 12,
    padding: 12,
    boxSizing: 'border-box',
    flex: 1,
    minHeight: 0,
  },
  header: { gridArea: 'header', height: 48, ...shimmer },
  pipeline: { gridArea: 'pipeline', height: 120, ...shimmer },
  detail: { gridArea: 'detail', minHeight: 220, ...shimmer },
  vitals: { gridArea: 'vitals', minHeight: 340, ...shimmer },
  drawer: { gridArea: 'drawer', height: 56, ...shimmer },
}

export function LoadingState() {
  return (
    <div data-testid="operator-loading-state" role="status" aria-busy="true" aria-live="polite" style={styles.grid}>
      <span className="sr-only" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
        Loading operator console…
      </span>
      <div data-testid="operator-skeleton" style={styles.header} />
      <div data-testid="operator-skeleton" style={styles.pipeline} />
      <div data-testid="operator-skeleton" style={styles.detail} />
      <div data-testid="operator-skeleton" style={styles.vitals} />
      <div data-testid="operator-skeleton" style={styles.drawer} />
    </div>
  )
}

export default LoadingState

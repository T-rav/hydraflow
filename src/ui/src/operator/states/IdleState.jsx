/**
 * IdleState — the operator console's calm idle/empty screen (epic #10556, Task 10).
 *
 * Shown when a repo has no active pipeline work. Deliberately *calm*: it does
 * NOT nag with "Waiting for issues…" — an idle factory is a healthy resting
 * state, not an error. It reassures the operator that everything is caught up
 * and the console is live and watching.
 *
 * Pure and prop-free; the console decides when to render it.
 */

import React from 'react'
import { theme } from '../../theme'

const styles = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    minHeight: 220,
    padding: 32,
    border: `1px dashed ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    textAlign: 'center',
    boxSizing: 'border-box',
  },
  glyph: {
    width: 40,
    height: 40,
    borderRadius: '50%',
    border: `2px solid ${theme.green}`,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: theme.green,
    fontSize: 18,
    fontWeight: 700,
  },
  title: {
    fontSize: 15,
    fontWeight: 700,
    color: theme.textBright,
  },
  sub: {
    fontSize: 12,
    color: theme.textMuted,
    maxWidth: 340,
    lineHeight: 1.5,
  },
}

export function IdleState() {
  return (
    <div data-testid="operator-idle-state" role="status" style={styles.wrap}>
      <span aria-hidden="true" style={styles.glyph}>✓</span>
      <span style={styles.title}>All caught up</span>
      <span style={styles.sub}>
        No active work in this pipeline right now. The console is live — new
        issues will appear here as the factory picks them up.
      </span>
    </div>
  )
}

export default IdleState

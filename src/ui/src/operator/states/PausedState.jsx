/**
 * PausedState — the operator console's paused banner (epic #10556, Task 10).
 *
 * Shown when the factory is paused (currently: credits exhausted). It surfaces
 * the *reason* the operator most needs — why work stopped and until when — plus
 * the provider that ran out, and a single Resume control that force-clears the
 * pause (the existing `clearCreditPause` control, threaded in as `onResume`).
 *
 * Rendered non-blocking (a top strip) so the last-known board stays visible
 * underneath — a credit pause leaves the orchestrator up, so the pipeline view
 * is still meaningful.
 *
 * Prop-driven; no endpoint logic is reinvented here.
 */

import React from 'react'
import { theme } from '../../theme'

const styles = {
  banner: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '8px 14px',
    background: theme.orangeSubtle,
    border: `1px solid ${theme.orange}`,
    borderRadius: 8,
    color: theme.orange,
    fontSize: 13,
    fontWeight: 600,
    boxSizing: 'border-box',
  },
  icon: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 20,
    height: 20,
    borderRadius: '50%',
    background: theme.orange,
    color: theme.white,
    fontSize: 12,
    fontWeight: 700,
    flexShrink: 0,
  },
  label: {
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    fontSize: 11,
    flexShrink: 0,
  },
  reason: {
    fontWeight: 600,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  provider: {
    fontWeight: 400,
    opacity: 0.85,
  },
  resume: {
    marginLeft: 'auto',
    flexShrink: 0,
    padding: '4px 14px',
    borderRadius: 6,
    border: `1px solid ${theme.orange}`,
    background: 'transparent',
    color: theme.orange,
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
  },
}

/**
 * @param {{
 *   reason?: string,       // vitals.factory.reason (e.g. "credits paused until …")
 *   provider?: string,     // vitals.credits.provider — which backend ran out
 *   onResume?: () => void,  // socket.clearCreditPause — force-clear the pause
 * }} props
 */
export function PausedState({ reason, provider, onResume }) {
  return (
    <div data-testid="operator-paused-state" role="status" style={styles.banner}>
      <span aria-hidden="true" style={styles.icon}>!</span>
      <span style={styles.label}>Paused</span>
      <span style={styles.reason}>
        {reason || 'Factory paused.'}
        {provider ? <span style={styles.provider}> ({provider})</span> : null}
      </span>
      <button
        type="button"
        data-testid="operator-paused-resume"
        style={styles.resume}
        onClick={() => onResume?.()}
      >
        Resume
      </button>
    </div>
  )
}

export default PausedState

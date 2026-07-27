/**
 * DisconnectedBanner — the operator console's non-blocking offline strip
 * (epic #10556, Task 10).
 *
 * When the WebSocket drops, the console keeps rendering the last-known state
 * (see OperatorConsole) and slides this banner in on top. It is deliberately
 * NON-blocking: it never replaces content, so the operator keeps reading the
 * stale-but-useful board while the context's exponential-backoff reconnect runs
 * in the background.
 *
 * An optional `onRetry` renders a manual retry affordance; when omitted the
 * banner is purely informational (the socket reconnects on its own).
 */

import React from 'react'
import { theme } from '../../theme'

const styles = {
  banner: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '7px 14px',
    background: theme.yellowSubtle,
    borderBottom: `1px solid ${theme.yellow}`,
    color: theme.yellow,
    fontSize: 12,
    fontWeight: 600,
    boxSizing: 'border-box',
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.yellow,
    flexShrink: 0,
  },
  hint: {
    fontWeight: 400,
    opacity: 0.85,
  },
  retry: {
    marginLeft: 'auto',
    flexShrink: 0,
    padding: '3px 12px',
    borderRadius: 6,
    border: `1px solid ${theme.yellow}`,
    background: 'transparent',
    color: theme.yellow,
    fontSize: 11,
    fontWeight: 700,
    cursor: 'pointer',
  },
}

/**
 * @param {{ onRetry?: () => void }} props
 */
export function DisconnectedBanner({ onRetry }) {
  return (
    <div data-testid="operator-disconnected-banner" role="status" aria-live="polite" style={styles.banner}>
      <span aria-hidden="true" style={styles.dot} />
      <span>Connection lost.</span>
      <span style={styles.hint}>Reconnecting… showing the last known state.</span>
      {onRetry && (
        <button
          type="button"
          data-testid="operator-disconnected-retry"
          style={styles.retry}
          onClick={() => onRetry()}
        >
          Retry now
        </button>
      )}
    </div>
  )
}

export default DisconnectedBanner

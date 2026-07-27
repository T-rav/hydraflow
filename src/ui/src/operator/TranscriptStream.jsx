/**
 * TranscriptStream — the operator console's per-item formatted live transcript
 * (epic #10556, Task 4). Replaces today's raw `transcript line#…` wall with a
 * readable, colour-coded stream.
 *
 * It consumes the already-formatted rows produced by `toTranscript(...)`
 * (Task 1) — each row is `{ ts, kind, text, meta }`, kind ∈
 * read|edit|run|pass|fail|agent — and renders:
 *   - one formatted row per entry (via StreamView's shared `TranscriptRow`, so
 *     there is a single row implementation across the dashboard),
 *   - a live indicator when the focused item is active (its transcript is
 *     streaming), and
 *   - a "raw" escape-hatch toggle that swaps the formatted rows for the
 *     unparsed line text — the safety valve for when the formatter hides
 *     something the operator needs to see.
 *
 * The stream auto-scrolls to the newest row as rows arrive. Presentation only —
 * no socket, no side effects; styling uses the shared `theme` CSS-variable
 * references so the dark/light paths keep working.
 */

import React, { useEffect, useRef, useState } from 'react'
import { theme } from '../theme'
import { PULSE_ANIMATION } from '../constants'
import { TranscriptRow } from '../components/StreamView'

const styles = {
  stream: {
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    overflow: 'hidden',
  },
  bar: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '4px 8px',
    borderBottom: `1px solid ${theme.border}`,
  },
  live: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    flexShrink: 0,
    fontSize: 9,
    fontWeight: 700,
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: theme.green,
  },
  liveDot: {
    display: 'inline-block',
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: theme.green,
    animation: PULSE_ANIMATION,
  },
  spacer: {
    flex: '1 1 auto',
  },
  rawToggle: {
    flexShrink: 0,
    border: `1px solid ${theme.border}`,
    borderRadius: 10,
    background: theme.surfaceInset,
    color: theme.textMuted,
    cursor: 'pointer',
    padding: '1px 8px',
    font: 'inherit',
    fontSize: 10,
    fontWeight: 600,
    lineHeight: 1.6,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  rawToggleOn: {
    background: theme.accent,
    color: theme.bg,
    borderColor: theme.accent,
  },
  body: {
    overflowY: 'auto',
    overflowX: 'hidden',
    padding: '6px 8px',
    maxHeight: 360,
    minHeight: 0,
  },
  rawLine: {
    fontFamily: 'monospace',
    fontSize: 10,
    color: theme.textMuted,
    lineHeight: 1.5,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
    padding: '1px 0',
  },
  empty: {
    padding: '10px 2px',
    fontSize: 12,
    color: theme.textMuted,
  },
}

/**
 * @param {{
 *   rows?: Array<{ts, kind, text, meta}>,
 *   active?: boolean,
 * }} props
 */
export function TranscriptStream({ rows = [], active = false }) {
  const [raw, setRaw] = useState(false)
  const scrollRef = useRef(null)

  // Follow the tail: keep the newest row in view as rows append (harmless in
  // jsdom, which has no layout — scrollHeight is 0).
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [rows, raw])

  const hasRows = rows.length > 0

  return (
    <div data-testid="transcript-stream" style={styles.stream}>
      <div style={styles.bar}>
        {active && (
          <span data-testid="transcript-live" style={styles.live}>
            <span style={styles.liveDot} aria-hidden="true" />
            Live
          </span>
        )}
        <span style={styles.spacer} />
        <button
          type="button"
          data-testid="transcript-raw-toggle"
          aria-pressed={raw}
          onClick={() => setRaw(v => !v)}
          style={{ ...styles.rawToggle, ...(raw ? styles.rawToggleOn : null) }}
          title="Show the unparsed transcript lines"
        >
          raw
        </button>
      </div>

      <div ref={scrollRef} style={styles.body} data-sensitive="true">
        {!hasRows ? (
          <div data-testid="transcript-empty" style={styles.empty}>
            No transcript yet.
          </div>
        ) : raw ? (
          rows.map((r, i) => (
            <div key={i} data-testid="transcript-raw-line" style={styles.rawLine}>
              {r.text}
            </div>
          ))
        ) : (
          rows.map((r, i) => <TranscriptRow key={i} row={r} />)
        )}
      </div>
    </div>
  )
}

export default TranscriptStream

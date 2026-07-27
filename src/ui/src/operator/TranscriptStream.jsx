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
 * no socket, no side effects. Phase-2 (Task 12): the container uses the `Card`
 * primitive and every colour / space value resolves from `useTokens()`, so
 * light + dark fall out of the console's ThemeProvider mode.
 */

import React, { useEffect, useRef, useState } from 'react'
import { useTokens, Card } from '../styles/primitives'
import { PULSE_ANIMATION } from '../constants'
import { TranscriptRow } from '../components/StreamView'

function makeStyles(t) {
  return {
    stream: {
      display: 'flex',
      flexDirection: 'column',
      minWidth: 0,
      padding: 0,
      overflow: 'hidden',
    },
    bar: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.sm,
      padding: `${t.space.xs}px ${t.space.sm}px`,
      borderBottom: `1px solid ${t.color.border}`,
    },
    live: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: t.space.xs,
      flexShrink: 0,
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.bold,
      letterSpacing: t.type.tracking.wide,
      textTransform: 'uppercase',
      color: t.color.green,
    },
    liveDot: {
      display: 'inline-block',
      width: 6,
      height: 6,
      borderRadius: t.radius.pill,
      background: t.color.green,
      animation: PULSE_ANIMATION,
    },
    spacer: { flex: '1 1 auto' },
    rawToggle: (on) => ({
      flexShrink: 0,
      border: `1px solid ${on ? t.color.accent : t.color.border}`,
      borderRadius: t.radius.lg,
      background: on ? t.color.accent : t.color.surfaceInset,
      color: on ? t.color.bg : t.color.textMuted,
      cursor: 'pointer',
      padding: `1px ${t.space.sm}px`,
      font: 'inherit',
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.semibold,
      lineHeight: 1.6,
      textTransform: 'uppercase',
      letterSpacing: t.type.tracking.wide,
    }),
    body: {
      overflowY: 'auto',
      overflowX: 'hidden',
      padding: `${t.space.xs}px ${t.space.sm}px`,
      maxHeight: 360,
      minHeight: 0,
    },
    rawLine: {
      fontFamily: t.type.family.mono,
      fontSize: t.type.size.xs,
      color: t.color.textMuted,
      lineHeight: 1.5,
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-all',
      padding: '1px 0',
    },
    empty: {
      padding: `${t.space.md}px ${t.space.xxs}px`,
      fontSize: t.type.size.sm,
      color: t.color.textMuted,
    },
  }
}

/**
 * @param {{
 *   rows?: Array<{ts, kind, text, meta}>,
 *   active?: boolean,
 * }} props
 */
export function TranscriptStream({ rows = [], active = false }) {
  const t = useTokens()
  const styles = makeStyles(t)
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
    <Card as="div" data-testid="transcript-stream" style={styles.stream}>
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
          style={styles.rawToggle(raw)}
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
    </Card>
  )
}

export default TranscriptStream

/**
 * ItemWorkspace — the operator console's detail slot (epic #10556, Task 4).
 *
 * A tabbed workspace over the selected item's transcript view model
 * (`toTranscript(...)`, Task 1):
 *   - Transcript (default): the formatted live `TranscriptStream`.
 *   - Diff: the item's file-edit rows (kind === 'edit') — the closest to a diff
 *     the existing event stream carries without a backend change.
 *   - PR: the item's PR number when the transcript rows carry one, else a calm
 *     empty state.
 *   - Timeline: the transcript folded into compact per-kind phases via
 *     `toTimelineRows(...)` (a shared, additive `useTimeline` export).
 *
 * It replaces the last shell placeholder (`ItemWorkspacePlaceholder`) and
 * consumes exactly the props the placeholder did (`item`, `transcript`, `mode`;
 * `select` is threaded by the shell but not yet needed here). The transcript is
 * treated as live whenever an item is selected.
 *
 * Regression contract (#10556): a missing item id must NEVER render as a
 * `#undefined` header — the header is only drawn when `item` is truthy.
 *
 * Presentation only — no socket, no side effects; styling uses the shared
 * `theme` CSS-variable references so the dark/light paths keep working.
 */

import React, { useMemo, useState } from 'react'
import { theme } from '../theme'
import { TranscriptStream } from './TranscriptStream'
import { toTimelineRows } from '../hooks/useTimeline'
import { formatTranscriptTs } from '../components/StreamView'

const TABS = [
  { key: 'transcript', label: 'Transcript' },
  { key: 'diff', label: 'Diff' },
  { key: 'pr', label: 'PR' },
  { key: 'timeline', label: 'Timeline' },
]

const styles = {
  workspace: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    minWidth: 0,
  },
  head: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 8,
    minWidth: 0,
  },
  title: {
    fontSize: 14,
    fontWeight: 700,
    color: theme.textBright,
    fontVariantNumeric: 'tabular-nums',
    flexShrink: 0,
  },
  titleMuted: {
    fontSize: 12,
    color: theme.textMuted,
    flexShrink: 0,
  },
  mode: {
    fontSize: 9,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    color: theme.textMuted,
    marginLeft: 'auto',
    flexShrink: 0,
  },
  tabs: {
    display: 'flex',
    gap: 4,
    minWidth: 0,
    overflowX: 'auto',
  },
  tab: {
    flexShrink: 0,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    background: theme.surfaceInset,
    color: theme.textMuted,
    cursor: 'pointer',
    padding: '3px 10px',
    font: 'inherit',
    fontSize: 11,
    fontWeight: 600,
  },
  tabActive: {
    background: theme.accent,
    color: theme.bg,
    borderColor: theme.accent,
  },
  panel: {
    minWidth: 0,
  },
  tabPanel: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    padding: '8px 10px',
    fontSize: 12,
    color: theme.text,
    minWidth: 0,
    maxHeight: 360,
    overflowY: 'auto',
  },
  empty: {
    fontSize: 12,
    color: theme.textMuted,
  },
  diffRow: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 8,
    padding: '1px 0',
    minWidth: 0,
  },
  diffTs: {
    flexShrink: 0,
    fontFamily: 'monospace',
    fontSize: 10,
    color: theme.textMuted,
    fontVariantNumeric: 'tabular-nums',
  },
  diffText: {
    flex: '1 1 auto',
    minWidth: 0,
    color: theme.cyan,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  timelineRow: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 8,
    padding: '2px 0',
    minWidth: 0,
  },
  timelineTs: {
    flexShrink: 0,
    fontFamily: 'monospace',
    fontSize: 10,
    color: theme.textMuted,
    fontVariantNumeric: 'tabular-nums',
  },
  timelineKind: {
    flexShrink: 0,
    width: 40,
    fontSize: 9,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    color: theme.text,
  },
  timelineCount: {
    flexShrink: 0,
    borderRadius: 8,
    background: theme.surfaceInset,
    color: theme.textMuted,
    padding: '0 6px',
    fontSize: 10,
    fontWeight: 700,
    fontVariantNumeric: 'tabular-nums',
  },
  timelineText: {
    flex: '1 1 auto',
    minWidth: 0,
    color: theme.textMuted,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
}

/**
 * @param {{
 *   item?: string|number|null,
 *   transcript?: Array<{ts, kind, text, meta}>,
 *   mode?: string,
 *   active?: boolean,   // optional override; defaults to "an item is selected"
 * }} props
 */
export function ItemWorkspace({ item = null, transcript = [], mode = 'focus', active }) {
  const [tab, setTab] = useState('transcript')

  // The transcript is live when a specific item is focused; an explicit prop
  // (used by the Task-5 all-active grid) may override this.
  const isActive = active === undefined ? Boolean(item) : active

  const editRows = useMemo(
    () => (transcript || []).filter(r => r.kind === 'edit'),
    [transcript],
  )
  const prNumber = useMemo(() => {
    for (const r of transcript || []) {
      const pr = r?.meta?.pr
      if (pr != null) return pr
    }
    return null
  }, [transcript])
  const timeline = useMemo(() => toTimelineRows(transcript || []), [transcript])

  return (
    <div data-testid="item-workspace" style={styles.workspace}>
      <div style={styles.head}>
        {/* Guard the #undefined regression: only render the id header when an
            item is actually selected (#10556). */}
        {item != null && item !== '' ? (
          <span data-testid="item-workspace-header" style={styles.title}>
            #{item}
          </span>
        ) : (
          <span style={styles.titleMuted}>No item selected</span>
        )}
        <span style={styles.mode}>{mode}</span>
      </div>

      <div role="tablist" aria-label="Item workspace" style={styles.tabs}>
        {TABS.map(t => (
          <button
            key={t.key}
            type="button"
            role="tab"
            data-testid={`workspace-tab-${t.key}`}
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            style={{ ...styles.tab, ...(tab === t.key ? styles.tabActive : null) }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={styles.panel}>
        {tab === 'transcript' && (
          <TranscriptStream rows={transcript || []} active={isActive} />
        )}

        {tab === 'diff' && (
          <div data-testid="workspace-diff" style={styles.tabPanel}>
            {editRows.length === 0 ? (
              <div style={styles.empty}>No file edits yet.</div>
            ) : (
              editRows.map((r, i) => (
                <div key={i} data-testid="diff-row" style={styles.diffRow}>
                  <span style={styles.diffTs}>{formatTranscriptTs(r.ts)}</span>
                  <span style={styles.diffText}>{r.text}</span>
                </div>
              ))
            )}
          </div>
        )}

        {tab === 'pr' && (
          <div data-testid="workspace-pr" style={styles.tabPanel}>
            {prNumber != null ? `PR #${prNumber}` : 'No PR yet.'}
          </div>
        )}

        {tab === 'timeline' && (
          <div data-testid="workspace-timeline" style={styles.tabPanel}>
            {timeline.length === 0 ? (
              <div style={styles.empty}>No activity yet.</div>
            ) : (
              timeline.map((p, i) => (
                <div key={i} data-testid="timeline-row" data-kind={p.kind} style={styles.timelineRow}>
                  <span style={styles.timelineTs}>{formatTranscriptTs(p.firstTs)}</span>
                  <span style={styles.timelineKind}>{p.kind}</span>
                  {p.count > 1 && <span style={styles.timelineCount}>×{p.count}</span>}
                  <span style={styles.timelineText}>{p.lastText}</span>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default ItemWorkspace

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
 * Presentation only — no socket, no side effects. Phase-2 (Task 12): the tab
 * panels use the `Card` primitive and every colour / space value resolves from
 * `useTokens()`, so light + dark fall out of the console's ThemeProvider mode.
 */

import React, { useMemo, useState } from 'react'
import { useTokens, Card, Text } from '../styles/primitives'
import { TranscriptStream } from './TranscriptStream'
import { toTimelineRows } from '../hooks/useTimeline'
import { formatTranscriptTs } from '../components/StreamView'

const TABS = [
  { key: 'transcript', label: 'Transcript' },
  { key: 'diff', label: 'Diff' },
  { key: 'pr', label: 'PR' },
  { key: 'timeline', label: 'Timeline' },
]

function makeStyles(t) {
  return {
    workspace: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.sm,
      minWidth: 0,
    },
    head: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      minWidth: 0,
    },
    title: { flexShrink: 0 },
    mode: { marginLeft: 'auto', flexShrink: 0, letterSpacing: t.type.tracking.wide },
    tabs: {
      display: 'flex',
      gap: t.space.xs,
      minWidth: 0,
      overflowX: 'auto',
    },
    tab: (active) => ({
      flexShrink: 0,
      border: `1px solid ${active ? t.color.accent : t.color.border}`,
      borderRadius: t.radius.md,
      background: active ? t.color.accent : t.color.surfaceInset,
      color: active ? t.color.bg : t.color.textMuted,
      cursor: 'pointer',
      padding: `${t.space.xxs}px ${t.space.md}px`,
      font: 'inherit',
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.semibold,
    }),
    panel: { minWidth: 0 },
    tabPanel: {
      padding: `${t.space.sm}px ${t.space.md}px`,
      fontSize: t.type.size.sm,
      color: t.color.text,
      minWidth: 0,
      maxHeight: 360,
      overflowY: 'auto',
    },
    diffRow: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      padding: '1px 0',
      minWidth: 0,
    },
    diffTs: {
      flexShrink: 0,
      fontFamily: t.type.family.mono,
      fontSize: t.type.size.xs,
      color: t.color.textMuted,
      fontVariantNumeric: 'tabular-nums',
    },
    diffText: {
      flex: '1 1 auto',
      minWidth: 0,
      color: t.color.cyan,
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
    },
    timelineRow: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      padding: '2px 0',
      minWidth: 0,
    },
    timelineTs: {
      flexShrink: 0,
      fontFamily: t.type.family.mono,
      fontSize: t.type.size.xs,
      color: t.color.textMuted,
      fontVariantNumeric: 'tabular-nums',
    },
    timelineKind: {
      flexShrink: 0,
      width: 40,
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.bold,
      textTransform: 'uppercase',
      letterSpacing: t.type.tracking.wide,
      color: t.color.text,
    },
    timelineCount: {
      flexShrink: 0,
      borderRadius: t.radius.lg,
      background: t.color.surfaceInset,
      color: t.color.textMuted,
      padding: `0 ${t.space.xs}px`,
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.bold,
      fontVariantNumeric: 'tabular-nums',
    },
    timelineText: {
      flex: '1 1 auto',
      minWidth: 0,
      color: t.color.textMuted,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
    },
  }
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
  const t = useTokens()
  const styles = makeStyles(t)
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
          <Text as="span" size="lg" weight="bold" tone="bright" data-testid="item-workspace-header" style={styles.title}>
            #{item}
          </Text>
        ) : (
          <Text as="span" size="sm" tone="muted" style={styles.title}>No item selected</Text>
        )}
        <Text as="span" size="xs" weight="semibold" tone="muted" uppercase style={styles.mode}>{mode}</Text>
      </div>

      <div role="tablist" aria-label="Item workspace" style={styles.tabs}>
        {TABS.map(tabDef => (
          <button
            key={tabDef.key}
            type="button"
            role="tab"
            data-testid={`workspace-tab-${tabDef.key}`}
            aria-selected={tab === tabDef.key}
            onClick={() => setTab(tabDef.key)}
            style={styles.tab(tab === tabDef.key)}
          >
            {tabDef.label}
          </button>
        ))}
      </div>

      <div style={styles.panel}>
        {tab === 'transcript' && (
          <TranscriptStream rows={transcript || []} active={isActive} />
        )}

        {tab === 'diff' && (
          <Card as="div" data-testid="workspace-diff" style={styles.tabPanel}>
            {editRows.length === 0 ? (
              <Text as="div" size="sm" tone="muted">No file edits yet.</Text>
            ) : (
              editRows.map((r, i) => (
                <div key={i} data-testid="diff-row" style={styles.diffRow}>
                  <span style={styles.diffTs}>{formatTranscriptTs(r.ts)}</span>
                  <span style={styles.diffText}>{r.text}</span>
                </div>
              ))
            )}
          </Card>
        )}

        {tab === 'pr' && (
          <Card as="div" data-testid="workspace-pr" style={styles.tabPanel}>
            {prNumber != null ? `PR #${prNumber}` : 'No PR yet.'}
          </Card>
        )}

        {tab === 'timeline' && (
          <Card as="div" data-testid="workspace-timeline" style={styles.tabPanel}>
            {timeline.length === 0 ? (
              <Text as="div" size="sm" tone="muted">No activity yet.</Text>
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
          </Card>
        )}
      </div>
    </div>
  )
}

export default ItemWorkspace

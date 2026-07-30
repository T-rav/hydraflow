/**
 * TimelinePanel — the operator console's phase-container timeline
 * (feat/operator-timeline).
 *
 * Pure presentational component. Consumes the `toTimeline(...)` view model and
 * renders a VERTICAL timeline: one collapsible phase-container card per entry, in
 * chronological order, each hung off a stage-coloured rail node. A container's
 * header shows the phase label, the issue it belongs to, and how long the phase
 * ran (or has been running); expanding it reveals that phase's event bullets and
 * any PR/commit "diff" rows folded inside it. This replaces the old flat
 * scrolling event view.
 *
 * The rail node colour is the contract the tests pin: each node resolves its
 * classic-palette identity colour through `stageColorKey(phase)` + `useTokens()`
 * — the SAME mapping the pipeline rail uses — so triage/plan/build/review can
 * never drift in colour, and light + dark fall out of the console's
 * ThemeProvider mode. No hardcoded hex; every colour / space value comes from the
 * token layer. Presentation only: no socket, no side effects.
 *
 * Diff rows DEGRADE GRACEFULLY to whatever the event stream actually carries — a
 * PR number (linked when a url is present), a short commit sha, and a `+add −del`
 * / file-change count when those fields exist. The stream carries none of the
 * file-level detail today, so nothing is invented: a diff row with only a PR
 * number renders exactly that.
 */

import React, { useState } from 'react'
import { useTokens, Card, Text, Badge } from '../styles/primitives'
import { stageColorKey } from './model/pipeline'

// Per-entry collapse state persists across reloads (guarded localStorage), reusing
// the LoopsPanel idiom. Containers default OPEN — the timeline is meant to be read
// — and the operator's explicit collapses are what get remembered.
const TIMELINE_OPEN_KEY = 'hydraflow-operator-timeline-open'

function readOpenState() {
  if (typeof window === 'undefined' || !window.localStorage) return {}
  try {
    const raw = window.localStorage.getItem(TIMELINE_OPEN_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function persistOpenState(id, open) {
  if (typeof window === 'undefined' || !window.localStorage) return
  try {
    const map = readOpenState()
    map[id] = open
    window.localStorage.setItem(TIMELINE_OPEN_KEY, JSON.stringify(map))
  } catch {
    // Ignore persistence failures (private mode / quota) — collapse still works
    // for the session, it just won't be remembered.
  }
}

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
    body: { overflowY: 'auto', overflowX: 'hidden', maxHeight: 420, minHeight: 0, padding: `${t.space.sm}px 0` },
    empty: { padding: `${t.space.md}px ${t.space.sm}px`, fontSize: t.type.size.sm, color: t.color.textMuted },
    // One entry = a rail column (node + connecting line) beside the content.
    entry: {
      display: 'grid',
      gridTemplateColumns: '18px minmax(0, 1fr)',
      gap: t.space.sm,
      padding: `0 ${t.space.sm}px`,
      minWidth: 0,
    },
    rail: { display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 0 },
    node: (phase) => ({
      flexShrink: 0,
      width: 11,
      height: 11,
      marginTop: 3,
      borderRadius: t.radius.pill,
      background: t.color[stageColorKey(phase)] ?? t.color.textMuted,
      boxShadow: t.shadow.sm,
    }),
    line: { flex: '1 1 auto', width: 2, marginTop: t.space.xxs, background: t.color.border },
    content: { minWidth: 0, paddingBottom: t.space.md },
    entryHeader: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      width: '100%',
      boxSizing: 'border-box',
      border: 'none',
      background: 'transparent',
      color: t.color.text,
      cursor: 'pointer',
      font: 'inherit',
      textAlign: 'left',
      padding: 0,
    },
    caret: { flexShrink: 0, width: 12, color: t.color.textMuted, fontSize: t.type.size.xs },
    phaseLabel: { flexShrink: 0 },
    issue: { flexShrink: 0 },
    events: { display: 'flex', flexDirection: 'column', gap: t.space.xxs, marginTop: t.space.xs },
    eventRow: { display: 'flex', alignItems: 'baseline', gap: t.space.xs, minWidth: 0 },
    bullet: { flexShrink: 0, color: t.color.textMuted, fontSize: t.type.size.xs },
    eventText: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
    diffs: { display: 'flex', flexDirection: 'column', gap: t.space.xxs, marginTop: t.space.xs },
    diffRow: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.sm,
      minWidth: 0,
      padding: `${t.space.xxs}px ${t.space.sm}px`,
      background: t.color.surfaceInset,
      borderRadius: t.radius.sm,
    },
    diffLink: { color: t.color.accent, textDecoration: 'none', flexShrink: 0 },
    diffSha: { flexShrink: 0 },
    diffStat: { flexShrink: 0 },
    add: { color: t.color.green },
    del: { color: t.color.red },
  }
}

/**
 * A single PR/commit diff row inside a phase. Renders only what the event stream
 * actually carried — a linked PR number, a short commit sha, and `+add −del` /
 * file count when present — never a fabricated diff body.
 * @param {{ diff: object, styles: object }} props
 */
function DiffRow({ diff, styles }) {
  const hasStat =
    diff.additions != null || diff.deletions != null || diff.filesChanged != null
  return (
    <div data-testid={`timeline-diff-${diff.id}`} style={styles.diffRow}>
      {diff.prNumber != null && (
        diff.url ? (
          <a
            data-testid={`timeline-diff-link-${diff.id}`}
            href={diff.url}
            target="_blank"
            rel="noreferrer"
            style={styles.diffLink}
          >
            <Text as="span" size="xs" weight="semibold" tone="accent">{`PR #${diff.prNumber}`}</Text>
          </a>
        ) : (
          <Text as="span" size="xs" weight="semibold" tone="accent" style={styles.diffLink}>
            {`PR #${diff.prNumber}`}
          </Text>
        )
      )}
      {diff.commitSha != null && (
        <Text as="span" size="xs" tone="code" style={styles.diffSha} data-testid={`timeline-diff-sha-${diff.id}`}>
          {String(diff.commitSha).slice(0, 7)}
        </Text>
      )}
      {diff.filesChanged != null && (
        <Text as="span" size="xs" tone="muted" style={styles.diffStat}>
          {`${diff.filesChanged} ${diff.filesChanged === 1 ? 'file' : 'files'}`}
        </Text>
      )}
      {hasStat && (diff.additions != null || diff.deletions != null) && (
        <Text as="span" size="xs" tone="muted" style={styles.diffStat} data-testid={`timeline-diff-stat-${diff.id}`}>
          {diff.additions != null && <span style={styles.add}>{`+${diff.additions}`}</span>}
          {diff.additions != null && diff.deletions != null ? ' ' : ''}
          {diff.deletions != null && <span style={styles.del}>{`−${diff.deletions}`}</span>}
        </Text>
      )}
    </div>
  )
}

/**
 * One phase container: a stage-coloured rail node beside a collapsible card
 * carrying the phase label + issue + duration, its event bullets, and any diff
 * rows. `isLast` drops the trailing rail connector on the final container.
 * @param {{ entry: object, isLast: boolean, styles: object }} props
 */
function TimelineEntry({ entry, isLast, styles }) {
  const [open, setOpen] = useState(() => readOpenState()[entry.id] !== false)
  const toggle = () => setOpen(prev => {
    const next = !prev
    persistOpenState(entry.id, next)
    return next
  })

  return (
    <div data-testid={`timeline-entry-${entry.id}`} data-phase={entry.phase} style={styles.entry}>
      <div style={styles.rail}>
        <span
          data-testid={`timeline-node-${entry.id}`}
          data-stage-color={stageColorKey(entry.phase) ?? ''}
          aria-hidden="true"
          style={styles.node(entry.phase)}
        />
        {!isLast && <span aria-hidden="true" style={styles.line} />}
      </div>
      <div style={styles.content}>
        <button
          type="button"
          data-testid={`timeline-toggle-${entry.id}`}
          aria-expanded={open}
          onClick={toggle}
          style={styles.entryHeader}
        >
          <span style={styles.caret} aria-hidden="true">{open ? '▾' : '▸'}</span>
          <Text
            as="span"
            size="sm"
            weight="semibold"
            uppercase
            style={styles.phaseLabel}
            data-testid={`timeline-phase-${entry.phase}`}
          >
            {entry.phaseLabel}
          </Text>
          {entry.issue != null && (
            <Text as="span" size="xs" tone="muted" style={styles.issue} data-testid={`timeline-issue-${entry.id}`}>
              {`#${entry.issue}`}
            </Text>
          )}
          <span style={styles.spacer} />
          {entry.diffs.length > 0 && (
            <Badge tone="accent" data-testid={`timeline-diffcount-${entry.id}`}>
              {`${entry.diffs.length} PR`}
            </Badge>
          )}
          {entry.durationLabel !== '' && (
            <Text as="span" size="xs" tone="muted" data-testid={`timeline-duration-${entry.id}`}>
              {entry.durationLabel}
            </Text>
          )}
        </button>
        {open && (
          <>
            {entry.events.length > 0 && (
              <div style={styles.events} data-testid={`timeline-events-${entry.id}`}>
                {entry.events.map((ev, i) => (
                  <div key={i} style={styles.eventRow} data-testid={`timeline-event-${entry.id}-${i}`} data-kind={ev.kind}>
                    <span style={styles.bullet} aria-hidden="true">{'•'}</span>
                    <Text as="span" size="xs" tone="muted" style={styles.eventText}>{ev.text}</Text>
                  </div>
                ))}
              </div>
            )}
            {entry.diffs.length > 0 && (
              <div style={styles.diffs} data-testid={`timeline-diffs-${entry.id}`}>
                {entry.diffs.map(diff => (
                  <DiffRow key={diff.id} diff={diff} styles={styles} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

/**
 * @param {{ timeline?: { entries: Array } }} props
 */
export function TimelinePanel({ timeline }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const entries = timeline?.entries ?? []

  return (
    <Card as="section" data-testid="timeline-panel" style={styles.panel} aria-label="Phase timeline">
      <div style={styles.header}>
        <Text size="xs" weight="semibold" tone="muted" uppercase>Timeline</Text>
        <span style={styles.spacer} />
        {entries.length > 0 && (
          <Badge tone="neutral" data-testid="timeline-count">{entries.length}</Badge>
        )}
      </div>
      <div style={styles.body}>
        {entries.length === 0 ? (
          <div data-testid="timeline-empty" style={styles.empty}>No phases yet.</div>
        ) : (
          entries.map((entry, i) => (
            <TimelineEntry
              key={entry.id}
              entry={entry}
              isLast={i === entries.length - 1}
              styles={styles}
            />
          ))
        )}
      </div>
    </Card>
  )
}

export default TimelinePanel

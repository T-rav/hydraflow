/**
 * ActiveGrid — the operator console's "all-active" view (epic #10556, Task 5).
 *
 * Where Focus mode drills a single item into the full `ItemWorkspace`, the
 * all-active mode fans out: a responsive grid of compact live transcripts, one
 * tile per item the factory is actively working — across EVERY workflow stage
 * (triage → plan → build → review), not just Build. Each tile streams that
 * item's own transcript by running the Task-1 `toTranscript` adapter for its id
 * and feeding the rows straight into the Task-4 `TranscriptStream` (reuse, don't
 * reimplement the stream). Tiles add and remove as the active set changes, so
 * the grid always mirrors what the factory is working right now, and each tile
 * shows how long that item has been running (issue #7 / #13).
 *
 * Clicking a tile header drills back into Focus on that item (switches
 * `mode` -> 'focus' and selects the item) so the grid doubles as a picker.
 *
 * Presentation only — no socket, no side effects. Stage-completeness and the
 * relative-duration derivation live in `model/pipeline.js`
 * (`activeWorkflowItems`, `stageDurationLabel`) so this component stays a pure
 * view. The clock is injected via the `now` prop (defaulting to `Date.now()` at
 * render) — the model formatter never reads the wall clock — so durations are
 * deterministic under test. Phase-2 (Task 12): tiles use the `Card` primitive
 * and every colour / space value resolves from `useTokens()`, so light + dark
 * fall out of the console's ThemeProvider mode.
 */

import React, { useMemo } from 'react'
import { useTokens, Card, Text } from '../styles/primitives'
import { toTranscript } from './model/transcript'
import { activeWorkflowItems, stageColorKey, stageDurationLabel, stageTransitionTs } from './model/pipeline'
import { PULSE_ANIMATION } from '../constants'
import { TranscriptStream } from './TranscriptStream'

/**
 * The "building set": items sitting in the Build (`implement`) stage of a
 * pipeline view model. Exported so the shell and tests can derive it without a
 * render. Tolerant of a missing / empty pipeline.
 * @param {{ stages?: Array }} [pipeline]
 * @returns {Array<{id, title, status}>}
 */
export function buildingItemsOf(pipeline) {
  const stages = pipeline?.stages ?? []
  const build = stages.find(s => s.key === 'implement')
  return build?.items ?? []
}

function makeStyles(t) {
  return {
    grid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
      gap: t.space.md,
      minWidth: 0,
    },
    tile: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xs,
      minWidth: 0,
      background: t.color.surfaceInset,
      padding: t.space.sm,
      boxSizing: 'border-box',
    },
    headerRow: {
      display: 'flex',
      alignItems: 'baseline',
      justifyContent: 'space-between',
      gap: t.space.xs,
      minWidth: 0,
    },
    header: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.xs,
      minWidth: 0,
      flex: '1 1 auto',
      border: 'none',
      background: 'none',
      color: 'inherit',
      font: 'inherit',
      textAlign: 'left',
      cursor: 'pointer',
      padding: 0,
    },
    meta: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.xs,
      flex: '0 0 auto',
    },
    // The tile's live indicator (#17/#18): a dot painted in the item's STAGE
    // colour (classic palette) replacing the old generic green "LIVE" pulse. An
    // unknown stage falls back to the neutral muted tone. The dot BLINKS (shared
    // stream-pulse) while the item is actively working, and sits SOLID while it
    // is merely queued in the stage (#18).
    stageDot: (stage, working) => ({
      display: 'inline-block',
      width: 7,
      height: 7,
      borderRadius: t.radius.pill,
      flexShrink: 0,
      background: t.color[stageColorKey(stage)] ?? t.color.textMuted,
      ...(working ? { animation: PULSE_ANIMATION } : {}),
    }),
    title: {
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      minWidth: 0,
    },
    empty: { padding: `${t.space.md}px ${t.space.xxs}px` },
  }
}

/**
 * A single compact tile: an item header (id + title, a stage-coloured live dot,
 * the stage label, and a `stage / total` running duration) plus its live
 * transcript stream.
 *
 * The item has no timestamp of its own (the pipeline snapshot's `PipelineIssue`
 * carries none), so its durations are derived from the item's own event stream:
 *   - TOTAL = now − the earliest `toTranscript` row (first-seen activity);
 *   - STAGE = now − the most recent stage transition, inferred from the rows'
 *     `meta.source` via `stageTransitionTs`; when no transition is observed the
 *     tile shows just the total (#17).
 * `now` is injected so the durations are deterministic under test. The dot takes
 * the item's stage colour (classic palette), replacing the old generic "LIVE".
 *
 * @param {{ item: {id, title, stage?, stageLabel?}, events: Array, now: number, select?: Function, styles: object }} props
 */
function ActiveTile({ item, events, now, select, styles }) {
  const rows = useMemo(() => toTranscript(events, item.id), [events, item.id])
  // Rows are oldest-first; the first row's ts is the item's start-of-activity.
  const startTs = rows.length > 0 ? rows[0].ts : null
  const totalDuration = stageDurationLabel(startTs, now)
  // Stage duration: elapsed since the most recent observed stage transition.
  // Null (single observed stage) → fall back to just the total.
  const stageTs = stageTransitionTs(rows)
  const stageDuration = stageTs != null ? stageDurationLabel(stageTs, now) : ''
  const durationText =
    stageDuration && stageDuration !== totalDuration
      ? `${stageDuration} / ${totalDuration}`
      : totalDuration

  const onFocus = () => {
    // Jump back to Focus on this item — mode first (orthogonal to depth), then
    // the item selection. Both apply against prev so the result is
    // { mode: 'focus', item: <id> }.
    select?.('mode', 'focus')
    select?.('item', item.id)
  }

  return (
    <Card as="div" data-testid={`active-tile-${item.id}`} data-item-id={item.id} style={styles.tile}>
      <div style={styles.headerRow}>
        <button
          type="button"
          data-testid={`active-tile-header-${item.id}`}
          onClick={onFocus}
          style={styles.header}
          title="Focus this item"
        >
          <Text as="span" size="md" weight="bold" tone="bright">#{item.id}</Text>
          {item.title != null && item.title !== '' && (
            <Text as="span" size="sm" tone="muted" style={styles.title}>{item.title}</Text>
          )}
        </button>
        <div style={styles.meta}>
          <span
            data-testid={`active-stage-dot-${item.id}`}
            data-stage-color={stageColorKey(item.stage) ?? ''}
            data-working={item.status === 'active'}
            aria-hidden="true"
            style={styles.stageDot(item.stage, item.status === 'active')}
          />
          {item.stageLabel != null && item.stageLabel !== '' && (
            <Text as="span" size="xs" tone="muted" uppercase data-testid={`active-stage-${item.id}`}>
              {item.stageLabel}
            </Text>
          )}
          {durationText !== '' && (
            <Text as="span" size="xs" tone="muted" data-testid={`active-duration-${item.id}`}>
              {durationText}
            </Text>
          )}
        </div>
      </div>
      {/* The tile header now owns the live/stage indicator (#17), so the stream's
          own generic green "Live" pulse is suppressed to avoid a duplicate. */}
      <TranscriptStream rows={rows} active={false} />
    </Card>
  )
}

/**
 * @param {{
 *   pipeline?: { stages?: Array },
 *   events?: Array,
 *   now?: number,
 *   select?: Function,
 * }} props
 */
export function ActiveGrid({ pipeline, events = [], now = Date.now(), select }) {
  const t = useTokens()
  const styles = makeStyles(t)
  // Every actively-worked item across the workflow stages (triage → plan →
  // build → review), not just the Build stage — issue #13.
  const items = useMemo(() => activeWorkflowItems(pipeline), [pipeline])

  return (
    <div data-testid="active-grid" style={styles.grid}>
      {items.length === 0 ? (
        <Text as="div" size="sm" tone="muted" data-testid="active-grid-empty" style={styles.empty}>
          Nothing active right now.
        </Text>
      ) : (
        items.map(item => (
          <ActiveTile
            key={`${item.stage}-${item.id}`}
            styles={styles}
            item={item}
            events={events}
            now={now}
            select={select}
          />
        ))
      )}
    </div>
  )
}

export default ActiveGrid

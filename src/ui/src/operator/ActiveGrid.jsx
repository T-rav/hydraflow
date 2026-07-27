/**
 * ActiveGrid — the operator console's "all-active" view (epic #10556, Task 5).
 *
 * Where Focus mode drills a single item into the full `ItemWorkspace`, the
 * all-active mode fans out: a responsive grid of compact live transcripts, one
 * tile per BUILDING item — the pipeline VM's Build (`implement`) stage. Each
 * tile streams that item's own transcript by running the Task-1 `toTranscript`
 * adapter for its id and feeding the rows straight into the Task-4
 * `TranscriptStream` (reuse, don't reimplement the stream). Tiles add and remove
 * as the building set changes, so the grid always mirrors what the factory is
 * actively working right now.
 *
 * Clicking a tile header drills back into Focus on that item (switches
 * `mode` -> 'focus' and selects the item) so the grid doubles as a picker.
 *
 * Presentation only — no socket, no side effects. Phase-2 (Task 12): tiles use
 * the `Card` primitive and every colour / space value resolves from
 * `useTokens()`, so light + dark fall out of the console's ThemeProvider mode.
 */

import React, { useMemo } from 'react'
import { useTokens, Card, Text } from '../styles/primitives'
import { toTranscript } from './model/transcript'
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
    header: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.xs,
      minWidth: 0,
      border: 'none',
      background: 'none',
      color: 'inherit',
      font: 'inherit',
      textAlign: 'left',
      cursor: 'pointer',
      padding: 0,
      width: '100%',
    },
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
 * A single compact tile: an item header + its live transcript stream.
 * @param {{ item: {id, title}, events: Array, select?: Function, styles: object }} props
 */
function ActiveTile({ item, events, select, styles }) {
  const rows = useMemo(() => toTranscript(events, item.id), [events, item.id])

  const onFocus = () => {
    // Jump back to Focus on this item — mode first (orthogonal to depth), then
    // the item selection. Both apply against prev so the result is
    // { mode: 'focus', item: <id> }.
    select?.('mode', 'focus')
    select?.('item', item.id)
  }

  return (
    <Card as="div" data-testid={`active-tile-${item.id}`} data-item-id={item.id} style={styles.tile}>
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
      <TranscriptStream rows={rows} active />
    </Card>
  )
}

/**
 * @param {{
 *   pipeline?: { stages?: Array },
 *   events?: Array,
 *   select?: Function,
 * }} props
 */
export function ActiveGrid({ pipeline, events = [], select }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const items = useMemo(() => buildingItemsOf(pipeline), [pipeline])

  return (
    <div data-testid="active-grid" style={styles.grid}>
      {items.length === 0 ? (
        <Text as="div" size="sm" tone="muted" data-testid="active-grid-empty" style={styles.empty}>
          Nothing building right now.
        </Text>
      ) : (
        items.map(item => (
          <ActiveTile key={item.id} styles={styles} item={item} events={events} select={select} />
        ))
      )}
    </div>
  )
}

export default ActiveGrid

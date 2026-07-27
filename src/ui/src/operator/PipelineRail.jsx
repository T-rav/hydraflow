/**
 * PipelineRail — the operator console's hero (epic #10556, Task 3).
 *
 * Renders the six canonical operator stages (Triage → Plan → Build → Review →
 * HITL → Merged) as a rail of tiles driven entirely by the pipeline view model
 * produced by `toPipeline(...)` (Task 1). Each tile surfaces the stage's live
 * count, its worker slots (used/cap, role-bearing stages only), and attention
 * badges: the HITL tile carries a badge equal to the HITL depth, and any stage
 * with failed work carries a red danger badge. Below the tile header the stage's
 * in-flight items render as chips, with a red marker on failed items.
 *
 * Interaction is delegated to the `select(kind, value)` callback threaded down
 * from `useOperatorSelection` (Task 2): clicking a tile emits
 * `select('stage', key)`, clicking an item chip emits `select('item', id)`.
 * The chip buttons are siblings of the tile-header button (not nested), so a
 * chip click never also triggers the stage selection.
 *
 * Presentation only — no socket, no side effects. Styling uses the shared
 * `theme` CSS-variable references so the dark/light paths and the Phase-2 token
 * migration keep working.
 */

import React from 'react'
import { theme } from '../theme'

const styles = {
  rail: {
    display: 'flex',
    alignItems: 'stretch',
    gap: 8,
    overflowX: 'auto',
    padding: '4px 2px',
    minWidth: 0,
  },
  tile: {
    flex: '1 1 0',
    minWidth: 120,
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    padding: 8,
    boxSizing: 'border-box',
  },
  header: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    alignItems: 'flex-start',
    width: '100%',
    textAlign: 'left',
    border: 'none',
    background: 'transparent',
    color: theme.text,
    cursor: 'pointer',
    padding: 0,
    font: 'inherit',
  },
  labelRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    width: '100%',
  },
  label: {
    fontSize: 11,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    color: theme.textMuted,
  },
  count: {
    fontSize: 22,
    fontWeight: 700,
    lineHeight: 1,
    color: theme.textBright,
  },
  slots: {
    fontSize: 10,
    color: theme.textMuted,
    fontVariantNumeric: 'tabular-nums',
  },
  badge: {
    marginLeft: 'auto',
    borderRadius: 10,
    padding: '1px 7px',
    fontSize: 10,
    fontWeight: 700,
    lineHeight: 1.6,
    whiteSpace: 'nowrap',
  },
  hitlBadge: {
    background: theme.orange,
    color: theme.bg,
  },
  failedBadge: {
    background: theme.red,
    color: theme.white,
  },
  chips: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 4,
  },
  chip: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    maxWidth: '100%',
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    background: theme.surfaceInset,
    color: theme.text,
    cursor: 'pointer',
    padding: '2px 6px',
    fontSize: 10,
    font: 'inherit',
    fontWeight: 500,
    lineHeight: 1.4,
  },
  chipId: {
    color: theme.textMuted,
    fontVariantNumeric: 'tabular-nums',
  },
  chipTitle: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: 90,
  },
  itemFailedDot: {
    display: 'inline-block',
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: theme.red,
    flexShrink: 0,
  },
}

function StageTile({ stage, select, active }) {
  const { key, label, count, slots, items, attention } = stage
  const showHitl = attention?.hitl > 0
  const showFailed = attention?.failed > 0

  return (
    <div style={styles.tile} data-testid={`stage-card-${key}`}>
      <button
        type="button"
        data-testid={`stage-tile-${key}`}
        aria-pressed={active}
        style={{
          ...styles.header,
          ...(active ? { color: theme.accent } : null),
        }}
        onClick={() => select('stage', key)}
      >
        <span style={styles.labelRow}>
          <span style={styles.label}>{label}</span>
          {showHitl && (
            <span
              data-testid={`stage-hitl-badge-${key}`}
              data-tone="attention"
              style={{ ...styles.badge, ...styles.hitlBadge }}
            >
              {attention.hitl}
            </span>
          )}
          {showFailed && (
            <span
              data-testid={`stage-failed-badge-${key}`}
              data-tone="danger"
              style={{
                ...styles.badge,
                ...styles.failedBadge,
                marginLeft: showHitl ? 4 : 'auto',
              }}
            >
              {attention.failed}
            </span>
          )}
        </span>
        <span style={styles.labelRow}>
          <span data-testid={`stage-count-${key}`} style={styles.count}>
            {count}
          </span>
          {slots && (
            <span data-testid={`stage-slots-${key}`} style={styles.slots}>
              {slots.used}/{slots.cap ?? '∞'}
            </span>
          )}
        </span>
      </button>

      {items?.length > 0 && (
        <div style={styles.chips}>
          {items.map(item => {
            const failed = item.status === 'failed'
            return (
              <button
                key={item.id}
                type="button"
                data-testid={`item-chip-${item.id}`}
                data-status={item.status}
                style={{
                  ...styles.chip,
                  ...(failed ? { borderColor: theme.red } : null),
                }}
                title={item.title}
                onClick={() => select('item', item.id)}
              >
                {failed && (
                  <span
                    data-testid={`item-failed-${item.id}`}
                    data-tone="danger"
                    aria-label="failed"
                    style={styles.itemFailedDot}
                  />
                )}
                <span style={styles.chipId}>#{item.id}</span>
                <span style={styles.chipTitle}>{item.title}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

/**
 * @param {{
 *   pipeline: { stages: Array },
 *   select: (kind: string, value: unknown) => void,
 *   stage?: string|null,
 * }} props
 */
export function PipelineRail({ pipeline = { stages: [] }, select = () => {}, stage = null }) {
  const stages = pipeline?.stages ?? []
  return (
    <div data-testid="pipeline-rail" style={styles.rail}>
      {stages.map(s => (
        <StageTile key={s.key} stage={s} select={select} active={s.key === stage} />
      ))}
    </div>
  )
}

export default PipelineRail

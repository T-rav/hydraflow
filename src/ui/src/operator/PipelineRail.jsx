/**
 * PipelineRail — the operator console's hero (epic #10556, Task 3).
 *
 * Renders the six canonical operator stages (Triage → Plan → Build → Review →
 * HITL → Merged) as a rail of tiles driven entirely by the pipeline view model
 * produced by `toPipeline(...)` (Task 1). Each tile surfaces the stage's live
 * count, its worker slots (used/cap, role-bearing stages only), and attention
 * badges: the HITL tile carries a badge equal to the HITL depth, and any stage
 * with failed work carries a red danger badge. Below the tile header the stage's
 * in-flight items render as chips, with a red marker on failed items; the
 * terminal stages (hitl, merged) list their items as compact issue-id chips
 * (#14). Each tile's top bar is painted in the stage's IDENTITY colour from the
 * classic dashboard palette (constants.PIPELINE_STAGES, #10) — severity/attention
 * still signal through `data-severity` and the badges.
 *
 * Interaction is delegated to the `select(kind, value)` callback threaded down
 * from `useOperatorSelection` (Task 2): clicking a tile emits
 * `select('stage', key)`, clicking an item chip emits `select('item', id)`.
 * The chip buttons are siblings of the tile-header button (not nested), so a
 * chip click never also triggers the stage selection.
 *
 * Presentation only — no socket, no side effects. Phase-2 (Task 12) styles the
 * tile surface with the `Card` primitive, the attention markers with `Badge`,
 * and every colour / space value from `useTokens()` — light + dark resolve from
 * the console's ThemeProvider mode, no hardcoded literals.
 */

import React from 'react'
import { useTokens, Card, Badge, Text } from '../styles/primitives'
import { stageColorKey } from './model/pipeline'

/**
 * Derive a stage's health severity from its view model, precedence
 * failed > hitl > flowing > idle:
 *   - `attention.failed > 0` → 'bad'   (something in this stage errored)
 *   - `attention.hitl > 0`   → 'warn'  (work is parked awaiting a human)
 *   - `count > 0`            → 'ok'    (work is flowing through the stage)
 *   - otherwise              → 'muted' (idle / empty)
 */
function stageSeverity(stage) {
  const failed = stage?.attention?.failed ?? 0
  const hitl = stage?.attention?.hitl ?? 0
  const count = stage?.count ?? 0
  if (failed > 0) return 'bad'
  if (hitl > 0) return 'warn'
  if (count > 0) return 'ok'
  return 'muted'
}

function makeStyles(t) {
  // Severity → token colour. Every value routes through the resolved token
  // bundle (no hardcoded literal), so the bar flips with the theme mode:
  // ok=green, warn=yellow (the same tone the HITL badge uses), bad=red,
  // muted=border (a neutral idle line).
  const severityColor = {
    ok: t.color.green,
    warn: t.color.yellow,
    bad: t.color.red,
    muted: t.color.border,
  }
  // A stage's IDENTITY colour, from the classic dashboard palette
  // (constants.PIPELINE_STAGES → token colour key): triage=yellow, plan=purple,
  // build=accent, review=orange, hitl=red, merged=green. Falls back to the
  // neutral muted line for an unknown stage key.
  const stageColor = (key) => t.color[stageColorKey(key)] ?? severityColor.muted
  return {
    severityColor,
    stageColor,
    rail: {
      display: 'flex',
      alignItems: 'stretch',
      gap: t.space.sm,
      overflowX: 'auto',
      padding: `${t.space.xs}px ${t.space.xxs}px`,
      minWidth: 0,
    },
    tile: {
      flex: '1 1 0',
      minWidth: 120,
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xs,
      padding: t.space.sm,
      boxSizing: 'border-box',
    },
    // A thin health bar full-bleed across the top of the tile. Negative margins
    // (token-backed) pull it out to the card's padded edge; the top radius
    // matches the Card so it hugs the rounded corners.
    colorBar: (color) => ({
      height: 3,
      marginTop: -t.space.sm,
      marginLeft: -t.space.sm,
      marginRight: -t.space.sm,
      borderTopLeftRadius: t.radius.lg,
      borderTopRightRadius: t.radius.lg,
      background: color,
      flexShrink: 0,
    }),
    header: (active) => ({
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xs,
      alignItems: 'flex-start',
      width: '100%',
      textAlign: 'left',
      border: 'none',
      background: 'transparent',
      color: active ? t.color.accent : t.color.text,
      cursor: 'pointer',
      padding: 0,
      font: 'inherit',
    }),
    labelRow: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.xs,
      width: '100%',
    },
    badgeShift: (shift) => ({ marginLeft: shift }),
    chips: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: t.space.xs,
    },
    chip: (failed) => ({
      display: 'inline-flex',
      alignItems: 'center',
      gap: t.space.xs,
      maxWidth: '100%',
      border: `1px solid ${failed ? t.color.red : t.color.border}`,
      borderRadius: t.radius.md,
      background: t.color.surfaceInset,
      color: t.color.text,
      cursor: 'pointer',
      padding: `${t.space.xxs}px ${t.space.xs}px`,
      fontSize: t.type.size.xs,
      font: 'inherit',
      fontWeight: t.type.weight.medium,
      lineHeight: 1.4,
    }),
    chipTitle: {
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      maxWidth: 90,
    },
    // Terminal stages (hitl, merged) list their items as compact issue-id
    // chips — the classic dashboard's dot/id treatment (#14) — rather than only
    // a count, so an operator sees WHICH issues are parked / just merged.
    itemIds: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: t.space.xxs,
    },
    idChip: (failed) => ({
      display: 'inline-flex',
      alignItems: 'center',
      border: `1px solid ${failed ? t.color.red : t.color.border}`,
      borderRadius: t.radius.md,
      background: t.color.surfaceInset,
      color: t.color.text,
      cursor: 'pointer',
      padding: `${t.space.xxs}px ${t.space.xs}px`,
      font: 'inherit',
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.medium,
      lineHeight: 1.4,
    }),
    itemFailedDot: {
      display: 'inline-block',
      width: 6,
      height: 6,
      borderRadius: t.radius.pill,
      background: t.color.red,
      flexShrink: 0,
    },
    labelText: { letterSpacing: t.type.tracking.wide },
    count: { fontSize: t.type.size.xl, lineHeight: 1 },
  }
}

function StageTile({ styles, stage, select, active }) {
  const { key, label, count, slots, items, attention } = stage
  const showHitl = attention?.hitl > 0
  const showFailed = attention?.failed > 0
  const severity = stageSeverity(stage)
  // The bar is painted in the stage's IDENTITY colour (classic palette, #10);
  // severity/attention still signal through `data-severity` + the badges below.
  const colorKey = stageColorKey(key)
  // Terminal stages surface their items as compact issue-id chips (#14); the
  // workflow stages keep the richer id-plus-title chips.
  const isTerminal = key === 'hitl' || key === 'merged'

  return (
    <Card as="div" style={styles.tile} data-testid={`stage-card-${key}`}>
      <div
        data-testid={`stage-colorbar-${key}`}
        data-severity={severity}
        data-stage-color={colorKey ?? ''}
        aria-hidden="true"
        style={styles.colorBar(styles.stageColor(key))}
      />
      <button
        type="button"
        data-testid={`stage-tile-${key}`}
        aria-pressed={active}
        style={styles.header(active)}
        onClick={() => select('stage', key)}
      >
        <span style={styles.labelRow}>
          <Text size="xs" weight="bold" tone="muted" uppercase style={styles.labelText}>{label}</Text>
          {showHitl && (
            <Badge
              tone="warning"
              data-testid={`stage-hitl-badge-${key}`}
              data-tone="attention"
              style={styles.badgeShift('auto')}
            >
              {attention.hitl}
            </Badge>
          )}
          {showFailed && (
            <Badge
              tone="danger"
              data-testid={`stage-failed-badge-${key}`}
              data-tone="danger"
              style={styles.badgeShift(showHitl ? 4 : 'auto')}
            >
              {attention.failed}
            </Badge>
          )}
        </span>
        <span style={styles.labelRow}>
          <Text as="span" size="xxl" weight="bold" tone="bright" data-testid={`stage-count-${key}`} style={styles.count}>
            {count}
          </Text>
          {slots && (
            <Text as="span" size="xs" tone="muted" data-testid={`stage-slots-${key}`}>
              {slots.used}/{slots.cap ?? '∞'}
            </Text>
          )}
        </span>
      </button>

      {items?.length > 0 && !isTerminal && (
        <div style={styles.chips}>
          {items.map(item => {
            const failed = item.status === 'failed'
            return (
              <button
                key={item.id}
                type="button"
                data-testid={`item-chip-${item.id}`}
                data-status={item.status}
                style={styles.chip(failed)}
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
                <Text as="span" size="xs" tone="muted">#{item.id}</Text>
                <Text as="span" size="xs" style={styles.chipTitle}>{item.title}</Text>
              </button>
            )
          })}
        </div>
      )}

      {items?.length > 0 && isTerminal && (
        <div style={styles.itemIds} data-testid={`stage-items-${key}`}>
          {items.map(item => (
            <button
              key={item.id}
              type="button"
              data-testid={`stage-item-${key}-${item.id}`}
              data-status={item.status}
              style={styles.idChip(item.status === 'failed')}
              title={item.title}
              onClick={() => select('item', item.id)}
            >
              <Text as="span" size="xs" tone="muted">#{item.id}</Text>
            </button>
          ))}
        </div>
      )}
    </Card>
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
  const t = useTokens()
  const styles = makeStyles(t)
  const stages = pipeline?.stages ?? []
  return (
    <div data-testid="pipeline-rail" style={styles.rail}>
      {stages.map(s => (
        <StageTile key={s.key} styles={styles} stage={s} select={select} active={s.key === stage} />
      ))}
    </div>
  )
}

export default PipelineRail

/**
 * PipelineRail — the operator console's hero (epic #10556, Task 3).
 *
 * Renders the six canonical operator stages (Triage → Plan → Build → Review →
 * HITL → Merged) as a rail of tiles driven entirely by the pipeline view model
 * produced by `toPipeline(...)` (Task 1). Each tile surfaces the stage's live
 * count, its worker slots (used/cap, role-bearing stages only), and attention
 * badges: the HITL tile carries a badge equal to the HITL depth, and any stage
 * with failed work carries a red danger badge.
 *
 * Within each WORKFLOW column (triage/plan/build/review) the in-flight items are
 * split into two legible sub-groups (#10943): an ACTIVE section (a worker is
 * running that item — pulse marker) on top, and a QUEUED section (waiting for a
 * slot, dimmed, collapsed past ~5) below. A per-column filter chip
 * (`Active | Queued | All`, default All, remembered per column) scopes the
 * column, and a phase with zero active items reads an honest `idle — N queued`
 * rather than looking like N are in-progress. The split keys off the same
 * "is a worker on this?" claim signal (`splitPhaseItems`, model/agents.js) that
 * drives the agent view, so the two board views can never disagree on which of
 * the 15 are building. The terminal stages (hitl, merged) list their items as
 * compact issue-id chips (#14).
 *
 * Interaction is delegated to the `select(kind, value)` callback threaded down
 * from `useOperatorSelection` (Task 2): clicking a tile emits
 * `select('stage', key)`, clicking an item chip emits `select('item', id)`.
 * The chip buttons are siblings of the tile-header button (not nested), so a
 * chip click never also triggers the stage selection.
 *
 * Presentation only — no socket, no side effects. Every colour / space value
 * resolves from `useTokens()`; light + dark fall out of the console's
 * ThemeProvider mode, no hardcoded literals.
 */

import React, { useState } from 'react'
import { useTokens, Card, Badge, Text } from '../styles/primitives'
import { stageColorKey } from './model/pipeline'
import { splitPhaseItems } from './model/agents'
import { PULSE_ANIMATION } from '../constants'

// Per-column filter chips (#10943): scope a workflow column to just the running
// items, just the waiting queue, or all of it (the default).
const PHASE_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Active' },
  { key: 'queued', label: 'Queued' },
]
const DEFAULT_PHASE_FILTER = 'all'
// Collapse a long QUEUED list past this many rows (unless the column is
// explicitly filtered to Queued, where the operator wants the whole queue).
const QUEUED_COLLAPSE = 5
// The per-column filter choice is remembered across reloads (guarded localStorage,
// mirroring TimelinePanel / LoopsPanel), keyed by stage.
const PHASE_FILTER_STORAGE_KEY = 'hydraflow.operator.phaseFilters'

function readStoredPhaseFilter(stageKey) {
  if (typeof window === 'undefined' || !window.localStorage) return DEFAULT_PHASE_FILTER
  try {
    const raw = window.localStorage.getItem(PHASE_FILTER_STORAGE_KEY)
    const map = raw ? JSON.parse(raw) : {}
    const stored = map?.[stageKey]
    return PHASE_FILTERS.some(f => f.key === stored) ? stored : DEFAULT_PHASE_FILTER
  } catch {
    return DEFAULT_PHASE_FILTER
  }
}

function writeStoredPhaseFilter(stageKey, value) {
  if (typeof window === 'undefined' || !window.localStorage) return
  try {
    const raw = window.localStorage.getItem(PHASE_FILTER_STORAGE_KEY)
    const map = raw ? JSON.parse(raw) : {}
    map[stageKey] = value
    window.localStorage.setItem(PHASE_FILTER_STORAGE_KEY, JSON.stringify(map))
  } catch {
    /* storage unavailable — the session-local state still works */
  }
}

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
    // A named group (ACTIVE / QUEUED) inside a workflow column (#10943).
    group: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xxs,
    },
    groupHeader: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.xs,
    },
    // The per-column filter chip row (Active | Queued | All).
    filterBar: {
      display: 'flex',
      gap: t.space.xxs,
    },
    filterChip: (on) => ({
      border: `1px solid ${on ? t.color.accent : t.color.border}`,
      borderRadius: t.radius.md,
      background: on ? t.color.accent : t.color.surfaceInset,
      color: on ? t.color.bg : t.color.textMuted,
      cursor: 'pointer',
      padding: `1px ${t.space.xs}px`,
      font: 'inherit',
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.medium,
    }),
    chip: (failed, dim) => ({
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
      // QUEUED items are visually recessed so the ACTIVE ones read first.
      opacity: dim ? 0.6 : 1,
    }),
    // The ACTIVE-item live pulse: a dot in the stage's identity colour.
    liveDot: (color) => ({
      display: 'inline-block',
      width: 6,
      height: 6,
      borderRadius: t.radius.pill,
      background: color,
      flexShrink: 0,
      animation: PULSE_ANIMATION,
    }),
    chipTitle: {
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      maxWidth: 90,
    },
    moreBtn: {
      alignSelf: 'flex-start',
      border: 'none',
      background: 'transparent',
      color: t.color.textMuted,
      cursor: 'pointer',
      padding: 0,
      font: 'inherit',
      fontSize: t.type.size.xs,
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

/**
 * A single workflow-stage item chip (id + title, a red marker when failed, a
 * live pulse when a worker is actively on it). Kept a stable component so the
 * ACTIVE and QUEUED groups render identical chips (only the dim + pulse differ).
 */
function ItemChip({ styles, stageKey, item, select, working, dim }) {
  const failed = item.status === 'failed'
  return (
    <button
      type="button"
      data-testid={`item-chip-${item.id}`}
      data-status={item.status}
      style={styles.chip(failed, dim)}
      title={item.title}
      onClick={() => select('item', item.id)}
    >
      {working && (
        <span
          data-testid={`item-live-${item.id}`}
          data-stage-color={stageColorKey(stageKey) ?? ''}
          aria-label="running"
          style={styles.liveDot(styles.stageColor(stageKey))}
        />
      )}
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
}

/**
 * The ACTIVE / QUEUED body of a workflow column (#10943). Drives both groups off
 * `splitPhaseItems`, hangs the per-column filter chips off remembered state, and
 * collapses a long queue.
 */
function WorkflowItems({ styles, stageKey, items, select }) {
  const [filter, setFilter] = useState(() => readStoredPhaseFilter(stageKey))
  const [queueExpanded, setQueueExpanded] = useState(false)
  const { active, queued } = splitPhaseItems(items)

  const chooseFilter = (value) => {
    setFilter(value)
    writeStoredPhaseFilter(stageKey, value)
  }

  const showActive = filter !== 'queued'
  const showQueued = filter !== 'active'
  // The queue collapses only in the un-filtered / active views; viewing Queued
  // explicitly shows the whole queue.
  const collapseQueue = filter !== 'queued' && !queueExpanded && queued.length > QUEUED_COLLAPSE
  const visibleQueued = collapseQueue ? queued.slice(0, QUEUED_COLLAPSE) : queued
  const hiddenQueued = queued.length - visibleQueued.length

  // Idle honesty: a column with zero active but a non-empty queue reads
  // "idle — N queued" instead of looking like N are in-progress.
  const idle = active.length === 0 && queued.length > 0

  return (
    <>
      <div style={styles.filterBar} role="group" aria-label={`${stageKey} filter`}>
        {PHASE_FILTERS.map(f => (
          <button
            key={f.key}
            type="button"
            data-testid={`phase-filter-${stageKey}-${f.key}`}
            aria-pressed={filter === f.key}
            style={styles.filterChip(filter === f.key)}
            onClick={() => chooseFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {idle && showQueued && (
        <Text as="div" size="xs" tone="muted" uppercase data-testid={`phase-idle-${stageKey}`} style={styles.labelText}>
          idle — {queued.length} queued
        </Text>
      )}

      {showActive && active.length > 0 && (
        <div style={styles.group} data-testid={`phase-active-${stageKey}`} data-group="active">
          <div style={styles.groupHeader}>
            <Text as="span" size="xs" weight="bold" tone="muted" uppercase style={styles.labelText}>Active</Text>
            <Text as="span" size="xs" tone="muted">{active.length}</Text>
          </div>
          <div style={styles.chips}>
            {active.map(item => (
              <ItemChip key={item.id} styles={styles} stageKey={stageKey} item={item} select={select} working />
            ))}
          </div>
        </div>
      )}

      {showQueued && queued.length > 0 && (
        <div style={styles.group} data-testid={`phase-queued-${stageKey}`} data-group="queued">
          <div style={styles.groupHeader}>
            <Text as="span" size="xs" weight="bold" tone="muted" uppercase style={styles.labelText}>Queued</Text>
            <Text as="span" size="xs" tone="muted">{queued.length}</Text>
          </div>
          <div style={styles.chips}>
            {visibleQueued.map(item => (
              <ItemChip key={item.id} styles={styles} stageKey={stageKey} item={item} select={select} dim />
            ))}
          </div>
          {collapseQueue && (
            <button
              type="button"
              data-testid={`phase-more-${stageKey}`}
              style={styles.moreBtn}
              onClick={() => setQueueExpanded(true)}
            >
              … +{hiddenQueued} more
            </button>
          )}
        </div>
      )}
    </>
  )
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
  // workflow stages get the ACTIVE/QUEUED split (#10943).
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
        <WorkflowItems styles={styles} stageKey={key} items={items} select={select} />
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

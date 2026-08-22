/**
 * EffectiveRoutesPanel — `?mode=routing&routingView=effective` (#11538, ADR-0140).
 *
 * A repository × worker-role × request-face grid, every cell resolved against
 * ONE policy revision and carrying the explanation that produced it. Three
 * honesty rules, all of which a prettier grid would break:
 *
 *   - **`unmanaged` is neutral, not a fault.** A cell no policy claims means
 *     "legacy routing decides this one", which is still the authoritative path
 *     in shadow mode. Drawing it red would train an operator to write policies
 *     to silence a badge.
 *   - **The revision is on the header, not implied.** Every cell shows the same
 *     `policy_revision` because they were resolved together; a grid whose rows
 *     saw different revisions is a race, and the header is where that claim is
 *     made checkable.
 *   - **Selecting a cell opens the trace that was already returned.** Nothing is
 *     re-resolved on click, so the explanation can never describe a newer
 *     revision than the grid was drawn from. The selection round-trips through
 *     the URL, so the view an operator is looking at is the view they can share.
 */

import React from 'react'
import { Badge, Text, useTokens } from '../styles/primitives'
import { EMPTY_EFFECTIVE_MATRIX_VM } from './model/policyWorkspace'

const SNAPSHOT_MESSAGES = {
  corrupt:
    'The policy snapshot cannot be read, so every route is held rather than resolved. This grid shows that hold, not an absence of policy.',
  absent:
    'No policy has been written for this repository. Every route below is decided by legacy routing.',
}

function makeStyles(t) {
  return {
    wrap: { display: 'flex', flexDirection: 'column', gap: t.space.md },
    card: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xs,
      padding: t.space.sm,
      borderRadius: t.radius.md,
      borderWidth: 1,
      borderStyle: 'solid',
      borderColor: t.color.border,
      background: t.color.surface,
      boxSizing: 'border-box',
    },
    header: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      flexWrap: 'wrap',
    },
    spacer: { flex: '1 1 auto' },
    scroller: { overflowX: 'auto', maxWidth: '100%' },
    rows: { display: 'flex', flexDirection: 'column', gap: t.space.xxs },
    row: {
      display: 'flex',
      alignItems: 'baseline',
      flexWrap: 'wrap',
      gap: t.space.sm,
      padding: `${t.space.xxs}px ${t.space.xs}px`,
      borderRadius: t.radius.sm,
      background: `color-mix(in srgb, ${t.color.text} 4%, transparent)`,
      appearance: 'none',
      borderWidth: 0,
      cursor: 'pointer',
      textAlign: 'left',
      width: '100%',
    },
    selectedRow: {
      display: 'flex',
      alignItems: 'baseline',
      flexWrap: 'wrap',
      gap: t.space.sm,
      padding: `${t.space.xxs}px ${t.space.xs}px`,
      borderRadius: t.radius.sm,
      background: `color-mix(in srgb, ${t.color.accent} 12%, transparent)`,
      appearance: 'none',
      borderWidth: 0,
      cursor: 'pointer',
      textAlign: 'left',
      width: '100%',
    },
    nameCol: {
      display: 'flex',
      flexDirection: 'column',
      minWidth: 0,
      flex: '1 1 auto',
    },
    facts: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      flexWrap: 'wrap',
      flexShrink: 0,
    },
    fact: { display: 'inline-flex', alignItems: 'baseline', gap: t.space.xxs },
    trace: { display: 'flex', flexDirection: 'column', gap: t.space.xxs },
    note: { padding: `${t.space.xxs}px 0` },
  }
}

function Fact({ label, value, styles, testid }) {
  return (
    <span style={styles.fact} data-testid={testid}>
      <Text as="span" size="xs" tone="muted" uppercase>
        {label}
      </Text>
      <Text as="span" size="sm" weight="semibold">
        {value}
      </Text>
    </span>
  )
}

function CellRow({ cell, selected, onSelect, styles }) {
  return (
    <button
      type="button"
      style={selected ? styles.selectedRow : styles.row}
      data-testid={`effective-cell-${cell.key}`}
      onClick={() => onSelect(cell.key)}
    >
      <span style={styles.nameCol}>
        <Text size="sm" weight="semibold">
          {`${cell.role} · ${cell.requestFace}`}
        </Text>
        <Text as="span" size="xs" tone="muted">
          {`${cell.requirement} · ${cell.policyId || 'no policy'}`}
        </Text>
      </span>
      <span style={styles.facts}>
        <Fact
          label="account"
          value={cell.accountId || '—'}
          styles={styles}
          testid={`effective-account-${cell.key}`}
        />
        <Fact
          label="model"
          value={cell.effectiveModel || '—'}
          styles={styles}
          testid={`effective-model-${cell.key}`}
        />
        <Badge tone={cell.tone} data-testid={`effective-state-${cell.key}`}>
          {cell.state}
        </Badge>
      </span>
    </button>
  )
}

/** The bounded trace the batch already returned for the selected cell. */
function ExplanationTrace({ cell, styles }) {
  if (!cell) {
    return (
      <Text role="status" size="sm" tone="muted" data-testid="effective-trace-empty">
        Select a route to read the explanation this revision produced for it.
      </Text>
    )
  }
  const considered = cell.explanation?.considered || []
  const rejected = cell.explanation?.rejected_accounts || []
  return (
    <div style={styles.trace} data-testid={`effective-trace-${cell.key}`}>
      <Text as="span" size="xs" tone="muted">
        {`outcome ${cell.outcome} · reason ${cell.reason} · source ${cell.policySource} · revision ${cell.policyRevision}`}
      </Text>
      {considered.length === 0 ? (
        <Text as="span" size="xs" tone="muted" data-testid="effective-considered-empty">
          No policy was considered for this route.
        </Text>
      ) : (
        considered.map(entry => (
          <Text
            key={entry.policy_id}
            as="span"
            size="xs"
            tone={entry.matched ? 'default' : 'muted'}
            data-testid={`effective-considered-${entry.policy_id}`}
          >
            {`${entry.policy_id} · level ${entry.precedence_level} · ${entry.reason}`}
          </Text>
        ))
      )}
      {rejected.map(entry => (
        <Text
          key={entry.account_id}
          as="span"
          size="xs"
          tone="warning"
          data-testid={`effective-rejected-${entry.account_id}`}
        >
          {`${entry.account_id} rejected · ${entry.reason}`}
        </Text>
      ))}
    </div>
  )
}

/**
 * @param {{ matrix?: object, selection?: string|null, select?: Function }} props
 */
export default function EffectiveRoutesPanel({
  matrix = EMPTY_EFFECTIVE_MATRIX_VM,
  selection = null,
  select = () => {},
}) {
  const t = useTokens()
  const styles = makeStyles(t)
  const selected = matrix.cells.find(cell => cell.key === selection) || null
  const snapshotMessage = SNAPSHOT_MESSAGES[matrix.snapshotState]

  return (
    <div style={styles.wrap} data-testid="effective-routes">
      <div style={styles.card}>
        <div style={styles.header}>
          <Text size="sm" weight="semibold" uppercase>
            Effective routes
          </Text>
          <Text as="span" size="xs" tone="muted" data-testid="effective-revision">
            {`${matrix.repo || 'this repo'} · policy revision ${matrix.policyRevision}`}
          </Text>
          <span style={styles.spacer} />
          <Text as="span" size="xs" tone="muted">
            {`${matrix.cells.length} routes`}
          </Text>
        </div>
        {snapshotMessage && (
          <div style={styles.note} data-testid="effective-snapshot-note">
            <Text
              size="sm"
              tone={matrix.snapshotState === 'corrupt' ? 'danger' : 'muted'}
              role={matrix.snapshotState === 'corrupt' ? 'alert' : 'status'}
            >
              {snapshotMessage}
            </Text>
          </div>
        )}
        {matrix.cells.length === 0 ? (
          <Text role="status" size="sm" tone="muted" data-testid="effective-empty">
            The effective-route matrix has not loaded yet.
          </Text>
        ) : (
          <div style={styles.scroller}>
            <div style={styles.rows}>
              {matrix.cells.map(cell => (
                <CellRow
                  key={cell.key}
                  cell={cell}
                  selected={selection === cell.key}
                  styles={styles}
                  onSelect={key => select('routingSelection', key)}
                />
              ))}
            </div>
          </div>
        )}
      </div>
      <div style={styles.card} data-testid="effective-trace">
        <Text size="sm" weight="semibold" uppercase>
          Pinned explanation
        </Text>
        <ExplanationTrace cell={selected} styles={styles} />
      </div>
    </div>
  )
}

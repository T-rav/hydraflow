/**
 * SupervisorSummary — the rail's compact one-line Supervisor readout
 * (#11207).
 *
 * Replaces the full `SupervisorPanel` in the 280px vitals column: a status
 * chip + open-escalation count that deep-links to the full-width Supervisor
 * tab — the same rail-compaction treatment PR #11203 gave the finder / loop
 * faceplates + judge calibration when they promoted to Instruments (the
 * vitals rail keeps only the glanceable set).
 *
 * Presentation only: no socket, no side effects — `onOpen` is called on
 * click (the console wires it to `select('mode', 'supervisor')`). Every
 * colour / space value resolves from `useTokens()` — no inline hardcoded hex —
 * so light + dark fall out of the console's ThemeProvider.
 */

import React from 'react'
import { useTokens, Text, Badge } from '../styles/primitives'
import { EMPTY_SUPERVISOR_VM } from './model/supervisorThread'

const VERDICT_TONE = {
  healthy: 'success',
  degraded: 'warning',
  escalations: 'danger',
  empty: 'neutral',
}

function makeStyles(t) {
  return {
    row: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.sm,
      width: '100%',
      boxSizing: 'border-box',
      border: `1px solid ${t.color.border}`,
      borderRadius: t.radius.lg,
      background: t.color.surface,
      color: t.color.text,
      cursor: 'pointer',
      padding: `${t.space.xs}px ${t.space.sm}px`,
      font: 'inherit',
      textAlign: 'left',
    },
    spacer: { flex: '1 1 auto' },
  }
}

/**
 * @param {{ supervisor?: ReturnType<typeof import('./model/supervisorThread').toSupervisorThread>,
 *           onOpen?: () => void }} props
 */
export function SupervisorSummary({ supervisor = EMPTY_SUPERVISOR_VM, onOpen }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const { verdict, verdictLabel, escalationCount } = supervisor

  return (
    <button
      type="button"
      data-testid="supervisor-summary"
      style={styles.row}
      onClick={() => onOpen?.()}
      aria-label="Open the Supervisor tab"
      title="Open the Supervisor tab"
    >
      <Text as="span" size="xs" weight="semibold" tone="muted" uppercase>Supervisor</Text>
      <Badge tone={VERDICT_TONE[verdict] ?? 'neutral'} data-testid="supervisor-summary-verdict">
        {verdictLabel}
      </Badge>
      <span style={styles.spacer} />
      {escalationCount > 0 && (
        <Text as="span" size="xs" tone="danger" data-testid="supervisor-summary-escalations">
          {`${escalationCount} escalation${escalationCount === 1 ? '' : 's'}`}
        </Text>
      )}
    </button>
  )
}

export default SupervisorSummary

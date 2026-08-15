/**
 * SupervisorMode — the full-width Supervisor detail-slot tab (#11207).
 *
 * Promotes supervision from a cramped 280px rail card to a full-width
 * surface, following the exact promotion pattern PR #11203 established for
 * Instruments: a mode key in `MODES` / `VALID_MODES` (OperatorConsole.jsx /
 * useOperatorSelection.js), full-width render in the detail slot, idle-exempt
 * (supervision matters most on a quiet factory — a paused/failed-over factory
 * IS the idle case an operator most needs this tab for).
 *
 * Layout: a GAUGES row up top — `toSupervisorGauges(...)`: tick health, open
 * escalations, credit state, attempt-budget consumption, cost burn — THE
 * POINT of the tab (gauge-first, not just the observation feed) — then the
 * existing `SupervisorPanel` (observation thread + action toolbar) beneath,
 * now with room to breathe instead of a stacked rail card.
 *
 * `SupervisorPanel` is reused UNCHANGED: its Resume/Pause buttons and
 * contextual restart-loop / ack-escalation affordances already read as a
 * toolbar once given full width — no duplicated action wiring, no new
 * data-testid surface to keep in sync with its own test file.
 */

import React from 'react'
import { useTokens, Card, Text, Badge } from '../styles/primitives'
import { EMPTY_GAUGES_VM } from './model/supervisorGauges'
import { SupervisorPanel } from './SupervisorPanel'
import { EMPTY_SUPERVISOR_VM } from './model/supervisorThread'

function makeStyles(t) {
  return {
    wrap: { display: 'flex', flexDirection: 'column', gap: t.space.md },
    gaugesRow: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
      gap: t.space.sm,
    },
    gauge: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xxs,
      padding: t.space.sm,
    },
    gaugeHead: { display: 'flex', alignItems: 'center', gap: t.space.xs, flexWrap: 'wrap' },
  }
}

/** One gauge tile: label + tone chip, the headline value, and a muted detail line. */
function Gauge({ gauge, styles }) {
  return (
    <Card data-testid={`supervisor-gauge-${gauge.key}`} style={styles.gauge}>
      <div style={styles.gaugeHead}>
        <Text size="xs" weight="semibold" tone="muted" uppercase>{gauge.label}</Text>
        <Badge tone={gauge.tone} data-testid={`supervisor-gauge-${gauge.key}-tone`}>{gauge.tone}</Badge>
      </div>
      <Text size="lg" weight="semibold" data-testid={`supervisor-gauge-${gauge.key}-value`}>
        {gauge.value}
      </Text>
      {gauge.detail && (
        <Text size="xs" tone="muted" data-testid={`supervisor-gauge-${gauge.key}-detail`}>
          {gauge.detail}
        </Text>
      )}
    </Card>
  )
}

/**
 * @param {{ gauges?: ReturnType<typeof import('./model/supervisorGauges').toSupervisorGauges>,
 *           supervisor?: ReturnType<typeof import('./model/supervisorThread').toSupervisorThread>,
 *           onResume?: Function, onPause?: Function,
 *           onRestartLoop?: (name: string) => void,
 *           onAckEscalations?: (ts: string, escalations: string[]) => void }} props
 */
export function SupervisorMode({
  gauges = EMPTY_GAUGES_VM,
  supervisor = EMPTY_SUPERVISOR_VM,
  onResume,
  onPause,
  onRestartLoop,
  onAckEscalations,
}) {
  const t = useTokens()
  const styles = makeStyles(t)

  return (
    <div data-testid="supervisor-mode" style={styles.wrap}>
      <div data-testid="supervisor-gauges" style={styles.gaugesRow}>
        {gauges.gauges.map(gauge => (
          <Gauge key={gauge.key} gauge={gauge} styles={styles} />
        ))}
      </div>
      <SupervisorPanel
        supervisor={supervisor}
        onResume={onResume}
        onPause={onPause}
        onRestartLoop={onRestartLoop}
        onAckEscalations={onAckEscalations}
      />
    </div>
  )
}

export default SupervisorMode

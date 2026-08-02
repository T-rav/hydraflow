import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { SupervisorPanel } from '../SupervisorPanel'

// SupervisorPanel (#10733) consumes the `toSupervisorThread(...)` view model and
// renders the goal-supervisor's observation thread. Tests pass VM literals (not
// raw payloads) to stay decoupled from the adapter internals, mirroring the
// VitalsCard / CostPanel component-test pattern.

const observation = (over = {}) => {
  const escalations = over.escalations ?? []
  const ackedEscalations = over.ackedEscalations ?? []
  const ackedSet = new Set(ackedEscalations)
  const unackedEscalations = escalations.filter(e => !ackedSet.has(e))
  return {
    id: `${over.ts ?? '2026-08-02T17:31:46Z'}#0`,
    ts: '2026-08-02T17:31:46Z',
    assessment: 'flake_tracker is erroring',
    snapshot: {
      healthy: false,
      stalledLoops: [],
      errorLoops: ['flake_tracker'],
      creditFailoverActive: false,
      creditProbeOverdue: false,
      bootShaStale: false,
      commitsBehind: 0,
      eventLoopStalled: false,
      vitalsVerdict: 'green',
    },
    insights: ['verified: flake_tracker cleared last tick'],
    nudges: ['restart_stalled_loop [flake_tracker] — wedged heartbeat'],
    escalations,
    ackedEscalations,
    unackedEscalations,
    deferred: ['rerun_flaky_check — CI auto-retry'],
    counts: { insights: 1, nudges: 1, escalations: escalations.length, deferred: 1 },
    hasEscalations: unackedEscalations.length > 0,
    ...over,
  }
}

const vm = (over = {}) => ({
  verdict: 'degraded',
  verdictLabel: 'degraded',
  escalationCount: 0,
  count: 1,
  latest: observation(),
  observations: [observation()],
  ...over,
})

describe('SupervisorPanel — verdict + thread', () => {
  it('renders the header and the glanceable liveness verdict', () => {
    render(<SupervisorPanel supervisor={vm({ verdict: 'healthy', verdictLabel: 'healthy' })} />)
    const panel = screen.getByTestId('supervisor-panel')
    expect(panel).toHaveTextContent('Supervisor')
    expect(screen.getByTestId('supervisor-verdict')).toHaveTextContent('healthy')
  })

  it('surfaces the escalation verdict up top when a human is wanted', () => {
    render(<SupervisorPanel supervisor={vm({
      verdict: 'escalations',
      verdictLabel: '2 escalations pending',
      escalationCount: 2,
    })} />)
    expect(screen.getByTestId('supervisor-verdict')).toHaveTextContent('2 escalations pending')
  })

  it('renders one collapsed row per observation, showing ts + assessment + bucket counts', () => {
    render(<SupervisorPanel supervisor={vm()} />)
    const row = screen.getByTestId('supervisor-obs-0')
    expect(row).toHaveTextContent('2026-08-02T17:31:46Z')
    expect(row).toHaveTextContent('flake_tracker is erroring')
    expect(row).toHaveTextContent('1 nudge')
    expect(row).toHaveTextContent('1 deferred')
    // Collapsed by default — the detail is not mounted.
    expect(screen.queryByTestId('supervisor-obs-0-detail')).toBeNull()
  })

  it('expands a row on click to mine its full detail, and re-collapses on a second click', () => {
    render(<SupervisorPanel supervisor={vm()} />)
    fireEvent.click(screen.getByTestId('supervisor-obs-0-toggle'))

    const detail = screen.getByTestId('supervisor-obs-0-detail')
    expect(detail).toBeInTheDocument()
    expect(within(detail).getByTestId('supervisor-obs-0-insights')).toHaveTextContent('flake_tracker cleared last tick')
    expect(within(detail).getByTestId('supervisor-obs-0-nudges')).toHaveTextContent('restart_stalled_loop [flake_tracker]')
    expect(within(detail).getByTestId('supervisor-obs-0-deferred')).toHaveTextContent('rerun_flaky_check')
    // The snapshot signals surface the erroring loop.
    expect(within(detail).getByTestId('supervisor-snapshot')).toHaveTextContent('flake_tracker')
    expect(screen.getByTestId('supervisor-obs-0-toggle')).toHaveAttribute('aria-expanded', 'true')

    fireEvent.click(screen.getByTestId('supervisor-obs-0-toggle'))
    expect(screen.queryByTestId('supervisor-obs-0-detail')).toBeNull()
  })

  it('marks an escalation observation as visually distinct and shows its escalation detail', () => {
    render(<SupervisorPanel supervisor={vm({
      observations: [observation({
        escalations: ['force_push [main] — RC wedged, needs a human'],
        counts: { insights: 1, nudges: 1, escalations: 1, deferred: 1 },
        hasEscalations: true,
      })],
    })} />)
    const row = screen.getByTestId('supervisor-obs-0')
    expect(row).toHaveAttribute('data-escalation', 'true')
    expect(row).toHaveTextContent('1 escalation')

    fireEvent.click(screen.getByTestId('supervisor-obs-0-toggle'))
    expect(screen.getByTestId('supervisor-obs-0-escalations')).toHaveTextContent('force_push [main]')
  })

  it('does NOT mark a clean observation as an escalation', () => {
    render(<SupervisorPanel supervisor={vm()} />)
    expect(screen.getByTestId('supervisor-obs-0')).toHaveAttribute('data-escalation', 'false')
  })

  it('shows a calm empty state when the thread is empty', () => {
    render(<SupervisorPanel supervisor={vm({
      verdict: 'empty', verdictLabel: 'no observations', count: 0, latest: null, observations: [],
    })} />)
    expect(screen.getByTestId('supervisor-empty')).toHaveTextContent('no supervisor observations')
    expect(screen.queryByTestId('supervisor-obs-0')).toBeNull()
  })

  it('renders the empty state without a supervisor prop (backward-compatible default)', () => {
    render(<SupervisorPanel />)
    expect(screen.getByTestId('supervisor-panel')).toBeInTheDocument()
    expect(screen.getByTestId('supervisor-empty')).toBeInTheDocument()
  })
})

describe('SupervisorPanel — human action buttons', () => {
  it('renders Resume + Pause live and wired to the provided control handlers', () => {
    const onResume = vi.fn()
    const onPause = vi.fn()
    render(<SupervisorPanel supervisor={vm()} onResume={onResume} onPause={onPause} />)

    const resume = screen.getByTestId('supervisor-action-resume')
    const pause = screen.getByTestId('supervisor-action-pause')
    expect(resume).not.toBeDisabled()
    expect(pause).not.toBeDisabled()

    fireEvent.click(resume)
    fireEvent.click(pause)
    expect(onResume).toHaveBeenCalledTimes(1)
    expect(onPause).toHaveBeenCalledTimes(1)
  })

  it('disables Resume / Pause when no control handler is threaded', () => {
    render(<SupervisorPanel supervisor={vm()} />)
    expect(screen.getByTestId('supervisor-action-resume')).toBeDisabled()
    expect(screen.getByTestId('supervisor-action-pause')).toBeDisabled()
  })

  it('no longer renders the deferred global restart-loop / ack buttons in the action bar', () => {
    render(<SupervisorPanel supervisor={vm()} onResume={vi.fn()} onPause={vi.fn()} />)
    // Restart + Ack are now CONTEXTUAL (per-loop / per-observation), not global.
    expect(screen.queryByTestId('supervisor-action-restart-loop')).toBeNull()
    expect(screen.queryByTestId('supervisor-action-ack')).toBeNull()
  })
})

describe('SupervisorPanel — contextual restart-loop action', () => {
  it('renders a restart affordance next to a degraded loop chip and POSTs its name', () => {
    const onRestartLoop = vi.fn()
    render(<SupervisorPanel supervisor={vm()} onRestartLoop={onRestartLoop} />)
    fireEvent.click(screen.getByTestId('supervisor-obs-0-toggle'))

    const restart = screen.getByTestId('supervisor-obs-0-restart-flake_tracker')
    expect(restart).not.toBeDisabled()
    fireEvent.click(restart)
    expect(onRestartLoop).toHaveBeenCalledTimes(1)
    expect(onRestartLoop).toHaveBeenCalledWith('flake_tracker')
  })

  it('disables the restart affordance when no handler is threaded', () => {
    render(<SupervisorPanel supervisor={vm()} />)
    fireEvent.click(screen.getByTestId('supervisor-obs-0-toggle'))
    expect(screen.getByTestId('supervisor-obs-0-restart-flake_tracker')).toBeDisabled()
  })

  it('offers a restart per distinct stalled loop', () => {
    const stalled = observation({
      snapshot: {
        healthy: false, stalledLoops: ['diagram', 'metrics'], errorLoops: [],
        creditFailoverActive: false, creditProbeOverdue: false, bootShaStale: false,
        commitsBehind: 0, eventLoopStalled: false, vitalsVerdict: 'green',
      },
    })
    const onRestartLoop = vi.fn()
    render(<SupervisorPanel supervisor={vm({ observations: [stalled], latest: stalled })} onRestartLoop={onRestartLoop} />)
    fireEvent.click(screen.getByTestId('supervisor-obs-0-toggle'))
    fireEvent.click(screen.getByTestId('supervisor-obs-0-restart-diagram'))
    fireEvent.click(screen.getByTestId('supervisor-obs-0-restart-metrics'))
    expect(onRestartLoop.mock.calls).toEqual([['diagram'], ['metrics']])
  })
})

describe('SupervisorPanel — contextual ack-escalation action', () => {
  const escalating = (over = {}) => observation({
    escalations: ['force_push [main] — RC wedged', 'delete_branch — orphan'],
    ...over,
  })

  it('acks all of an observation\'s unacked escalations, POSTing the observation ts', () => {
    const onAckEscalations = vi.fn()
    const obs = escalating()
    render(<SupervisorPanel supervisor={vm({ observations: [obs], latest: obs })} onAckEscalations={onAckEscalations} />)
    fireEvent.click(screen.getByTestId('supervisor-obs-0-toggle'))

    const ack = screen.getByTestId('supervisor-obs-0-ack')
    expect(ack).not.toBeDisabled()
    fireEvent.click(ack)
    expect(onAckEscalations).toHaveBeenCalledTimes(1)
    expect(onAckEscalations).toHaveBeenCalledWith('2026-08-02T17:31:46Z', [
      'force_push [main] — RC wedged',
      'delete_branch — orphan',
    ])
  })

  it('renders an acked escalation visibly struck and only acks what remains unacked', () => {
    const onAckEscalations = vi.fn()
    const obs = escalating({ ackedEscalations: ['force_push [main] — RC wedged'] })
    render(<SupervisorPanel supervisor={vm({ observations: [obs], latest: obs })} onAckEscalations={onAckEscalations} />)
    fireEvent.click(screen.getByTestId('supervisor-obs-0-toggle'))

    // The acked one is marked; the unacked one is not.
    expect(screen.getByTestId('supervisor-obs-0-escalation-0')).toHaveAttribute('data-acked', 'true')
    expect(screen.getByTestId('supervisor-obs-0-escalation-1')).toHaveAttribute('data-acked', 'false')

    fireEvent.click(screen.getByTestId('supervisor-obs-0-ack'))
    expect(onAckEscalations).toHaveBeenCalledWith('2026-08-02T17:31:46Z', ['delete_branch — orphan'])
  })

  it('disables Ack (and drops the escalation flag) once every escalation is acked', () => {
    const acked = ['force_push [main] — RC wedged', 'delete_branch — orphan']
    const obs = escalating({ ackedEscalations: acked })
    render(<SupervisorPanel supervisor={vm({ observations: [obs], latest: obs })} onAckEscalations={vi.fn()} />)
    // A fully-acked observation is no longer visually distinct.
    expect(screen.getByTestId('supervisor-obs-0')).toHaveAttribute('data-escalation', 'false')
    fireEvent.click(screen.getByTestId('supervisor-obs-0-toggle'))
    expect(screen.getByTestId('supervisor-obs-0-ack')).toBeDisabled()
  })

  it('disables Ack when no handler is threaded', () => {
    const obs = escalating()
    render(<SupervisorPanel supervisor={vm({ observations: [obs], latest: obs })} />)
    fireEvent.click(screen.getByTestId('supervisor-obs-0-toggle'))
    expect(screen.getByTestId('supervisor-obs-0-ack')).toBeDisabled()
  })
})

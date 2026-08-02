import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { SupervisorPanel } from '../SupervisorPanel'

// SupervisorPanel (#10733) consumes the `toSupervisorThread(...)` view model and
// renders the goal-supervisor's observation thread. Tests pass VM literals (not
// raw payloads) to stay decoupled from the adapter internals, mirroring the
// VitalsCard / CostPanel component-test pattern.

const observation = (over = {}) => ({
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
  escalations: [],
  deferred: ['rerun_flaky_check — CI auto-retry'],
  counts: { insights: 1, nudges: 1, escalations: 0, deferred: 1 },
  hasEscalations: false,
  ...over,
})

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

  it('renders restart-loop + ack-escalation as deferred (disabled) no-ops with an explanatory title', () => {
    render(<SupervisorPanel supervisor={vm()} onResume={vi.fn()} onPause={vi.fn()} />)
    const restart = screen.getByTestId('supervisor-action-restart-loop')
    const ack = screen.getByTestId('supervisor-action-ack')
    expect(restart).toBeDisabled()
    expect(ack).toBeDisabled()
    expect(restart).toHaveAttribute('title', expect.stringContaining('Deferred'))
    expect(ack).toHaveAttribute('title', expect.stringContaining('Deferred'))
  })
})

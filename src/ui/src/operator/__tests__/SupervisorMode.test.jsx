import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SupervisorMode } from '../SupervisorMode'
import { toSupervisorGauges } from '../model/supervisorGauges'

// SupervisorMode (#11207) is the full-width Supervisor detail-slot tab: a
// gauges row (the point of the tab) plus the existing SupervisorPanel
// (observation thread + action toolbar), reused unchanged.

describe('SupervisorMode', () => {
  it('renders without crashing on default props', () => {
    render(<SupervisorMode />)
    expect(screen.getByTestId('supervisor-mode')).toBeInTheDocument()
  })

  it('renders all five gauges from the injected gauges VM', () => {
    const gauges = toSupervisorGauges({
      fleet: { tickHealth: { total: 10, ok: 10, warmup: 0, errored: 0, loopCount: 1 } },
    })
    render(<SupervisorMode gauges={gauges} />)
    for (const key of ['tick-health', 'open-escalations', 'credit-state', 'attempt-budget', 'cost-burn']) {
      expect(screen.getByTestId(`supervisor-gauge-${key}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('supervisor-gauge-tick-health-value')).toHaveTextContent('10 ok / 0 warmup / 0 errored')
    expect(screen.getByTestId('supervisor-gauge-tick-health-tone')).toHaveTextContent('success')
  })

  it('omits the detail line for a gauge with an empty detail', () => {
    const gauges = toSupervisorGauges({ vitals: { credits: { paused: false } } })
    render(<SupervisorMode gauges={gauges} />)
    // credit-state's "ok" gauge carries no detail line.
    expect(screen.queryByTestId('supervisor-gauge-credit-state-detail')).toBeNull()
  })

  it('mounts the existing SupervisorPanel (observation thread + toolbar) beneath the gauges', () => {
    render(<SupervisorMode />)
    expect(screen.getByTestId('supervisor-panel')).toBeInTheDocument()
    expect(screen.getByTestId('supervisor-empty')).toBeInTheDocument()
  })

  it('wires the Resume/Pause action handlers through to the reused SupervisorPanel', () => {
    const onResume = vi.fn()
    const onPause = vi.fn()
    render(<SupervisorMode onResume={onResume} onPause={onPause} />)
    fireEvent.click(screen.getByTestId('supervisor-action-resume'))
    fireEvent.click(screen.getByTestId('supervisor-action-pause'))
    expect(onResume).toHaveBeenCalledTimes(1)
    expect(onPause).toHaveBeenCalledTimes(1)
  })
})

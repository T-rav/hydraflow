import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SupervisorSummary } from '../SupervisorSummary'

// SupervisorSummary (#11207) is the rail's compact one-line Supervisor
// readout that replaced the full SupervisorPanel there: a status chip + open-
// escalation count that deep-links to the full-width Supervisor tab.

const vm = (over = {}) => ({
  verdict: 'healthy',
  verdictLabel: 'healthy',
  escalationCount: 0,
  count: 0,
  latest: null,
  observations: [],
  ...over,
})

describe('SupervisorSummary', () => {
  it('renders the verdict badge', () => {
    render(<SupervisorSummary supervisor={vm({ verdict: 'degraded', verdictLabel: 'degraded' })} />)
    expect(screen.getByTestId('supervisor-summary-verdict')).toHaveTextContent('degraded')
  })

  it('renders the empty state without a supervisor prop (backward-compatible default)', () => {
    render(<SupervisorSummary />)
    expect(screen.getByTestId('supervisor-summary')).toBeInTheDocument()
    expect(screen.getByTestId('supervisor-summary-verdict')).toHaveTextContent('no observations')
  })

  it('omits the escalation count when there are none pending', () => {
    render(<SupervisorSummary supervisor={vm({ escalationCount: 0 })} />)
    expect(screen.queryByTestId('supervisor-summary-escalations')).toBeNull()
  })

  it('shows the open-escalation count when escalations are pending', () => {
    render(<SupervisorSummary supervisor={vm({ verdict: 'escalations', verdictLabel: '2 escalations pending', escalationCount: 2 })} />)
    expect(screen.getByTestId('supervisor-summary-escalations')).toHaveTextContent('2 escalations')
  })

  it('singularizes a single pending escalation', () => {
    render(<SupervisorSummary supervisor={vm({ escalationCount: 1 })} />)
    expect(screen.getByTestId('supervisor-summary-escalations')).toHaveTextContent('1 escalation')
  })

  it('calls onOpen when clicked (deep-links to the Supervisor tab)', () => {
    const onOpen = vi.fn()
    render(<SupervisorSummary supervisor={vm()} onOpen={onOpen} />)
    fireEvent.click(screen.getByTestId('supervisor-summary'))
    expect(onOpen).toHaveBeenCalledTimes(1)
  })

  it('does not throw when clicked without an onOpen handler', () => {
    render(<SupervisorSummary supervisor={vm()} />)
    expect(() => fireEvent.click(screen.getByTestId('supervisor-summary'))).not.toThrow()
  })
})

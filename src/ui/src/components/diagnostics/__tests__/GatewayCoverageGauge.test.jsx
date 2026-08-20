import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { GatewayCoverageGauge } from '../GatewayCoverageGauge'
import { toGatewayCoverage } from '../gatewayCoverageModel'

describe('GatewayCoverageGauge', () => {
  it('renders an accessible complete meter and bypass families', () => {
    const coverage = toGatewayCoverage({
      status: 'complete',
      scope: 'global',
      window_label: '24h',
      coverage_percent: 80,
      known_spend_coverage_percent: 80,
      gateway_spend_usd: 8,
      known_total_spend_usd: 10,
      gateway_requests: 4,
      bypass_requests: 1,
      bypassing_families: [{ family: 'wiki_compilation', calls: 1 }],
    })
    render(<GatewayCoverageGauge coverage={coverage} />)

    expect(screen.getByTestId('gateway-coverage-gauge')).toBeInTheDocument()
    const meter = screen.getByRole('meter', { name: /LLM spend through gateway/i })
    expect(meter).toHaveAttribute('aria-valuenow', '80')
    expect(screen.getByTestId('gateway-coverage-value')).toHaveTextContent('80.0%')
    expect(screen.getByText('wiki_compilation')).toBeInTheDocument()
  })

  it('shows partial known-spend context without a complete claim', () => {
    const coverage = toGatewayCoverage({
      status: 'partial',
      known_spend_coverage_percent: 100,
      unpriced_gateway_requests: 1,
    })
    render(<GatewayCoverageGauge coverage={coverage} />)
    expect(screen.getByText('Partial pricing')).toBeInTheDocument()
    expect(screen.getByTestId('gateway-coverage-value')).toHaveTextContent('known spend')
    expect(screen.getByText(/no total coverage claim/i)).toBeInTheDocument()
  })

  it('shows unknown coverage when every observed request is unpriced', () => {
    const coverage = toGatewayCoverage({
      status: 'partial',
      known_spend_coverage_percent: null,
      unpriced_bypass_requests: 1,
    })
    render(<GatewayCoverageGauge coverage={coverage} />)

    expect(screen.getByTestId('gateway-coverage-value')).toHaveTextContent('Coverage unknown')
    expect(screen.getByRole('status', { name: /LLM spend through gateway/i }))
      .not.toHaveAttribute('aria-valuenow')
  })

  it('renders a no-data status without invented meter values', () => {
    render(<GatewayCoverageGauge />)
    expect(screen.getByRole('status', { name: /LLM spend through gateway/i }))
      .not.toHaveAttribute('aria-valuenow')
    expect(screen.getByText('No spend')).toBeInTheDocument()
  })

  it('renders a fail-soft error state', () => {
    render(<GatewayCoverageGauge error={new Error('boom')} />)
    expect(screen.getByRole('alert')).toHaveTextContent(/could not be loaded/i)
  })

  it('surfaces a post-ceiling direct-provider regression', () => {
    const coverage = toGatewayCoverage({
      status: 'complete',
      coverage_percent: 75,
      known_spend_coverage_percent: 75,
      ceiling_achieved: true,
      regression_detected: true,
      bypass_requests: 1,
    })

    render(<GatewayCoverageGauge coverage={coverage} />)

    expect(screen.getByText('Regression')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/reappeared after/i)
  })

  it('surfaces post-ceiling evidence loss without inventing direct traffic', () => {
    const coverage = toGatewayCoverage({
      status: 'partial',
      known_spend_coverage_percent: 100,
      source_data_complete: false,
      ceiling_achieved: true,
      regression_detected: true,
      bypass_requests: 0,
    })

    render(<GatewayCoverageGauge coverage={coverage} />)

    expect(screen.getByText('Regression')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/evidence became incomplete/i)
    expect(screen.getByRole('alert')).not.toHaveTextContent(/traffic reappeared/i)
  })
})

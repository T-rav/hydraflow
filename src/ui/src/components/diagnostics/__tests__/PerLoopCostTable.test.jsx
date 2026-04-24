import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { PerLoopCostTable } from '../PerLoopCostTable'

// Sanity-check render tests for the §4.11p2 Task 12 per-loop table.

describe('PerLoopCostTable', () => {
  const rows = [
    {
      loop: 'implementer',
      cost_usd: 3.1234,
      llm_calls: 42,
      ticks: 9,
      tick_cost_avg_usd: 0.3471,
      tick_cost_avg_usd_prev_period: 0.1,
      wall_clock_seconds: 600,
      sparkline_points: [0.1, 0.2, 0.35],
    },
    {
      loop: 'reviewer',
      cost_usd: 0.5,
      llm_calls: 5,
      ticks: 2,
      tick_cost_avg_usd: 0.25,
      tick_cost_avg_usd_prev_period: 0.3,
      wall_clock_seconds: 120,
      sparkline_points: [],
    },
  ]

  it('renders rows, column headers, and spike highlight', () => {
    render(<PerLoopCostTable rows={rows} />)
    // Column headers
    expect(screen.getByText(/Loop/i)).toBeInTheDocument()
    expect(screen.getByText(/Cost \(USD\)/i)).toBeInTheDocument()
    expect(screen.getByText(/LLM Calls/i)).toBeInTheDocument()
    expect(screen.getByText(/Avg \$\/Tick/i)).toBeInTheDocument()
    // Row loop names
    expect(screen.getByText('implementer')).toBeInTheDocument()
    expect(screen.getByText('reviewer')).toBeInTheDocument()
    // Spike: implementer cur 0.3471 vs prev 0.1 → >= 2x → flagged via data attr.
    const implementerRow = screen.getByText('implementer').closest('tr')
    expect(implementerRow).toHaveAttribute('data-spike', 'true')
    const reviewerRow = screen.getByText('reviewer').closest('tr')
    expect(reviewerRow).toHaveAttribute('data-spike', 'false')
    // Sparkline rendered for the row that has points.
    expect(screen.getByTestId('sparkline-implementer')).toBeInTheDocument()
  })

  it('renders empty state when no rows', () => {
    render(<PerLoopCostTable rows={[]} />)
    expect(screen.getByText(/No loop cost data in range/i)).toBeInTheDocument()
  })
})

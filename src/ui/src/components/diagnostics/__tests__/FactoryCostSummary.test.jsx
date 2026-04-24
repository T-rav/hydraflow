import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { FactoryCostSummary } from '../FactoryCostSummary'

// Sanity-check render tests for the §4.11p2 Task 11 summary tile.
// Component is purely controlled (no fetch), so we just pass props.

describe('FactoryCostSummary', () => {
  it('renders the four headline KPI cards with formatted values', () => {
    const rolling24h = {
      total: { cost_usd: 12.3456, tokens_in: 2_500_000, tokens_out: 750_000 },
      by_loop: [
        { loop: 'implementer', llm_calls: 12 },
        { loop: 'reviewer', llm_calls: 7 },
      ],
    }
    render(<FactoryCostSummary rolling24h={rolling24h} />)
    expect(screen.getByText(/Cost \(24h\)/i)).toBeInTheDocument()
    expect(screen.getByText(/\$12\.35/)).toBeInTheDocument()
    // 2_500_000 tokens_in formats as "2.5M"
    expect(screen.getByText('2.5M')).toBeInTheDocument()
    // 750_000 tokens_out formats as "750K"
    expect(screen.getByText('750K')).toBeInTheDocument()
    // 12 + 7 = 19 llm calls
    expect(screen.getByText('19')).toBeInTheDocument()
  })

  it('shows loading state when rolling24h is null', () => {
    render(<FactoryCostSummary rolling24h={null} />)
    expect(screen.getByText(/Loading cost summary/i)).toBeInTheDocument()
  })

  it('shows error state when error is set', () => {
    render(<FactoryCostSummary rolling24h={null} error={new Error('boom')} />)
    expect(screen.getByText(/Cost summary failed to load/i)).toBeInTheDocument()
  })
})

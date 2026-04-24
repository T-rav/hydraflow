import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { WaterfallView } from '../WaterfallView'

// Sanity-check render tests for the §4.11p2 Task 13 waterfall view.
// Component supports two modes: controlled (payload prop) and
// self-fetching (issueNumber prop). We exercise both.

const samplePayload = {
  issue: 4242,
  title: 'Example issue',
  labels: ['hydraflow-ready'],
  total: {
    cost_usd: 0.1234,
    tokens_in: 1200,
    tokens_out: 340,
    wall_clock_seconds: 125,
  },
  phases: [
    {
      phase: 'triage',
      cost_usd: 0.01,
      tokens_in: 100,
      tokens_out: 40,
      wall_clock_seconds: 5,
      actions: [],
    },
    {
      phase: 'implement',
      cost_usd: 0.1,
      tokens_in: 1100,
      tokens_out: 300,
      wall_clock_seconds: 120,
      actions: [],
    },
  ],
  missing_phases: ['merge'],
}

describe('WaterfallView', () => {
  let originalFetch
  beforeEach(() => {
    originalFetch = global.fetch
  })
  afterEach(() => {
    global.fetch = originalFetch
  })

  it('renders the controlled payload with phases, total, and missing list', () => {
    render(<WaterfallView payload={samplePayload} />)
    expect(screen.getByText(/Issue #4242/)).toBeInTheDocument()
    expect(screen.getByText(/Example issue/)).toBeInTheDocument()
    // Phase labels
    expect(screen.getByText('triage')).toBeInTheDocument()
    expect(screen.getByText('implement')).toBeInTheDocument()
    // Total cost formatting (fmtUsd → $0.1234)
    expect(screen.getByText(/\$0\.1234/)).toBeInTheDocument()
    // Missing phases row
    expect(screen.getByText(/Missing:/)).toBeInTheDocument()
    expect(screen.getByText(/merge/)).toBeInTheDocument()
  })

  it('renders the empty prompt when no payload and no issueNumber', () => {
    render(<WaterfallView />)
    expect(screen.getByText(/Select an issue to view its cost waterfall/i)).toBeInTheDocument()
  })

  it('self-fetches when given issueNumber and renders the resulting payload', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(samplePayload),
    })
    render(<WaterfallView issueNumber={4242} />)
    await waitFor(() => {
      expect(screen.getByText(/Issue #4242/)).toBeInTheDocument()
    })
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/diagnostics/issue/4242/waterfall'),
    )
  })
})

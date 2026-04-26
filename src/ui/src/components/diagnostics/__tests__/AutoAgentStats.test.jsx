import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const MOCK_DATA = {
  today: {
    spend_usd: 1.23,
    attempts: 5,
    resolved: 3,
    resolution_rate: 0.6,
    p50_cost_usd: 0.20,
    p95_cost_usd: 0.80,
    p50_wall_clock_s: 45,
    p95_wall_clock_s: 120,
  },
  last_7d: {
    spend_usd: 8.75,
    attempts: 30,
    resolved: 22,
    resolution_rate: 0.733,
    p50_cost_usd: 0.25,
    p95_cost_usd: 0.90,
    p50_wall_clock_s: 50,
    p95_wall_clock_s: 130,
  },
  top_spend: [
    {
      issue: 42,
      sub_label: 'hydraflow-plan',
      cost_usd: 0.55,
      wall_clock_s: 90,
      status: 'resolved',
      ts: '2026-04-25T10:00:00Z',
    },
  ],
}

global.fetch = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
})

import { AutoAgentStats } from '../AutoAgentStats'

describe('AutoAgentStats', () => {
  it('renders loading state initially', async () => {
    global.fetch.mockReturnValue(new Promise(() => {}))
    render(<AutoAgentStats />)
    expect(screen.getByTestId('auto-agent-stats-loading')).toBeInTheDocument()
  })

  it('renders stats after successful fetch', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(MOCK_DATA),
    })
    render(<AutoAgentStats />)
    await waitFor(() => {
      expect(screen.getByTestId('auto-agent-stats')).toBeInTheDocument()
    })
    // Today window
    expect(screen.getByText('Today (24h)')).toBeInTheDocument()
    expect(screen.getByText('$1.23')).toBeInTheDocument()
    // Last 7d window
    expect(screen.getByText('Last 7 days')).toBeInTheDocument()
    expect(screen.getByText('$8.75')).toBeInTheDocument()
  })

  it('renders top spend table when rows present', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(MOCK_DATA),
    })
    render(<AutoAgentStats />)
    await waitFor(() => {
      expect(screen.getByTestId('auto-agent-top-spend')).toBeInTheDocument()
    })
    expect(screen.getByText('#42')).toBeInTheDocument()
    expect(screen.getByText('hydraflow-plan')).toBeInTheDocument()
    expect(screen.getByText('resolved')).toBeInTheDocument()
  })

  it('renders error state on failed fetch', async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      status: 500,
    })
    render(<AutoAgentStats />)
    await waitFor(() => {
      expect(screen.getByTestId('auto-agent-stats-error')).toBeInTheDocument()
    })
    expect(screen.getByText(/Auto-Agent stats unavailable/)).toBeInTheDocument()
  })

  it('renders error state on network failure', async () => {
    global.fetch.mockRejectedValue(new Error('Network error'))
    render(<AutoAgentStats />)
    await waitFor(() => {
      expect(screen.getByTestId('auto-agent-stats-error')).toBeInTheDocument()
    })
  })

  it('omits top spend section when rows is empty', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...MOCK_DATA, top_spend: [] }),
    })
    render(<AutoAgentStats />)
    await waitFor(() => {
      expect(screen.getByTestId('auto-agent-stats')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('auto-agent-top-spend')).not.toBeInTheDocument()
  })
})

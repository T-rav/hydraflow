import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts" />,
}))

const MOCK_AUTO_AGENT = {
  today: { spend_usd: 0, attempts: 0, resolved: 0, resolution_rate: 0, p50_cost_usd: 0, p95_cost_usd: 0, p50_wall_clock_s: 0, p95_wall_clock_s: 0 },
  last_7d: { spend_usd: 0, attempts: 0, resolved: 0, resolution_rate: 0, p50_cost_usd: 0, p95_cost_usd: 0, p50_wall_clock_s: 0, p95_wall_clock_s: 0 },
  top_spend: [],
}

global.fetch = vi.fn((url) => {
  if (url.includes('/overview')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        total_tokens: 247000, total_runs: 1, total_tool_invocations: 7, cache_hit_rate: 0.5,
      }),
    })
  }
  if (url.includes('/auto-agent')) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_AUTO_AGENT) })
  }
  return Promise.resolve({ ok: true, json: () => Promise.resolve([]) })
})

import { DiagnosticsTab } from '../DiagnosticsTab'

describe('DiagnosticsTab', () => {
  it('fetches and renders overview', async () => {
    render(<DiagnosticsTab />)
    await waitFor(() => {
      expect(screen.getByText(/247K/)).toBeInTheDocument()
    })
  })

  it('renders range filter dropdown', async () => {
    render(<DiagnosticsTab />)
    expect(await screen.findByLabelText(/Range/i)).toBeInTheDocument()
  })
})

import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts" />,
}))

// `ctx.selectedRepoSlug` is mutable per-test so we can exercise both the
// single-repo (null) and a concrete-repo selection.
const { mockFetchWithRepo, ctx } = vi.hoisted(() => ({
  mockFetchWithRepo: vi.fn(),
  ctx: { selectedRepoSlug: null },
}))
vi.mock('../../../context/HydraFlowContext', () => ({
  useHydraFlow: () => ({
    fetchWithRepo: mockFetchWithRepo,
    selectedRepoSlug: ctx.selectedRepoSlug,
  }),
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
  if (url.includes('/issues')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve([
        { issue: 7, repo: 'org-b', phase: 'implement', run_id: 1, tokens: 100, duration_seconds: 10, tool_count: 1, skill_pass_count: 0, skill_total: 0, crashed: false },
      ]),
    })
  }
  if (url.includes('/issue/')) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ summary: {}, subprocesses: [] }) })
  }
  return Promise.resolve({ ok: true, json: () => Promise.resolve([]) })
})

// The repo-aware fetcher mirrors the real applyRepoParam: it appends the
// selected repo slug to the URL before hitting the network. Modeling it here
// lets the tests assert the repo param actually reaches fetch (not just that
// the component called *some* fetcher).
mockFetchWithRepo.mockImplementation((url, opts) => {
  const sep = url.includes('?') ? '&' : '?'
  const scoped = ctx.selectedRepoSlug ? `${url}${sep}repo=${ctx.selectedRepoSlug}` : url
  return global.fetch(scoped, opts)
})

import { DiagnosticsTab } from '../DiagnosticsTab'

describe('DiagnosticsTab', () => {
  beforeEach(() => {
    ctx.selectedRepoSlug = null
    global.fetch.mockClear()
    mockFetchWithRepo.mockClear()
  })

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

  it('routes diagnostics through the repo-aware fetcher', async () => {
    render(<DiagnosticsTab />)
    await waitFor(() => {
      expect(mockFetchWithRepo).toHaveBeenCalledWith(
        expect.stringContaining('/api/diagnostics/overview')
      )
    })
    expect(mockFetchWithRepo).toHaveBeenCalledWith(
      expect.stringContaining('/api/diagnostics/issues')
    )
  })

  it('scopes diagnostics requests to the selected repo', async () => {
    ctx.selectedRepoSlug = 'org-x'
    render(<DiagnosticsTab />)
    // The repo slug must actually reach fetch — proves the data path
    // component → fetchWithRepo → repo param → network, not merely that a
    // fetcher was called.
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('repo=org-x'),
        undefined,
      )
    })
  })

  it('scopes the per-issue drill-down to the row owning repo', async () => {
    // Under "All repos" each row carries its own repo; the drill-down must use
    // that repo, never the aggregate sentinel.
    ctx.selectedRepoSlug = '__all__'
    render(<DiagnosticsTab />)
    const cell = await screen.findByText('7')
    fireEvent.click(cell.closest('tr'))
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/diagnostics/issue/7/implement/1?repo=org-b'
      )
    })
    // It must NOT fall back to the __all__ sentinel for the drill-down.
    expect(global.fetch).not.toHaveBeenCalledWith(
      expect.stringContaining('/issue/7/implement/1?repo=__all__')
    )
  })
})

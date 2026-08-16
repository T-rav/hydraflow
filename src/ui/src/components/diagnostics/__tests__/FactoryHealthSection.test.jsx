import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// `ctx.selectedRepoSlug` is mutable per-test. `fetchWithRepo` is a STABLE
// hoisted reference (like the real useCallback-memoized fetcher) so the effect
// that depends on it does not re-render-loop. It mirrors applyRepoParam and
// delegates to the per-test `global.fetch` stub.
const { ctx, fetchWithRepo } = vi.hoisted(() => {
  const ctx = { selectedRepoSlug: null }
  const fetchWithRepo = (url, opts) => {
    const sep = url.includes('?') ? '&' : '?'
    const scoped = ctx.selectedRepoSlug
      ? `${url}${sep}repo=${encodeURIComponent(ctx.selectedRepoSlug)}`
      : url
    return global.fetch(scoped, opts)
  }
  return { ctx, fetchWithRepo }
})
vi.mock('../../../context/HydraFlowContext', () => ({
  useHydraFlow: () => ({ selectedRepoSlug: ctx.selectedRepoSlug, fetchWithRepo }),
}))

import { FactoryHealthSection } from '../FactoryHealthSection'

describe('FactoryHealthSection', () => {
  let originalFetch
  beforeEach(() => {
    originalFetch = global.fetch
    ctx.selectedRepoSlug = null
  })
  afterEach(() => {
    global.fetch = originalFetch
  })

  it('renders nothing (does not throw) when API returns a truthy response without rolling_averages', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    })
    const { container } = render(<FactoryHealthSection />)
    // Wait one microtask for the fetch promise + setData re-render to settle.
    await new Promise((resolve) => setTimeout(resolve, 0))
    // Component must not throw. It should render nothing (loading disappears, no data shape → null).
    // A narrow behavioural assertion: no "Factory Health Trends" heading, no crash.
    expect(container.textContent).not.toMatch(/Factory Health Trends/)
  })

  it('fetches health scoped to the selected repo', async () => {
    ctx.selectedRepoSlug = 'org-x'
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    render(<FactoryHealthSection />)
    // The repo slug must reach fetch — proving the data path
    // component → fetchWithRepo → repo param → network.
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/factory-health/summary?repo=org-x',
        undefined,
      )
    })
  })

  it('shows tile calc info driven verbatim by metric_metadata, not hardcoded copy', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        rolling_averages: {
          plan_accuracy_pct: [{ value: 80 }, { value: 70 }],
        },
        cohorts: { memory_available: { count: 0 }, memory_unavailable: { count: 0 } },
        regressions: [],
        metric_metadata: {
          plan_accuracy_pct: {
            label: 'Plan Accuracy %',
            numerator: 'UNIQUE_NUMERATOR_TEXT',
            denominator: 'UNIQUE_DENOMINATOR_TEXT',
            window_runs: 7,
            delta_baseline: 'UNIQUE_BASELINE_TEXT',
            data_source: 'UNIQUE_SOURCE.jsonl',
          },
        },
      }),
    })
    render(<FactoryHealthSection />)
    const infoButton = await screen.findByRole('button', { name: /Plan Accuracy %/i })
    fireEvent.click(infoButton)

    // The popover text is exactly what the calc's metric_metadata carried —
    // no separately hand-written copy that could drift from it.
    expect(screen.getByText(/UNIQUE_NUMERATOR_TEXT/)).toBeInTheDocument()
    expect(screen.getByText(/UNIQUE_DENOMINATOR_TEXT/)).toBeInTheDocument()
    expect(screen.getByText(/last 7 runs/)).toBeInTheDocument()
    expect(screen.getByText(/UNIQUE_BASELINE_TEXT/)).toBeInTheDocument()
    expect(screen.getByText(/UNIQUE_SOURCE\.jsonl/)).toBeInTheDocument()

    // Clicking again closes it.
    fireEvent.click(infoButton)
    expect(screen.queryByText(/UNIQUE_NUMERATOR_TEXT/)).not.toBeInTheDocument()
  })

  it('renders an aligned companion graph row spanning the shared rolling-average window', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        rolling_averages: {
          plan_accuracy_pct: [{ value: 80 }, { value: 82 }, { value: 78 }],
          first_pass_rate: [{ value: 0.6 }, { value: 0.5 }, { value: 0.55 }],
          quality_fix_rounds: [{ value: 1 }, { value: 1.2 }, { value: 0.9 }],
          ci_fix_rounds: [{ value: 0.5 }, { value: 0.4 }, { value: 0.3 }],
          // One extra point of history than the others — the row must
          // truncate to the shortest series so the same index means the
          // same window offset across every tile.
          duration_seconds: [{ value: 95 }, { value: 100 }, { value: 110 }, { value: 90 }],
        },
        cohorts: { memory_available: { count: 0 }, memory_unavailable: { count: 0 } },
        regressions: [],
        metric_metadata: {},
      }),
    })
    render(<FactoryHealthSection />)
    expect(await screen.findByText(/Aligned Trend/)).toBeInTheDocument()
    expect(screen.getByText(/last 3 windows/)).toBeInTheDocument()
  })
})

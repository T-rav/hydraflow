import { render, waitFor } from '@testing-library/react'
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
})

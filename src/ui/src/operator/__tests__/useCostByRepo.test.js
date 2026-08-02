import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useCostByRepo, COST_ENDPOINT } from '../useCostByRepo'
import { EMPTY_COST_VM } from '../model/cost'
import { COST_POLL_MS } from '../../constants'

// The cost feed hook (#10785) owns ONLY the async lifecycle — the backend
// pre-aggregates the repo + per-repo cost-per-model payload into one endpoint.
// The prior monolithic attempts failed precisely here, so every edge is pinned:
// pinned cadence, poll teardown, stale-response/abort guard, no-fetch guard.

const PAYLOAD = {
  window_label: 'last 24h',
  total_cost_usd: 3.5,
  all: [{ model: 'sonnet', cost_usd: 3.5, cost_unknown: false, calls: 1, input_tokens: 100, output_tokens: 50 }],
  repos: [],
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useCostByRepo — async lifecycle', () => {
  it('fetches the fixed endpoint once on mount, passing an abort signal, and exposes the VM', async () => {
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    const { result } = renderHook(() => useCostByRepo({ fetcher }))

    await waitFor(() => expect(result.current.totalCostUsd).toBe(3.5))
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith(
      COST_ENDPOINT,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('starts on the EMPTY view model before the first response lands', () => {
    const fetcher = vi.fn(() => new Promise(() => {})) // never resolves
    const { result } = renderHook(() => useCostByRepo({ fetcher, intervalMs: 1_000_000 }))
    expect(result.current).toBe(EMPTY_COST_VM)
  })

  it('pins the poll cadence to COST_POLL_MS by default', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useCostByRepo({ fetcher }))
    expect(setSpy).toHaveBeenCalledWith(expect.any(Function), COST_POLL_MS)
  })

  it('polls again after the interval elapses', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useCostByRepo({ fetcher, intervalMs: 1_000 }))

    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(fetcher).toHaveBeenCalledTimes(1)

    await act(async () => { await vi.advanceTimersByTimeAsync(1_000) })
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('tears down the poll and aborts the in-flight request on unmount', async () => {
    let capturedSignal
    const fetcher = vi.fn((_url, { signal }) => {
      capturedSignal = signal
      return Promise.resolve(PAYLOAD)
    })
    const clearSpy = vi.spyOn(global, 'clearInterval')
    const { unmount } = renderHook(() => useCostByRepo({ fetcher, intervalMs: 1_000_000 }))

    await waitFor(() => expect(fetcher).toHaveBeenCalled())
    expect(capturedSignal.aborted).toBe(false)

    unmount()
    expect(capturedSignal.aborted).toBe(true)
    expect(clearSpy).toHaveBeenCalled()
  })

  it('ignores a response that resolves after unmount, without error (stale-response guard)', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    let resolveFetch
    const fetcher = vi.fn(() => new Promise(res => { resolveFetch = res }))
    const { result, unmount } = renderHook(() => useCostByRepo({ fetcher, intervalMs: 1_000_000 }))

    unmount() // request still in-flight

    await act(async () => {
      resolveFetch(PAYLOAD)
      await Promise.resolve()
    })

    // The late response never wrote state (VM stays EMPTY) and never warned.
    expect(result.current).toBe(EMPTY_COST_VM)
    expect(errSpy).not.toHaveBeenCalled()
  })

  it('no-fetch guard: a null fetcher renders EMPTY and schedules no poll', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const { result } = renderHook(() => useCostByRepo({ fetcher: null }))
    expect(result.current).toBe(EMPTY_COST_VM)
    expect(setSpy).not.toHaveBeenCalled()
  })

  it('keeps the last-known VM when a fetch rejects (no crash)', async () => {
    const fetcher = vi.fn(() => Promise.reject(new Error('boom')))
    const { result } = renderHook(() => useCostByRepo({ fetcher, intervalMs: 1_000_000 }))
    await act(async () => { await Promise.resolve() })
    expect(result.current).toBe(EMPTY_COST_VM)
  })
})

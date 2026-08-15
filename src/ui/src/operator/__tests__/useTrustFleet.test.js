import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useTrustFleet, TRUST_FLEET_ENDPOINT } from '../useTrustFleet'
import { EMPTY_TRUST_FLEET_VM } from '../model/trustFleet'
import { TRUST_FLEET_POLL_MS } from '../../constants'

// The trust-fleet feed hook (#11207) owns ONLY the async lifecycle — the
// backend serves the per-loop tick/repair tallies from one endpoint. It
// MIRRORS useSupervisorThread / useCostByRepo, whose prior monolithic
// attempts died on an untested hook lifecycle, so every edge is pinned:
// pinned cadence, poll teardown, stale-response/abort guard, no-fetch guard.

const PAYLOAD = {
  loops: [
    { worker_name: 'flake_tracker', ticks_total: 10, ticks_errored: 1, ticks_warmup: 0, repair_attempts_total: 3, repair_successes_total: 2, repair_failures_total: 1 },
  ],
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useTrustFleet — async lifecycle', () => {
  it('fetches the fixed endpoint once on mount, passing an abort signal, and exposes the VM', async () => {
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    const { result } = renderHook(() => useTrustFleet({ fetcher }))

    await waitFor(() => expect(result.current.tickHealth.total).toBe(10))
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith(
      TRUST_FLEET_ENDPOINT,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(result.current.attemptBudget).toEqual({ attempts: 3, successes: 2, failures: 1 })
  })

  it('starts on the EMPTY view model before the first response lands', () => {
    const fetcher = vi.fn(() => new Promise(() => {})) // never resolves
    const { result } = renderHook(() => useTrustFleet({ fetcher, intervalMs: 1_000_000 }))
    expect(result.current).toBe(EMPTY_TRUST_FLEET_VM)
  })

  it('pins the poll cadence to TRUST_FLEET_POLL_MS by default', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useTrustFleet({ fetcher }))
    expect(setSpy).toHaveBeenCalledWith(expect.any(Function), TRUST_FLEET_POLL_MS)
  })

  it('polls again after the interval elapses', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useTrustFleet({ fetcher, intervalMs: 1_000 }))

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
    const { unmount } = renderHook(() => useTrustFleet({ fetcher, intervalMs: 1_000_000 }))

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
    const { result, unmount } = renderHook(() => useTrustFleet({ fetcher, intervalMs: 1_000_000 }))

    unmount() // request still in-flight

    await act(async () => {
      resolveFetch(PAYLOAD)
      await Promise.resolve()
    })

    // The late response never wrote state (VM stays EMPTY) and never warned.
    expect(result.current).toBe(EMPTY_TRUST_FLEET_VM)
    expect(errSpy).not.toHaveBeenCalled()
  })

  it('no-fetch guard: a null fetcher renders EMPTY and schedules no poll', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const { result } = renderHook(() => useTrustFleet({ fetcher: null }))
    expect(result.current).toBe(EMPTY_TRUST_FLEET_VM)
    expect(setSpy).not.toHaveBeenCalled()
  })

  it('keeps the last-known VM when a fetch rejects (no crash)', async () => {
    const fetcher = vi.fn(() => Promise.reject(new Error('boom')))
    const { result } = renderHook(() => useTrustFleet({ fetcher, intervalMs: 1_000_000 }))
    await act(async () => { await Promise.resolve() })
    expect(result.current).toBe(EMPTY_TRUST_FLEET_VM)
  })
})

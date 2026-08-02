import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useSupervisorThread, SUPERVISOR_ENDPOINT } from '../useSupervisorThread'
import { EMPTY_SUPERVISOR_VM } from '../model/supervisorThread'
import { SUPERVISOR_POLL_MS } from '../../constants'

// The supervisor feed hook (#10733) owns ONLY the async lifecycle — the backend
// serves the append-only thread from one endpoint. It MIRRORS useCostByRepo
// (#10785), whose prior monolithic attempts died on an untested hook lifecycle,
// so every edge is pinned: pinned cadence, poll teardown, stale-response/abort
// guard, no-fetch guard.

const PAYLOAD = {
  observations: [
    {
      ts: '2026-08-02T17:31:46Z',
      snapshot: { healthy: false, error_loops: ['flake_tracker'], vitals_verdict: 'green' },
      assessment: 'flake_tracker erroring',
      insights: [],
      nudges_taken: ['restart_stalled_loop [flake_tracker]'],
      escalations: [],
      deferred: [],
    },
  ],
  count: 1,
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useSupervisorThread — async lifecycle', () => {
  it('fetches the fixed endpoint once on mount, passing an abort signal, and exposes the VM', async () => {
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    const { result } = renderHook(() => useSupervisorThread({ fetcher }))

    await waitFor(() => expect(result.current.count).toBe(1))
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith(
      SUPERVISOR_ENDPOINT,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(result.current.verdict).toBe('degraded')
  })

  it('starts on the EMPTY view model before the first response lands', () => {
    const fetcher = vi.fn(() => new Promise(() => {})) // never resolves
    const { result } = renderHook(() => useSupervisorThread({ fetcher, intervalMs: 1_000_000 }))
    expect(result.current).toBe(EMPTY_SUPERVISOR_VM)
  })

  it('pins the poll cadence to SUPERVISOR_POLL_MS by default', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useSupervisorThread({ fetcher }))
    expect(setSpy).toHaveBeenCalledWith(expect.any(Function), SUPERVISOR_POLL_MS)
  })

  it('polls again after the interval elapses', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useSupervisorThread({ fetcher, intervalMs: 1_000 }))

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
    const { unmount } = renderHook(() => useSupervisorThread({ fetcher, intervalMs: 1_000_000 }))

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
    const { result, unmount } = renderHook(() => useSupervisorThread({ fetcher, intervalMs: 1_000_000 }))

    unmount() // request still in-flight

    await act(async () => {
      resolveFetch(PAYLOAD)
      await Promise.resolve()
    })

    // The late response never wrote state (VM stays EMPTY) and never warned.
    expect(result.current).toBe(EMPTY_SUPERVISOR_VM)
    expect(errSpy).not.toHaveBeenCalled()
  })

  it('no-fetch guard: a null fetcher renders EMPTY and schedules no poll', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const { result } = renderHook(() => useSupervisorThread({ fetcher: null }))
    expect(result.current).toBe(EMPTY_SUPERVISOR_VM)
    expect(setSpy).not.toHaveBeenCalled()
  })

  it('keeps the last-known VM when a fetch rejects (no crash)', async () => {
    const fetcher = vi.fn(() => Promise.reject(new Error('boom')))
    const { result } = renderHook(() => useSupervisorThread({ fetcher, intervalMs: 1_000_000 }))
    await act(async () => { await Promise.resolve() })
    expect(result.current).toBe(EMPTY_SUPERVISOR_VM)
  })
})

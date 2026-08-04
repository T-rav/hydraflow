import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useFinderFaceplates, FINDER_FACEPLATE_ENDPOINT } from '../useFinderFaceplates'
import { EMPTY_FINDER_FACEPLATES_VM } from '../model/finderFaceplates'
import { FINDER_FACEPLATE_POLL_MS } from '../../constants'

// The finder-faceplate hook (#10826) is a STRUCTURAL MIRROR of useCostByRepo /
// useSupervisorThread: the backend does the join, so the hook owns only the
// async lifecycle. Every edge is pinned — pinned cadence, poll teardown,
// stale-response/abort guard, no-fetch guard.

const PAYLOAD = {
  generated_at: '2026-08-03T00:00:00+00:00',
  finders: [
    {
      finder_id: 'wiki_rot', signal_class: 'wiki-rot', calibrated: true, live_rate: 18,
      status: 'above_floor', floor_mean: 15.0, floor_sigma: 0.0, threshold: 15, sample_count: 2,
      low_confidence: true, last_calibrated: '2026-08-01T00:00:00+00:00', drift_days: 0,
      baseline_stale: null, baseline_sha: 'b653fca', baseline_vetted: false,
    },
  ],
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useFinderFaceplates — async lifecycle', () => {
  it('fetches the fixed endpoint once on mount, passing an abort signal, and exposes the VM', async () => {
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    const { result } = renderHook(() => useFinderFaceplates({ fetcher }))

    await waitFor(() => expect(result.current.calibratedCount).toBe(1))
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith(
      FINDER_FACEPLATE_ENDPOINT,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('starts on the EMPTY view model before the first response lands', () => {
    const fetcher = vi.fn(() => new Promise(() => {})) // never resolves
    const { result } = renderHook(() => useFinderFaceplates({ fetcher, intervalMs: 1_000_000 }))
    expect(result.current).toBe(EMPTY_FINDER_FACEPLATES_VM)
  })

  it('pins the poll cadence to FINDER_FACEPLATE_POLL_MS by default', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useFinderFaceplates({ fetcher }))
    expect(setSpy).toHaveBeenCalledWith(expect.any(Function), FINDER_FACEPLATE_POLL_MS)
  })

  it('polls again after the interval elapses', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useFinderFaceplates({ fetcher, intervalMs: 1_000 }))

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
    const { unmount } = renderHook(() => useFinderFaceplates({ fetcher, intervalMs: 1_000_000 }))

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
    const { result, unmount } = renderHook(() => useFinderFaceplates({ fetcher, intervalMs: 1_000_000 }))

    unmount() // request still in-flight

    await act(async () => {
      resolveFetch(PAYLOAD)
      await Promise.resolve()
    })

    // The late response never wrote state (VM stays EMPTY) and never warned.
    expect(result.current).toBe(EMPTY_FINDER_FACEPLATES_VM)
    expect(errSpy).not.toHaveBeenCalled()
  })

  it('no-fetch guard: a null fetcher renders EMPTY and schedules no poll', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const { result } = renderHook(() => useFinderFaceplates({ fetcher: null }))
    expect(result.current).toBe(EMPTY_FINDER_FACEPLATES_VM)
    expect(setSpy).not.toHaveBeenCalled()
  })

  it('keeps the last-known VM when a fetch rejects (no crash)', async () => {
    const fetcher = vi.fn(() => Promise.reject(new Error('boom')))
    const { result } = renderHook(() => useFinderFaceplates({ fetcher, intervalMs: 1_000_000 }))
    await act(async () => { await Promise.resolve() })
    expect(result.current).toBe(EMPTY_FINDER_FACEPLATES_VM)
  })
})

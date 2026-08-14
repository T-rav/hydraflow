import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useLoopFaceplates, LOOP_FACEPLATE_ENDPOINT } from '../useLoopFaceplates'
import { LOOP_FACEPLATE_POLL_MS } from '../../constants'

// The loop-faceplate hook (#10826) mirrors useFinderFaceplates with one
// deliberate difference: it returns the RAW payload (the view joins it
// against the live backgroundWorkers WS slice). Same four pinned edges.

const PAYLOAD = {
  generated_at: '2026-08-13T00:00:00+00:00',
  counts: { convertible: 1, error_driven: 0, exploratory: 0, infrastructure: 0 },
  loops: [
    {
      worker_name: 'gate_health', control_class: 'convertible',
      pv_label: 'fleet pass rate', finder_id: '', floor_sigma: null,
      setpoint: { value: 0.9, band: 0.05, units: 'fraction', direction: 'above', signed: false, signed_by: null, authority: '#10824' },
    },
  ],
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useLoopFaceplates — async lifecycle', () => {
  it('fetches the fixed endpoint once on mount, passing an abort signal, and exposes the raw payload', async () => {
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    const { result } = renderHook(() => useLoopFaceplates({ fetcher }))

    await waitFor(() => expect(result.current).toBe(PAYLOAD))
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith(
      LOOP_FACEPLATE_ENDPOINT,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('starts on null before the first response lands', () => {
    const fetcher = vi.fn(() => new Promise(() => {})) // never resolves
    const { result } = renderHook(() => useLoopFaceplates({ fetcher, intervalMs: 1_000_000 }))
    expect(result.current).toBe(null)
  })

  it('pins the poll cadence to LOOP_FACEPLATE_POLL_MS by default', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useLoopFaceplates({ fetcher }))
    expect(setSpy).toHaveBeenCalledWith(expect.any(Function), LOOP_FACEPLATE_POLL_MS)
  })

  it('polls again after the interval elapses', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useLoopFaceplates({ fetcher, intervalMs: 1_000 }))

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
    const { unmount } = renderHook(() => useLoopFaceplates({ fetcher, intervalMs: 1_000_000 }))

    await waitFor(() => expect(fetcher).toHaveBeenCalled())
    expect(capturedSignal.aborted).toBe(false)

    unmount()
    expect(capturedSignal.aborted).toBe(true)
    expect(clearSpy).toHaveBeenCalled()
  })

  it('a late resolution after unmount never writes state (stale-response guard)', async () => {
    let resolveLate
    const fetcher = vi.fn(
      () => new Promise(resolve => { resolveLate = resolve }),
    )
    const { result, unmount } = renderHook(() => useLoopFaceplates({ fetcher, intervalMs: 1_000_000 }))

    await waitFor(() => expect(fetcher).toHaveBeenCalled())
    unmount()
    await act(async () => { resolveLate(PAYLOAD) })
    expect(result.current).toBe(null)
  })

  it('keeps the last-known payload on a failed poll', async () => {
    let calls = 0
    const fetcher = vi.fn(() => {
      calls += 1
      return calls === 1 ? Promise.resolve(PAYLOAD) : Promise.reject(new Error('down'))
    })
    vi.useFakeTimers()
    const { result } = renderHook(() => useLoopFaceplates({ fetcher, intervalMs: 1_000 }))

    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current).toBe(PAYLOAD)

    await act(async () => { await vi.advanceTimersByTimeAsync(1_000) })
    expect(result.current).toBe(PAYLOAD)
  })

  it('no-fetch guard: a null fetcher stays on null and schedules nothing', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const { result } = renderHook(() => useLoopFaceplates({ fetcher: null }))
    expect(result.current).toBe(null)
    expect(setSpy).not.toHaveBeenCalled()
  })
})

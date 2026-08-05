import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useJudgeCalibration, JUDGE_CALIBRATION_ENDPOINT } from '../useJudgeCalibration'
import { EMPTY_JUDGE_CALIBRATION_VM } from '../model/judgeCalibration'
import { JUDGE_CALIBRATION_POLL_MS } from '../../constants'

// The judge-calibration hook (#10836) is a STRUCTURAL MIRROR of
// useFinderFaceplates / useSupervisorThread: the backend does the scoring, so
// the hook owns only the async lifecycle. Every edge is pinned — pinned
// cadence, poll teardown, stale-response/abort guard, no-fetch guard.

const PAYLOAD = {
  generated_at: '2026-08-04T00:00:00+00:00',
  resolved_total: 10,
  grace_window_days: 7,
  judges: [
    {
      judge_id: 'post_verify', judge_family: 'review_advisor', n_resolved: 10,
      brier: 0.083, log_score: 0.29, calibration_error: 0.05,
      calibration_bins: [], discrimination: 0.82,
      low_confidence: false, discrimination_undefined: false,
    },
  ],
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useJudgeCalibration — async lifecycle', () => {
  it('fetches the fixed endpoint once on mount, passing an abort signal, and exposes the VM', async () => {
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    const { result } = renderHook(() => useJudgeCalibration({ fetcher }))

    await waitFor(() => expect(result.current.scoredCount).toBe(1))
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith(
      JUDGE_CALIBRATION_ENDPOINT,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('starts on the EMPTY view model before the first response lands', () => {
    const fetcher = vi.fn(() => new Promise(() => {})) // never resolves
    const { result } = renderHook(() => useJudgeCalibration({ fetcher, intervalMs: 1_000_000 }))
    expect(result.current).toBe(EMPTY_JUDGE_CALIBRATION_VM)
  })

  it('pins the poll cadence to JUDGE_CALIBRATION_POLL_MS by default', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useJudgeCalibration({ fetcher }))
    expect(setSpy).toHaveBeenCalledWith(expect.any(Function), JUDGE_CALIBRATION_POLL_MS)
  })

  it('polls again after the interval elapses', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    renderHook(() => useJudgeCalibration({ fetcher, intervalMs: 1_000 }))

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
    const { unmount } = renderHook(() => useJudgeCalibration({ fetcher, intervalMs: 1_000_000 }))

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
    const { result, unmount } = renderHook(() => useJudgeCalibration({ fetcher, intervalMs: 1_000_000 }))

    unmount() // request still in-flight

    await act(async () => {
      resolveFetch(PAYLOAD)
      await Promise.resolve()
    })

    // The late response never wrote state (VM stays EMPTY) and never warned.
    expect(result.current).toBe(EMPTY_JUDGE_CALIBRATION_VM)
    expect(errSpy).not.toHaveBeenCalled()
  })

  it('no-fetch guard: a null fetcher renders EMPTY and schedules no poll', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    const { result } = renderHook(() => useJudgeCalibration({ fetcher: null }))
    expect(result.current).toBe(EMPTY_JUDGE_CALIBRATION_VM)
    expect(setSpy).not.toHaveBeenCalled()
  })

  it('keeps the last-known VM when a fetch rejects (no crash)', async () => {
    const fetcher = vi.fn(() => Promise.reject(new Error('boom')))
    const { result } = renderHook(() => useJudgeCalibration({ fetcher, intervalMs: 1_000_000 }))
    await act(async () => { await Promise.resolve() })
    expect(result.current).toBe(EMPTY_JUDGE_CALIBRATION_VM)
  })
})

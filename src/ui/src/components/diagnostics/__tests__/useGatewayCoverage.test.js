import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  GATEWAY_COVERAGE_ENDPOINT,
  useGatewayCoverage,
} from '../useGatewayCoverage'

const PAYLOAD = {
  status: 'complete',
  coverage_percent: 75,
  known_spend_coverage_percent: 75,
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useGatewayCoverage', () => {
  it('loads the selected range and exposes the normalized view model', async () => {
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    const { result } = renderHook(() => useGatewayCoverage({
      range: '7d',
      fetcher,
      intervalMs: 1_000_000,
    }))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.coverage.valueLabel).toBe('75.0%')
    expect(fetcher).toHaveBeenCalledWith(
      `${GATEWAY_COVERAGE_ENDPOINT}?range=7d`,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('reloads when repo scope changes', async () => {
    const fetcher = vi.fn(() => Promise.resolve(PAYLOAD))
    const { rerender } = renderHook(
      ({ scopeKey }) => useGatewayCoverage({
        fetcher,
        scopeKey,
        intervalMs: 1_000_000,
      }),
      { initialProps: { scopeKey: 'org-a' } },
    )
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
    rerender({ scopeKey: 'org-b' })
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
  })

  it('fails soft when the diagnostics endpoint is unavailable', async () => {
    const fetcher = vi.fn(() => Promise.reject(new Error('offline')))
    const { result } = renderHook(() => useGatewayCoverage({
      fetcher,
      intervalMs: 1_000_000,
    }))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error).toHaveProperty('message', 'offline')
    expect(result.current.coverage.status).toBe('no_data')
  })

  it('polls and aborts the in-flight lifecycle on unmount', async () => {
    vi.useFakeTimers()
    let signal
    const fetcher = vi.fn((_url, options) => {
      signal = options.signal
      return Promise.resolve(PAYLOAD)
    })
    const { unmount } = renderHook(() => useGatewayCoverage({
      fetcher,
      intervalMs: 1_000,
    }))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000) })
    expect(fetcher).toHaveBeenCalledTimes(2)
    unmount()
    expect(signal.aborted).toBe(true)
  })
})

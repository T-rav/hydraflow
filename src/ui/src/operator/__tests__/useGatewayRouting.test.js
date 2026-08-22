/**
 * Gateway routing poll hooks (#11534, ADR-0138).
 *
 * Both hooks MIRROR useTrustFleet, so the same lifecycle edges are pinned:
 * pinned cadence, poll teardown, abort/stale-response guard, no-fetch guard,
 * and last-known VM on failure. `useGatewayLiveRoutes` additionally reads both
 * Live endpoints in ONE cycle so the two halves cannot drift apart.
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import {
  GATEWAY_ACCOUNTS_ENDPOINT,
  GATEWAY_ACTIVE_ROUTES_ENDPOINT,
  GATEWAY_RECENT_ROUTES_ENDPOINT,
  useGatewayAccounts,
  useGatewayLiveRoutes,
} from '../useGatewayRouting'
import {
  EMPTY_GATEWAY_ACCOUNTS_VM,
  EMPTY_GATEWAY_LIVE_VM,
} from '../model/gatewayRouting'
import { GATEWAY_ROUTING_POLL_MS } from '../../constants'

const ACCOUNTS_PAYLOAD = {
  available: true,
  source_state: 'available',
  data: {
    window_seconds: 900,
    summary: { configured: 1, enabled: 1, leased: 0, in_flight: 0 },
    accounts: [{ account_id: 'legacy-anthropic', configured: true, health: 'unverified' }],
  },
}

const ACTIVE_PAYLOAD = {
  available: true,
  source_state: 'available',
  data: { leases: [], in_flight: [] },
}

const RECENT_PAYLOAD = {
  available: true,
  source_state: 'available',
  data: { routes: [], truncated: false },
}

function liveFetcher() {
  return vi.fn(url =>
    Promise.resolve(url === GATEWAY_ACTIVE_ROUTES_ENDPOINT ? ACTIVE_PAYLOAD : RECENT_PAYLOAD),
  )
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useGatewayAccounts — async lifecycle', () => {
  it('fetches the accounts endpoint once on mount with an abort signal', async () => {
    const fetcher = vi.fn(() => Promise.resolve(ACCOUNTS_PAYLOAD))
    renderHook(() => useGatewayAccounts({ fetcher }))

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
    expect(fetcher).toHaveBeenCalledWith(
      GATEWAY_ACCOUNTS_ENDPOINT,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('exposes the reduced view model once the response lands', async () => {
    const fetcher = vi.fn(() => Promise.resolve(ACCOUNTS_PAYLOAD))
    const { result } = renderHook(() => useGatewayAccounts({ fetcher }))

    await waitFor(() => expect(result.current.available).toBe(true))
  })

  it('starts on the EMPTY view model before the first response', () => {
    const fetcher = vi.fn(() => new Promise(() => {}))
    const { result } = renderHook(() => useGatewayAccounts({ fetcher, intervalMs: 1_000_000 }))

    expect(result.current).toBe(EMPTY_GATEWAY_ACCOUNTS_VM)
  })

  it('pins the poll cadence to GATEWAY_ROUTING_POLL_MS by default', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    renderHook(() => useGatewayAccounts({ fetcher: vi.fn(() => Promise.resolve(ACCOUNTS_PAYLOAD)) }))

    expect(setSpy).toHaveBeenCalledWith(expect.any(Function), GATEWAY_ROUTING_POLL_MS)
  })

  it('polls again after the interval elapses', async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn(() => Promise.resolve(ACCOUNTS_PAYLOAD))
    renderHook(() => useGatewayAccounts({ fetcher, intervalMs: 1_000 }))

    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000) })

    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('aborts the in-flight request on unmount', async () => {
    let capturedSignal
    const fetcher = vi.fn((_url, { signal }) => {
      capturedSignal = signal
      return Promise.resolve(ACCOUNTS_PAYLOAD)
    })
    const { unmount } = renderHook(() =>
      useGatewayAccounts({ fetcher, intervalMs: 1_000_000 }),
    )
    await waitFor(() => expect(fetcher).toHaveBeenCalled())

    unmount()

    expect(capturedSignal.aborted).toBe(true)
  })

  it('clears the poll timer on unmount', async () => {
    const clearSpy = vi.spyOn(global, 'clearInterval')
    const fetcher = vi.fn(() => Promise.resolve(ACCOUNTS_PAYLOAD))
    const { unmount } = renderHook(() =>
      useGatewayAccounts({ fetcher, intervalMs: 1_000_000 }),
    )
    await waitFor(() => expect(fetcher).toHaveBeenCalled())

    unmount()

    expect(clearSpy).toHaveBeenCalled()
  })

  it('ignores a response that resolves after unmount', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    let resolveFetch
    const fetcher = vi.fn(() => new Promise(res => { resolveFetch = res }))
    const { result, unmount } = renderHook(() =>
      useGatewayAccounts({ fetcher, intervalMs: 1_000_000 }),
    )
    unmount()

    await act(async () => {
      resolveFetch(ACCOUNTS_PAYLOAD)
      await Promise.resolve()
    })

    expect([result.current, errSpy.mock.calls.length]).toEqual([EMPTY_GATEWAY_ACCOUNTS_VM, 0])
  })

  it('schedules no poll when there is no fetcher', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    renderHook(() => useGatewayAccounts({ fetcher: null }))

    expect(setSpy).not.toHaveBeenCalled()
  })

  it('keeps the last-known VM when a fetch rejects', async () => {
    const fetcher = vi.fn(() => Promise.reject(new Error('boom')))
    const { result } = renderHook(() => useGatewayAccounts({ fetcher, intervalMs: 1_000_000 }))

    await act(async () => { await Promise.resolve() })

    expect(result.current).toBe(EMPTY_GATEWAY_ACCOUNTS_VM)
  })
})

describe('useGatewayLiveRoutes — async lifecycle', () => {
  it('reads both Live endpoints in one cycle', async () => {
    const fetcher = liveFetcher()
    renderHook(() => useGatewayLiveRoutes({ fetcher, intervalMs: 1_000_000 }))

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
    expect(fetcher.mock.calls.map(call => call[0]).sort()).toEqual(
      [GATEWAY_ACTIVE_ROUTES_ENDPOINT, GATEWAY_RECENT_ROUTES_ENDPOINT].sort(),
    )
  })

  it('exposes the combined view model once both responses land', async () => {
    const { result } = renderHook(() =>
      useGatewayLiveRoutes({ fetcher: liveFetcher(), intervalMs: 1_000_000 }),
    )

    await waitFor(() => expect(result.current.available).toBe(true))
  })

  it('starts on the EMPTY view model before the first response', () => {
    const fetcher = vi.fn(() => new Promise(() => {}))
    const { result } = renderHook(() => useGatewayLiveRoutes({ fetcher, intervalMs: 1_000_000 }))

    expect(result.current).toBe(EMPTY_GATEWAY_LIVE_VM)
  })

  it('keeps the last-known VM when one of the two reads rejects', async () => {
    const fetcher = vi.fn(url =>
      url === GATEWAY_RECENT_ROUTES_ENDPOINT
        ? Promise.reject(new Error('boom'))
        : Promise.resolve(ACTIVE_PAYLOAD),
    )
    const { result } = renderHook(() => useGatewayLiveRoutes({ fetcher, intervalMs: 1_000_000 }))

    await act(async () => { await Promise.resolve() })

    expect(result.current).toBe(EMPTY_GATEWAY_LIVE_VM)
  })

  it('schedules no poll when there is no fetcher', () => {
    const setSpy = vi.spyOn(global, 'setInterval')
    renderHook(() => useGatewayLiveRoutes({ fetcher: null }))

    expect(setSpy).not.toHaveBeenCalled()
  })
})

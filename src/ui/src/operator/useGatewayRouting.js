/**
 * useGatewayAccounts / useGatewayLiveRoutes — the operator console's read-only
 * gateway routing feeds (issue #11534, ADR-0138).
 *
 * Both MIRROR `useTrustFleet`: one pinned `setInterval`, one `AbortController`
 * per cycle, a stale-response guard before `setState`, a no-fetch guard, and a
 * last-known VM kept on failure. `useGatewayLiveRoutes` reads the two Live
 * endpoints in ONE cycle so leases, in-flight requests, and recent routes are
 * always rendered from the same poll rather than drifting apart.
 *
 * Both are strictly read-only: neither hook has a write path, and the backend
 * exposes no gateway mutation route for P0.
 */

import { useEffect, useState } from 'react'
import { GATEWAY_ROUTING_POLL_MS } from '../constants'
import {
  EMPTY_GATEWAY_ACCOUNTS_VM,
  EMPTY_GATEWAY_LIVE_VM,
  toGatewayAccounts,
  toGatewayLiveRoutes,
} from './model/gatewayRouting'

export const GATEWAY_ACCOUNTS_ENDPOINT = '/api/gateway/accounts'
export const GATEWAY_ACTIVE_ROUTES_ENDPOINT = '/api/gateway/routes/active'
export const GATEWAY_RECENT_ROUTES_ENDPOINT = '/api/gateway/routes/recent'

/** Default same-origin fetcher; throws on a non-OK response so the caller keeps
 * the last-known VM. Aborts when the caller's signal fires. */
async function defaultFetcher(url, { signal } = {}) {
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(`gateway routing fetch failed: ${res.status}`)
  return res.json()
}

/**
 * @param {{ fetcher?: Function, intervalMs?: number }} [options]
 * @returns {typeof EMPTY_GATEWAY_ACCOUNTS_VM}
 */
export function useGatewayAccounts({
  fetcher = defaultFetcher,
  intervalMs = GATEWAY_ROUTING_POLL_MS,
} = {}) {
  const [accounts, setAccounts] = useState(EMPTY_GATEWAY_ACCOUNTS_VM)

  useEffect(() => {
    if (typeof fetcher !== 'function') return undefined

    const controller = new AbortController()
    const { signal } = controller

    const load = async () => {
      let raw
      try {
        raw = await fetcher(GATEWAY_ACCOUNTS_ENDPOINT, { signal })
      } catch {
        return
      }
      if (signal.aborted) return
      setAccounts(toGatewayAccounts(raw))
    }

    load()
    const timer = setInterval(load, intervalMs)

    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [fetcher, intervalMs])

  return accounts
}

/**
 * @param {{ fetcher?: Function, intervalMs?: number }} [options]
 * @returns {typeof EMPTY_GATEWAY_LIVE_VM}
 */
export function useGatewayLiveRoutes({
  fetcher = defaultFetcher,
  intervalMs = GATEWAY_ROUTING_POLL_MS,
} = {}) {
  const [live, setLive] = useState(EMPTY_GATEWAY_LIVE_VM)

  useEffect(() => {
    if (typeof fetcher !== 'function') return undefined

    const controller = new AbortController()
    const { signal } = controller

    const load = async () => {
      let active
      let recent
      try {
        ;[active, recent] = await Promise.all([
          fetcher(GATEWAY_ACTIVE_ROUTES_ENDPOINT, { signal }),
          fetcher(GATEWAY_RECENT_ROUTES_ENDPOINT, { signal }),
        ])
      } catch {
        return
      }
      if (signal.aborted) return
      setLive(toGatewayLiveRoutes(active, recent))
    }

    load()
    const timer = setInterval(load, intervalMs)

    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [fetcher, intervalMs])

  return live
}

export default useGatewayAccounts

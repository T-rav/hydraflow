/**
 * The operator console's gateway routing feeds
 * (issue #11534 ADR-0138; #11540 ADR-0142).
 *
 * `useGatewayAccounts` and `useGatewayLiveRoutes` MIRROR `useTrustFleet`: one
 * pinned `setInterval`, one `AbortController` per cycle, a stale-response guard
 * before `setState`, a no-fetch guard, and a last-known VM kept on failure.
 * `useGatewayLiveRoutes` reads the two Live endpoints in ONE cycle so leases,
 * in-flight requests, and recent routes are always rendered from the same poll
 * rather than drifting apart. Both remain strictly read-only.
 *
 * `useAccountAdmin` is the console's HOST-ADMIN feed, and the only one here
 * with a write path. It follows `usePolicyWorkspace`'s shape rather than
 * inventing a second one:
 *
 *   - a monotonic ticket guard, so a slow poll landing after a mutation's
 *     refresh cannot put the pre-mutation revision back on screen and invite an
 *     action against it — the lost update optimistic concurrency exists to stop;
 *   - a fetcher that does NOT throw on a non-2xx response, because a 409 body
 *     carries the code the operator must act on. It is the same fetcher the
 *     policy plane uses: one convention for the whole operator control plane,
 *     not two that could drift;
 *   - a credential passed in per mutation and forwarded straight to the
 *     request — never state, never `localStorage`, never a view model;
 *   - a re-read after EVERY outcome, refusals included, because the whole point
 *     of a 409 is that the revision on screen is no longer the current one.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { GATEWAY_ROUTING_POLL_MS } from '../constants'
import {
  EMPTY_ACCOUNT_ADMIN_VM,
  EMPTY_GATEWAY_ACCOUNTS_VM,
  EMPTY_GATEWAY_LIVE_VM,
  toAccountAdmin,
  toGatewayAccounts,
  toGatewayLiveRoutes,
} from './model/gatewayRouting'
// One control-plane fetcher, borrowed rather than copied: it already returns
// `{ok, status, data}` and already refuses to throw away a refusal body.
import { defaultPolicyFetcher as defaultControlFetcher } from './usePolicyWorkspace'

export const GATEWAY_ACCOUNTS_ENDPOINT = '/api/gateway/accounts'
export const GATEWAY_ACCOUNT_AUDIT_ENDPOINT = '/api/gateway/accounts/audit'
export const GATEWAY_ACTIVE_ROUTES_ENDPOINT = '/api/gateway/routes/active'
export const GATEWAY_RECENT_ROUTES_ENDPOINT = '/api/gateway/routes/recent'

export { defaultControlFetcher }

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

/**
 * The audited administrative overlay: its revision, whether the chain verifies,
 * whether this dashboard may write, and the two host-admin mutations.
 *
 * @param {{ fetcher?: Function, intervalMs?: number, enabled?: boolean }} [options]
 */
export function useAccountAdmin({
  fetcher = defaultControlFetcher,
  intervalMs = GATEWAY_ROUTING_POLL_MS,
  enabled = true,
} = {}) {
  const [admin, setAdmin] = useState(EMPTY_ACCOUNT_ADMIN_VM)
  const issued = useRef(0)
  const applied = useRef(0)

  const load = useCallback(
    async signal => {
      const ticket = ++issued.current
      let response
      try {
        response = await fetcher(GATEWAY_ACCOUNT_AUDIT_ENDPOINT, { signal })
      } catch {
        return
      }
      // Strictly newer only: a poll that started before a mutation's refresh
      // must not overwrite the revision that refresh just established.
      if (signal?.aborted || ticket <= applied.current) return
      applied.current = ticket
      if (response?.ok) setAdmin(toAccountAdmin(response.data))
    },
    [fetcher],
  )

  useEffect(() => {
    if (!enabled || typeof fetcher !== 'function') return undefined
    const controller = new AbortController()
    load(controller.signal)
    const timer = setInterval(() => load(controller.signal), intervalMs)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [enabled, fetcher, intervalMs, load])

  const mutate = useCallback(
    async (url, method, body, token) => {
      let response
      try {
        response = await fetcher(url, { method, body, token })
      } catch {
        // A transport failure on a write is the AMBIGUOUS case: the mutation
        // may still have committed, so the caller is told to re-read rather
        // than told it failed.
        await load()
        return { ok: false, status: 0, code: 'gateway-unreachable' }
      }
      // Re-read on every outcome. On a 409 especially: the whole meaning of
      // that refusal is that the revision this view holds is no longer current.
      await load()
      if (!response?.ok) {
        return {
          ok: false,
          status: response?.status || 0,
          code: response?.data?.code || 'gateway-refused',
        }
      }
      return {
        ok: true,
        status: response.status,
        revision: response.data?.revision ?? null,
        data: response.data,
      }
    },
    [fetcher, load],
  )

  const setAccountState = useCallback(
    (accountId, { administrativeState, expectedRevision }, token) =>
      mutate(
        `${GATEWAY_ACCOUNTS_ENDPOINT}/${encodeURIComponent(accountId)}/state`,
        'PATCH',
        // No `actor`: the backend derives it from the authenticated operator
        // boundary, and a body that named one would be refused as extra.
        {
          administrative_state: administrativeState,
          expected_revision: expectedRevision,
        },
        token,
      ),
    [mutate],
  )

  const revokeLeases = useCallback(
    (accountId, { expectedRevision }, token) =>
      mutate(
        `${GATEWAY_ACCOUNTS_ENDPOINT}/${encodeURIComponent(accountId)}/revoke-leases`,
        'POST',
        { expected_revision: expectedRevision },
        token,
      ),
    [mutate],
  )

  return { admin, setAccountState, revokeLeases, refresh: load }
}

export default useGatewayAccounts

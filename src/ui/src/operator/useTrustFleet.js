/**
 * useTrustFleet — the operator console's trust-fleet feed for the Supervisor
 * gauges (#11207).
 *
 * Polls ONE endpoint (`/api/trust/fleet`, the per-loop tick + repair-attempt
 * tallies across the trust fleet) on a single pinned cadence and hands the
 * pure `toTrustFleetSummary` view model to the shell. Deliberately minimal —
 * a MIRROR of `useCostByRepo` / `useSupervisorThread`: the backend does the
 * aggregation, so the hook owns only the async lifecycle. Every edge is
 * pinned by a test:
 *
 *   - pinned cadence — one `setInterval(load, intervalMs)`, `intervalMs`
 *     defaults to the `TRUST_FLEET_POLL_MS` constant (no per-frame refetch
 *     storm);
 *   - poll teardown — the interval is cleared on unmount;
 *   - stale-response guard — each cycle runs under an `AbortController`;
 *     unmount aborts the in-flight request AND arms the guard so a late
 *     resolution never calls `setState` on an unmounted component;
 *   - no-fetch guard — a null/absent fetcher renders the empty VM and never
 *     schedules a poll.
 */

import { useEffect, useState } from 'react'
import { TRUST_FLEET_POLL_MS } from '../constants'
import { EMPTY_TRUST_FLEET_VM, toTrustFleetSummary } from './model/trustFleet'

/** The single read-only endpoint the gauges consume. */
export const TRUST_FLEET_ENDPOINT = '/api/trust/fleet'

/** Default same-origin fetcher; throws on a non-OK response so `load` keeps the
 * last-known VM. Aborts when the caller's signal fires. */
async function defaultFetcher(url, { signal } = {}) {
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(`trust fleet fetch failed: ${res.status}`)
  return res.json()
}

/**
 * @param {{ fetcher?: (url: string, opts: {signal: AbortSignal}) => Promise<any>,
 *           intervalMs?: number }} [options]
 * @returns {ReturnType<typeof toTrustFleetSummary>} the fleet VM (EMPTY until first load)
 */
export function useTrustFleet({ fetcher = defaultFetcher, intervalMs = TRUST_FLEET_POLL_MS } = {}) {
  const [fleet, setFleet] = useState(EMPTY_TRUST_FLEET_VM)

  useEffect(() => {
    // No-fetch guard: nothing to poll → stay on the empty VM, schedule nothing.
    if (typeof fetcher !== 'function') return undefined

    const controller = new AbortController()
    const { signal } = controller

    const load = async () => {
      let raw
      try {
        raw = await fetcher(TRUST_FLEET_ENDPOINT, { signal })
      } catch {
        // Network error or abort: keep the last-known VM, never crash the shell.
        return
      }
      // Stale-response guard: a response that lands after unmount must not write state.
      if (signal.aborted) return
      setFleet(toTrustFleetSummary(raw))
    }

    load()
    const timer = setInterval(load, intervalMs)

    return () => {
      controller.abort() // cancel in-flight + arm the stale-response guard
      clearInterval(timer) // stop polling
    }
  }, [fetcher, intervalMs])

  return fleet
}

export default useTrustFleet

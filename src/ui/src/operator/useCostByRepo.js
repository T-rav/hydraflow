/**
 * useCostByRepo — the operator console's cost feed (#10785).
 *
 * Polls ONE endpoint (`/api/diagnostics/cost/by-model-by-repo`, which already
 * returns the repo + per-repo cost-per-model aggregate over a rolling 24h
 * window) on a single pinned cadence and hands the pure `toCostByRepo` view
 * model to the shell. Deliberately minimal: the backend does the aggregation, so
 * the hook owns only the async lifecycle — which is exactly where the prior
 * monolithic attempts failed, so every edge is pinned by a test:
 *
 *   - pinned cadence — one `setInterval(load, intervalMs)`, `intervalMs`
 *     defaults to the `COST_POLL_MS` constant (no per-frame refetch storm);
 *   - poll teardown — the interval is cleared on unmount;
 *   - stale-response guard — each cycle runs under an `AbortController`; unmount
 *     aborts the in-flight request AND arms the guard so a late resolution never
 *     calls `setState` on an unmounted component;
 *   - no-fetch guard — a null/absent fetcher renders the empty VM and never
 *     schedules a poll.
 *
 * The endpoint returns every repo in one payload, so the hook needs no repo
 * scoping — repo selection is a client-side filter over the returned VM.
 */

import { useEffect, useState } from 'react'
import { COST_POLL_MS } from '../constants'
import { EMPTY_COST_VM, toCostByRepo } from './model/cost'

/** The single read-only endpoint the panel consumes. */
export const COST_ENDPOINT = '/api/diagnostics/cost/by-model-by-repo'

/** Default same-origin fetcher; throws on a non-OK response so `load` keeps the
 * last-known VM. Aborts when the caller's signal fires. */
async function defaultFetcher(url, { signal } = {}) {
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(`cost fetch failed: ${res.status}`)
  return res.json()
}

/**
 * @param {{ fetcher?: (url: string, opts: {signal: AbortSignal}) => Promise<any>,
 *           intervalMs?: number }} [options]
 * @returns {ReturnType<typeof toCostByRepo>} the cost view model (EMPTY until first load)
 */
export function useCostByRepo({ fetcher = defaultFetcher, intervalMs = COST_POLL_MS } = {}) {
  const [cost, setCost] = useState(EMPTY_COST_VM)

  useEffect(() => {
    // No-fetch guard: nothing to poll → stay on the empty VM, schedule nothing.
    if (typeof fetcher !== 'function') return undefined

    const controller = new AbortController()
    const { signal } = controller

    const load = async () => {
      let raw
      try {
        raw = await fetcher(COST_ENDPOINT, { signal })
      } catch {
        // Network error or abort: keep the last-known VM, never crash the shell.
        return
      }
      // Stale-response guard: a response that lands after unmount / repo change
      // must not write state.
      if (signal.aborted) return
      setCost(toCostByRepo(raw))
    }

    load()
    const timer = setInterval(load, intervalMs)

    return () => {
      controller.abort() // cancel in-flight + arm the stale-response guard
      clearInterval(timer) // stop polling
    }
  }, [fetcher, intervalMs])

  return cost
}

export default useCostByRepo

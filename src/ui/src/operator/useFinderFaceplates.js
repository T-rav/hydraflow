/**
 * useFinderFaceplates — the operator console's finder-faceplate feed (#10826).
 *
 * Polls ONE endpoint (`/api/diagnostics/finder-faceplates`, the read-only join
 * of each generative finder's measured noise floor against its live finding-rate)
 * on a single pinned cadence and hands the pure `toFinderFaceplates` view model
 * to the shell. Deliberately minimal — a STRUCTURAL MIRROR of `useCostByRepo`
 * (#10785) / `useSupervisorThread` (#10733): the backend does the join, so the
 * hook owns only the async lifecycle. Every edge is pinned by a test:
 *
 *   - pinned cadence — one `setInterval(load, intervalMs)`, `intervalMs`
 *     defaults to the `FINDER_FACEPLATE_POLL_MS` constant (no per-frame refetch
 *     storm);
 *   - poll teardown — the interval is cleared on unmount;
 *   - stale-response guard — each cycle runs under an `AbortController`; unmount
 *     aborts the in-flight request AND arms the guard so a late resolution never
 *     calls `setState` on an unmounted component;
 *   - no-fetch guard — a null/absent fetcher renders the empty VM and never
 *     schedules a poll.
 */

import { useEffect, useState } from 'react'
import { FINDER_FACEPLATE_POLL_MS } from '../constants'
import { EMPTY_FINDER_FACEPLATES_VM, toFinderFaceplates } from './model/finderFaceplates'

/** The single read-only endpoint the panel consumes (one row per catalog finder). */
export const FINDER_FACEPLATE_ENDPOINT = '/api/diagnostics/finder-faceplates'

/** Default same-origin fetcher; throws on a non-OK response so `load` keeps the
 * last-known VM. Aborts when the caller's signal fires. */
async function defaultFetcher(url, { signal } = {}) {
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(`finder faceplates fetch failed: ${res.status}`)
  return res.json()
}

/**
 * @param {{ fetcher?: (url: string, opts: {signal: AbortSignal}) => Promise<any>,
 *           intervalMs?: number }} [options]
 * @returns {ReturnType<typeof toFinderFaceplates>} the faceplate VM (EMPTY until first load)
 */
export function useFinderFaceplates({ fetcher = defaultFetcher, intervalMs = FINDER_FACEPLATE_POLL_MS } = {}) {
  const [faceplates, setFaceplates] = useState(EMPTY_FINDER_FACEPLATES_VM)

  useEffect(() => {
    // No-fetch guard: nothing to poll → stay on the empty VM, schedule nothing.
    if (typeof fetcher !== 'function') return undefined

    const controller = new AbortController()
    const { signal } = controller

    const load = async () => {
      let raw
      try {
        raw = await fetcher(FINDER_FACEPLATE_ENDPOINT, { signal })
      } catch {
        // Network error or abort: keep the last-known VM, never crash the shell.
        return
      }
      // Stale-response guard: a response that lands after unmount must not write state.
      if (signal.aborted) return
      setFaceplates(toFinderFaceplates(raw))
    }

    load()
    const timer = setInterval(load, intervalMs)

    return () => {
      controller.abort() // cancel in-flight + arm the stale-response guard
      clearInterval(timer) // stop polling
    }
  }, [fetcher, intervalMs])

  return faceplates
}

export default useFinderFaceplates

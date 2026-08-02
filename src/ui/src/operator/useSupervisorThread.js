/**
 * useSupervisorThread — the operator console's Tier-2 goal-supervisor feed
 * (#10733, ADR-0124).
 *
 * Polls ONE endpoint (`/api/diagnostics/supervisor/thread`, the supervisor's
 * append-only observation thread — newest last, healthy ticks omitted) on a
 * single pinned cadence and hands the pure `toSupervisorThread` view model to
 * the shell. Deliberately minimal — a MIRROR of `useCostByRepo` (#10785): the
 * backend does the work, so the hook owns only the async lifecycle, which is
 * exactly where the prior cost attempt died on an untested hook lifecycle. Every
 * edge is pinned by a test:
 *
 *   - pinned cadence — one `setInterval(load, intervalMs)`, `intervalMs`
 *     defaults to the `SUPERVISOR_POLL_MS` constant (no per-frame refetch storm);
 *   - poll teardown — the interval is cleared on unmount;
 *   - stale-response guard — each cycle runs under an `AbortController`; unmount
 *     aborts the in-flight request AND arms the guard so a late resolution never
 *     calls `setState` on an unmounted component;
 *   - no-fetch guard — a null/absent fetcher renders the empty VM and never
 *     schedules a poll.
 */

import { useEffect, useState } from 'react'
import { SUPERVISOR_POLL_MS } from '../constants'
import { EMPTY_SUPERVISOR_VM, toSupervisorThread } from './model/supervisorThread'

/** The single read-only endpoint the panel consumes (most-recent 50 observations). */
export const SUPERVISOR_ENDPOINT = '/api/diagnostics/supervisor/thread?limit=50'

/** Default same-origin fetcher; throws on a non-OK response so `load` keeps the
 * last-known VM. Aborts when the caller's signal fires. */
async function defaultFetcher(url, { signal } = {}) {
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(`supervisor thread fetch failed: ${res.status}`)
  return res.json()
}

/**
 * @param {{ fetcher?: (url: string, opts: {signal: AbortSignal}) => Promise<any>,
 *           intervalMs?: number }} [options]
 * @returns {ReturnType<typeof toSupervisorThread>} the supervisor VM (EMPTY until first load)
 */
export function useSupervisorThread({ fetcher = defaultFetcher, intervalMs = SUPERVISOR_POLL_MS } = {}) {
  const [thread, setThread] = useState(EMPTY_SUPERVISOR_VM)

  useEffect(() => {
    // No-fetch guard: nothing to poll → stay on the empty VM, schedule nothing.
    if (typeof fetcher !== 'function') return undefined

    const controller = new AbortController()
    const { signal } = controller

    const load = async () => {
      let raw
      try {
        raw = await fetcher(SUPERVISOR_ENDPOINT, { signal })
      } catch {
        // Network error or abort: keep the last-known VM, never crash the shell.
        return
      }
      // Stale-response guard: a response that lands after unmount must not write state.
      if (signal.aborted) return
      setThread(toSupervisorThread(raw))
    }

    load()
    const timer = setInterval(load, intervalMs)

    return () => {
      controller.abort() // cancel in-flight + arm the stale-response guard
      clearInterval(timer) // stop polling
    }
  }, [fetcher, intervalMs])

  return thread
}

export default useSupervisorThread

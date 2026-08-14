/**
 * useLoopFaceplates — the operator console's loop-faceplate feed (#10826).
 *
 * Polls ONE endpoint (`/api/diagnostics/loop-faceplates`, the STATIC
 * control-register half: fleet class + setpoint + floor sigma) on a single
 * pinned cadence. A STRUCTURAL MIRROR of `useFinderFaceplates` with one
 * deliberate difference: it returns the RAW payload, not a VM — the live
 * half of a faceplate comes from the console's `backgroundWorkers` WS slice,
 * so the CONTAINER composes `toLoopFaceplates(raw, backgroundWorkers)` and
 * the join re-renders on every WS update without refetching. Every lifecycle
 * edge is pinned by a test:
 *
 *   - pinned cadence — one `setInterval(load, intervalMs)`, defaulting to
 *     the `LOOP_FACEPLATE_POLL_MS` constant;
 *   - poll teardown — the interval is cleared on unmount;
 *   - stale-response guard — each cycle runs under an `AbortController`;
 *     unmount aborts in-flight AND arms the guard so a late resolution never
 *     writes state;
 *   - no-fetch guard — a null/absent fetcher stays on `null` and never
 *     schedules a poll.
 */

import { useEffect, useState } from 'react'
import { LOOP_FACEPLATE_POLL_MS } from '../constants'

/** The single read-only endpoint (one row per control/fleet.yaml entry). */
export const LOOP_FACEPLATE_ENDPOINT = '/api/diagnostics/loop-faceplates'

/** Default same-origin fetcher; throws on non-OK so `load` keeps the
 * last-known payload. Aborts when the caller's signal fires. */
async function defaultFetcher(url, { signal } = {}) {
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(`loop faceplates fetch failed: ${res.status}`)
  return res.json()
}

/**
 * @param {{ fetcher?: (url: string, opts: {signal: AbortSignal}) => Promise<any>,
 *           intervalMs?: number }} [options]
 * @returns {unknown} the raw `/loop-faceplates` payload (`null` until first load)
 */
export function useLoopFaceplates({ fetcher = defaultFetcher, intervalMs = LOOP_FACEPLATE_POLL_MS } = {}) {
  const [payload, setPayload] = useState(null)

  useEffect(() => {
    // No-fetch guard: nothing to poll → stay on null, schedule nothing.
    if (typeof fetcher !== 'function') return undefined

    const controller = new AbortController()
    const { signal } = controller

    const load = async () => {
      let raw
      try {
        raw = await fetcher(LOOP_FACEPLATE_ENDPOINT, { signal })
      } catch {
        // Network error or abort: keep the last-known payload, never crash.
        return
      }
      // Stale-response guard: post-unmount resolutions must not write state.
      if (signal.aborted) return
      setPayload(raw)
    }

    load()
    const timer = setInterval(load, intervalMs)

    return () => {
      controller.abort() // cancel in-flight + arm the stale-response guard
      clearInterval(timer) // stop polling
    }
  }, [fetcher, intervalMs])

  return payload
}

export default useLoopFaceplates

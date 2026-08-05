/**
 * useJudgeCalibration — the operator console's judge-calibration feed (#10836).
 *
 * Polls ONE endpoint (`/api/diagnostics/judge-calibration`, the read-only
 * proper-scoring report for each review judge — calibration ECE + discrimination
 * AUC, resolved against the escape ledger) on a single pinned cadence and hands
 * the pure `toJudgeCalibration` view model to the shell. Deliberately minimal —
 * a STRUCTURAL MIRROR of `useFinderFaceplates` (#10826) / `useSupervisorThread`
 * (#10733): the backend does the scoring, so the hook owns only the async
 * lifecycle. Every edge is pinned by a test:
 *
 *   - pinned cadence — one `setInterval(load, intervalMs)`, `intervalMs`
 *     defaults to the `JUDGE_CALIBRATION_POLL_MS` constant (no per-frame refetch
 *     storm);
 *   - poll teardown — the interval is cleared on unmount;
 *   - stale-response guard — each cycle runs under an `AbortController`; unmount
 *     aborts the in-flight request AND arms the guard so a late resolution never
 *     calls `setState` on an unmounted component;
 *   - no-fetch guard — a null/absent fetcher renders the empty VM and never
 *     schedules a poll.
 */

import { useEffect, useState } from 'react'
import { JUDGE_CALIBRATION_POLL_MS } from '../constants'
import { EMPTY_JUDGE_CALIBRATION_VM, toJudgeCalibration } from './model/judgeCalibration'

/** The single read-only endpoint the panel consumes (one row per review judge). */
export const JUDGE_CALIBRATION_ENDPOINT = '/api/diagnostics/judge-calibration'

/** Default same-origin fetcher; throws on a non-OK response so `load` keeps the
 * last-known VM. Aborts when the caller's signal fires. */
async function defaultFetcher(url, { signal } = {}) {
  const res = await fetch(url, { signal })
  if (!res.ok) throw new Error(`judge calibration fetch failed: ${res.status}`)
  return res.json()
}

/**
 * @param {{ fetcher?: (url: string, opts: {signal: AbortSignal}) => Promise<any>,
 *           intervalMs?: number }} [options]
 * @returns {ReturnType<typeof toJudgeCalibration>} the calibration VM (EMPTY until first load)
 */
export function useJudgeCalibration({ fetcher = defaultFetcher, intervalMs = JUDGE_CALIBRATION_POLL_MS } = {}) {
  const [calibration, setCalibration] = useState(EMPTY_JUDGE_CALIBRATION_VM)

  useEffect(() => {
    // No-fetch guard: nothing to poll → stay on the empty VM, schedule nothing.
    if (typeof fetcher !== 'function') return undefined

    const controller = new AbortController()
    const { signal } = controller

    const load = async () => {
      let raw
      try {
        raw = await fetcher(JUDGE_CALIBRATION_ENDPOINT, { signal })
      } catch {
        // Network error or abort: keep the last-known VM, never crash the shell.
        return
      }
      // Stale-response guard: a response that lands after unmount must not write state.
      if (signal.aborted) return
      setCalibration(toJudgeCalibration(raw))
    }

    load()
    const timer = setInterval(load, intervalMs)

    return () => {
      controller.abort() // cancel in-flight + arm the stale-response guard
      clearInterval(timer) // stop polling
    }
  }, [fetcher, intervalMs])

  return calibration
}

export default useJudgeCalibration

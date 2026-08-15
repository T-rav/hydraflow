/**
 * Trust-fleet summary view-model for the operator console's Supervisor
 * gauges (#11207). Pure `toTrustFleetSummary(raw)` — no fetch, no React.
 * Reduces the `GET /api/trust/fleet` payload (`{ loops: [...], ... }`, one
 * row per trust loop — see `_read_fleet` / `FLEET_ENDPOINT_SCHEMA` in
 * `dashboard_routes/_trust_routes.py`) into the two fleet-wide tallies the
 * Supervisor gauges need:
 *
 *   {
 *     tickHealth:    { total, ok, warmup, errored, loopCount },
 *     attemptBudget: { attempts, successes, failures },
 *   }
 *
 * Every numeric field is coerced through `num()` (NaN/Infinity/non-numeric ->
 * 0), mirroring the same guard in model/cost.js / model/finderFaceplates.js —
 * a malformed loop row never produces NaN or throws. A missing / malformed
 * payload yields the frozen EMPTY view model, never throws.
 */

function num(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

/** Frozen empty view model — the fallback for a missing / malformed payload. */
export const EMPTY_TRUST_FLEET_VM = Object.freeze({
  tickHealth: Object.freeze({ total: 0, ok: 0, warmup: 0, errored: 0, loopCount: 0 }),
  attemptBudget: Object.freeze({ attempts: 0, successes: 0, failures: 0 }),
})

/**
 * @param {unknown} raw The `/api/trust/fleet` payload (`{loops: [...]}`).
 * @returns {{tickHealth: object, attemptBudget: object}}
 */
export function toTrustFleetSummary(raw) {
  const loops = Array.isArray(raw?.loops) ? raw.loops : null
  if (!loops) return EMPTY_TRUST_FLEET_VM

  let ticksTotal = 0
  let ticksErrored = 0
  let ticksWarmup = 0
  let attempts = 0
  let successes = 0
  let failures = 0
  for (const loop of loops) {
    if (!loop || typeof loop !== 'object') continue
    ticksTotal += num(loop.ticks_total)
    ticksErrored += num(loop.ticks_errored)
    ticksWarmup += num(loop.ticks_warmup)
    attempts += num(loop.repair_attempts_total)
    successes += num(loop.repair_successes_total)
    failures += num(loop.repair_failures_total)
  }
  const ok = Math.max(0, ticksTotal - ticksErrored - ticksWarmup)

  return {
    tickHealth: {
      total: ticksTotal,
      ok,
      warmup: ticksWarmup,
      errored: ticksErrored,
      loopCount: loops.length,
    },
    attemptBudget: { attempts, successes, failures },
  }
}

export default toTrustFleetSummary

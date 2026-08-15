/**
 * Supervisor-gauges view-model for the operator console's full-width
 * Supervisor mode (#11207, promoting the pattern PR #11203 gave Instruments).
 *
 * Pure `toSupervisorGauges({ fleet, supervisor, vitals, cost, now })` — no
 * fetch, no React. Composes FOUR already-fetched view models (no new backend
 * for v1):
 *
 *   - `fleet`      — `toTrustFleetSummary(...)` (per-loop tick / repair tallies)
 *   - `supervisor` — `toSupervisorThread(...)` (latest observation's credit /
 *                    escalation snapshot)
 *   - `vitals`     — `toVitals(...)` (factory credit-pause state)
 *   - `cost`       — `toCostByRepo(...)` (rolling 24h spend)
 *
 * into five glanceable gauges:
 *
 *   { gauges: [
 *     { key, label, value, detail, tone },   // tick health
 *     { key, label, value, detail, tone },   // open escalations
 *     { key, label, value, detail, tone },   // credit state
 *     { key, label, value, detail, tone },   // attempt-budget consumption
 *     { key, label, value, detail, tone },   // cost burn rate
 *   ] }
 *
 * `tone` is a Badge tone (`'success'|'warning'|'danger'|'neutral'`), pinned by
 * tests at each threshold boundary. Every numeric input is coerced through
 * `num()` (NaN/Infinity/non-numeric -> 0) so a malformed upstream VM never
 * renders "NaN" or throws — mirrors the `num()` guard in model/cost.js /
 * model/finderFaceplates.js.
 *
 * `now` (epoch-ms) is OPTIONAL and used only for the credit-pause countdown;
 * it is never read from `Date.now()` internally — a bare `Date.now()` default
 * previously caused a re-render/useMemo-invalidation bug (see
 * OperatorConsole's `useNowTick` comment, #100). Omitting `now` still renders
 * a correct (countdown-less) "paused" gauge.
 */

import { EMPTY_TRUST_FLEET_VM } from './trustFleet'
import { EMPTY_SUPERVISOR_VM } from './supervisorThread'
import { EMPTY_COST_VM } from './cost'

function num(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

/** "2h14m" style duration for a millisecond span (never negative). */
function durationLabel(ms) {
  const totalSec = Math.max(0, Math.floor(ms / 1000))
  if (totalSec < 60) return `${totalSec}s`
  const totalMin = Math.floor(totalSec / 60)
  if (totalMin < 60) return `${totalMin}m`
  const hours = Math.floor(totalMin / 60)
  const mins = totalMin % 60
  return `${hours}h${String(mins).padStart(2, '0')}m`
}

function tickHealthGauge(fleet) {
  const th = fleet?.tickHealth ?? EMPTY_TRUST_FLEET_VM.tickHealth
  const total = num(th.total)
  if (total === 0) {
    return { key: 'tick-health', label: 'Tick health', value: 'no data', detail: '', tone: 'neutral' }
  }
  const errored = num(th.errored)
  const warmup = num(th.warmup)
  const ok = Math.max(0, num(th.ok))
  const loopCount = num(th.loopCount)
  // errored ticks dominate the tone (a real failure signal); warmup alone is
  // just startup noise, not a fault.
  const tone = errored > 0 ? 'danger' : warmup > 0 ? 'warning' : 'success'
  return {
    key: 'tick-health',
    label: 'Tick health',
    value: `${ok} ok / ${warmup} warmup / ${errored} errored`,
    detail: `${total} ticks across ${loopCount} loop${loopCount === 1 ? '' : 's'}`,
    tone,
  }
}

function escalationsGauge(supervisor) {
  const count = num(supervisor?.escalationCount ?? EMPTY_SUPERVISOR_VM.escalationCount)
  return {
    key: 'open-escalations',
    label: 'Open escalations',
    value: String(count),
    detail: count > 0 ? 'want a human' : 'none pending',
    tone: count > 0 ? 'danger' : 'success',
  }
}

function creditStateGauge(vitals, supervisor, now) {
  const credits = vitals?.credits ?? {}
  const snapshot = supervisor?.latest?.snapshot ?? {}
  const paused = credits.paused === true
  const failover = snapshot.creditFailoverActive === true
  const probeOverdue = snapshot.creditProbeOverdue === true

  if (paused) {
    const untilMs = Date.parse(String(credits.pausedUntil ?? ''))
    let value = 'paused'
    if (Number.isFinite(untilMs) && typeof now === 'number' && Number.isFinite(now)) {
      const remainingMs = untilMs - now
      value = remainingMs > 0 ? `paused — resumes in ${durationLabel(remainingMs)}` : 'paused — resume overdue'
    }
    return {
      key: 'credit-state',
      label: 'Credit state',
      value,
      detail: credits.provider ? `provider: ${credits.provider}` : '',
      tone: 'danger',
    }
  }
  if (failover) {
    return { key: 'credit-state', label: 'Credit state', value: 'failover engaged', detail: '', tone: 'warning' }
  }
  if (probeOverdue) {
    return { key: 'credit-state', label: 'Credit state', value: 'probe overdue', detail: '', tone: 'warning' }
  }
  return { key: 'credit-state', label: 'Credit state', value: 'ok', detail: '', tone: 'success' }
}

function attemptBudgetGauge(fleet) {
  const ab = fleet?.attemptBudget ?? EMPTY_TRUST_FLEET_VM.attemptBudget
  const attempts = num(ab.attempts)
  if (attempts === 0) {
    return { key: 'attempt-budget', label: 'Attempt budget', value: 'no data', detail: '', tone: 'neutral' }
  }
  const successes = num(ab.successes)
  const failures = num(ab.failures)
  const tone = failures > successes ? 'danger' : failures > 0 ? 'warning' : 'success'
  return {
    key: 'attempt-budget',
    label: 'Attempt budget',
    value: `${attempts} attempts`,
    detail: `${successes} ok / ${failures} failed`,
    tone,
  }
}

function costBurnGauge(cost) {
  const total = num(cost?.totalCostUsd)
  const windowLabel = String(cost?.windowLabel || EMPTY_COST_VM.windowLabel)
  const unknown = cost?.totalCostUnknown === true
  return {
    key: 'cost-burn',
    label: 'Cost burn',
    value: `$${total.toFixed(2)}`,
    detail: unknown ? `${windowLabel} (some models unpriced)` : windowLabel,
    tone: unknown ? 'warning' : 'neutral',
  }
}

/**
 * @param {{ fleet?: ReturnType<typeof import('./trustFleet').toTrustFleetSummary>,
 *           supervisor?: ReturnType<typeof import('./supervisorThread').toSupervisorThread>,
 *           vitals?: ReturnType<typeof import('./vitals').toVitals>,
 *           cost?: ReturnType<typeof import('./cost').toCostByRepo>,
 *           now?: number }} [input]
 * @returns {{ gauges: Array<{key: string, label: string, value: string, detail: string, tone: string}> }}
 */
export function toSupervisorGauges({ fleet, supervisor, vitals, cost, now } = {}) {
  return {
    gauges: [
      tickHealthGauge(fleet),
      escalationsGauge(supervisor),
      creditStateGauge(vitals, supervisor, now),
      attemptBudgetGauge(fleet),
      costBurnGauge(cost),
    ],
  }
}

/** Frozen empty view model — the fallback before the first poll lands. */
export const EMPTY_GAUGES_VM = Object.freeze({
  gauges: Object.freeze(toSupervisorGauges({}).gauges),
})

export default toSupervisorGauges

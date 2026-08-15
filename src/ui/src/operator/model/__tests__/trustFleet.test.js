import { describe, it, expect } from 'vitest'
import { toTrustFleetSummary, EMPTY_TRUST_FLEET_VM } from '../trustFleet'

// toTrustFleetSummary (#11207) reduces the /api/trust/fleet payload (one row
// per trust loop) into the two fleet-wide tallies the Supervisor gauges need:
// tick health (ok/warmup/errored) and repair-attempt-budget consumption. Every
// numeric field is coerced through num() so a malformed loop row never
// produces NaN or throws.

const loop = (over = {}) => ({
  worker_name: 'flake_tracker',
  ticks_total: 10,
  ticks_errored: 1,
  ticks_warmup: 2,
  repair_attempts_total: 5,
  repair_successes_total: 3,
  repair_failures_total: 1,
  ...over,
})

describe('toTrustFleetSummary — malformed payload', () => {
  it('returns the EMPTY VM for a missing / malformed payload', () => {
    expect(toTrustFleetSummary(null)).toBe(EMPTY_TRUST_FLEET_VM)
    expect(toTrustFleetSummary(undefined)).toBe(EMPTY_TRUST_FLEET_VM)
    expect(toTrustFleetSummary(42)).toBe(EMPTY_TRUST_FLEET_VM)
    expect(toTrustFleetSummary({})).toBe(EMPTY_TRUST_FLEET_VM)
    expect(toTrustFleetSummary({ loops: 'not-an-array' })).toBe(EMPTY_TRUST_FLEET_VM)
  })

  it('returns zeroed tallies (not the EMPTY reference) for an empty loops array', () => {
    const vm = toTrustFleetSummary({ loops: [] })
    expect(vm).toEqual(EMPTY_TRUST_FLEET_VM)
  })

  it('skips non-object entries in the loops array without throwing', () => {
    const vm = toTrustFleetSummary({ loops: [null, 42, 'x', loop()] })
    expect(vm.tickHealth.total).toBe(10)
  })
})

describe('toTrustFleetSummary — tick health tally', () => {
  it('sums ticks_total / ticks_errored / ticks_warmup across loops', () => {
    const vm = toTrustFleetSummary({
      loops: [
        loop({ ticks_total: 10, ticks_errored: 1, ticks_warmup: 2 }),
        loop({ ticks_total: 20, ticks_errored: 0, ticks_warmup: 3 }),
      ],
    })
    expect(vm.tickHealth).toEqual({ total: 30, ok: 24, warmup: 5, errored: 1, loopCount: 2 })
  })

  it('clamps ok at 0 when errored+warmup exceed total (never negative)', () => {
    const vm = toTrustFleetSummary({ loops: [loop({ ticks_total: 5, ticks_errored: 4, ticks_warmup: 4 })] })
    expect(vm.tickHealth.ok).toBe(0)
  })

  it('coerces non-finite / non-numeric tick fields to 0', () => {
    const vm = toTrustFleetSummary({
      loops: [loop({ ticks_total: NaN, ticks_errored: Infinity, ticks_warmup: 'bogus' })],
    })
    expect(vm.tickHealth).toEqual({ total: 0, ok: 0, warmup: 0, errored: 0, loopCount: 1 })
  })
})

describe('toTrustFleetSummary — attempt-budget tally', () => {
  it('sums repair attempts / successes / failures across loops', () => {
    const vm = toTrustFleetSummary({
      loops: [
        loop({ repair_attempts_total: 5, repair_successes_total: 3, repair_failures_total: 1 }),
        loop({ repair_attempts_total: 2, repair_successes_total: 2, repair_failures_total: 0 }),
      ],
    })
    expect(vm.attemptBudget).toEqual({ attempts: 7, successes: 5, failures: 1 })
  })

  it('coerces non-finite / missing repair fields to 0', () => {
    const vm = toTrustFleetSummary({
      loops: [{ worker_name: 'x' }],
    })
    expect(vm.attemptBudget).toEqual({ attempts: 0, successes: 0, failures: 0 })
  })
})

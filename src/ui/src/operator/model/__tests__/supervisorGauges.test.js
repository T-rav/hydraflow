import { describe, it, expect } from 'vitest'
import { toSupervisorGauges, EMPTY_GAUGES_VM } from '../supervisorGauges'

// toSupervisorGauges (#11207) composes the fleet/supervisor/vitals/cost VMs
// into the Supervisor tab's five gauges. These tests pin the tone thresholds
// (a prior attempt shipped unpinned severity-tone mappings) and non-finite
// metric coercion (a prior attempt shipped unpinned NaN/Infinity handling) —
// see the #11207 escalation's test-adequacy findings.

function gaugeByKey(vm, key) {
  return vm.gauges.find(g => g.key === key)
}

describe('toSupervisorGauges — shape', () => {
  it('returns exactly five gauges, in a stable order, for a fully-empty input', () => {
    const vm = toSupervisorGauges({})
    expect(vm.gauges).toHaveLength(5)
    expect(vm.gauges.map(g => g.key)).toEqual([
      'tick-health', 'open-escalations', 'credit-state', 'attempt-budget', 'cost-burn',
    ])
  })

  it('EMPTY_GAUGES_VM matches toSupervisorGauges({}) and is frozen', () => {
    expect(EMPTY_GAUGES_VM.gauges).toEqual(toSupervisorGauges({}).gauges)
    expect(Object.isFrozen(EMPTY_GAUGES_VM)).toBe(true)
    expect(Object.isFrozen(EMPTY_GAUGES_VM.gauges)).toBe(true)
  })

  it('never throws on entirely missing sub-VMs (undefined fleet/supervisor/vitals/cost)', () => {
    expect(() => toSupervisorGauges({ fleet: undefined, supervisor: undefined, vitals: undefined, cost: undefined })).not.toThrow()
  })
})

describe('toSupervisorGauges — tick health', () => {
  it('renders "no data" (neutral) when the fleet has no ticks', () => {
    const g = gaugeByKey(toSupervisorGauges({ fleet: { tickHealth: { total: 0, ok: 0, warmup: 0, errored: 0, loopCount: 0 } } }), 'tick-health')
    expect(g.value).toBe('no data')
    expect(g.tone).toBe('neutral')
  })

  it('is success-toned when every tick is clean (no errors, no warmup)', () => {
    const g = gaugeByKey(toSupervisorGauges({ fleet: { tickHealth: { total: 10, ok: 10, warmup: 0, errored: 0, loopCount: 2 } } }), 'tick-health')
    expect(g.tone).toBe('success')
    expect(g.value).toBe('10 ok / 0 warmup / 0 errored')
    expect(g.detail).toBe('10 ticks across 2 loops')
  })

  it('is warning-toned when warmup ticks exist but no errors', () => {
    const g = gaugeByKey(toSupervisorGauges({ fleet: { tickHealth: { total: 10, ok: 7, warmup: 3, errored: 0, loopCount: 1 } } }), 'tick-health')
    expect(g.tone).toBe('warning')
    expect(g.detail).toBe('10 ticks across 1 loop')
  })

  it('is danger-toned when any tick errored, even alongside warmup', () => {
    const g = gaugeByKey(toSupervisorGauges({ fleet: { tickHealth: { total: 10, ok: 6, warmup: 3, errored: 1, loopCount: 1 } } }), 'tick-health')
    expect(g.tone).toBe('danger')
  })

  it('coerces non-finite / non-numeric tick fields to 0 rather than rendering NaN', () => {
    const g = gaugeByKey(toSupervisorGauges({ fleet: { tickHealth: { total: NaN, ok: Infinity, warmup: 'x', errored: null, loopCount: undefined } } }), 'tick-health')
    expect(g.value).toBe('no data')
    expect(g.tone).toBe('neutral')
  })
})

describe('toSupervisorGauges — open escalations', () => {
  it('is success-toned with "none pending" when escalationCount is 0', () => {
    const g = gaugeByKey(toSupervisorGauges({ supervisor: { escalationCount: 0 } }), 'open-escalations')
    expect(g.value).toBe('0')
    expect(g.tone).toBe('success')
    expect(g.detail).toBe('none pending')
  })

  it('is danger-toned with "want a human" when escalations are open', () => {
    const g = gaugeByKey(toSupervisorGauges({ supervisor: { escalationCount: 3 } }), 'open-escalations')
    expect(g.value).toBe('3')
    expect(g.tone).toBe('danger')
    expect(g.detail).toBe('want a human')
  })

  it('coerces a non-finite escalationCount to 0', () => {
    const g = gaugeByKey(toSupervisorGauges({ supervisor: { escalationCount: NaN } }), 'open-escalations')
    expect(g.value).toBe('0')
    expect(g.tone).toBe('success')
  })
})

describe('toSupervisorGauges — credit state', () => {
  it('is success-toned "ok" with nothing paused/failed-over/overdue', () => {
    const g = gaugeByKey(toSupervisorGauges({ vitals: { credits: { paused: false } } }), 'credit-state')
    expect(g.value).toBe('ok')
    expect(g.tone).toBe('success')
  })

  it('is danger-toned "paused" with no countdown when `now` is not supplied', () => {
    const g = gaugeByKey(toSupervisorGauges({
      vitals: { credits: { paused: true, pausedUntil: '2026-08-15T13:00:00Z', provider: 'anthropic' } },
    }), 'credit-state')
    expect(g.value).toBe('paused')
    expect(g.tone).toBe('danger')
    expect(g.detail).toBe('provider: anthropic')
  })

  it('renders a resume countdown in seconds under a minute', () => {
    const g = gaugeByKey(toSupervisorGauges({
      vitals: { credits: { paused: true, pausedUntil: '2026-08-15T12:00:30Z' } },
      now: Date.parse('2026-08-15T12:00:00Z'),
    }), 'credit-state')
    expect(g.value).toBe('paused — resumes in 30s')
  })

  it('renders a resume countdown in minutes under an hour', () => {
    const g = gaugeByKey(toSupervisorGauges({
      vitals: { credits: { paused: true, pausedUntil: '2026-08-15T12:14:00Z' } },
      now: Date.parse('2026-08-15T12:00:00Z'),
    }), 'credit-state')
    expect(g.value).toBe('paused — resumes in 14m')
  })

  it('renders a resume countdown in hours+minutes at or beyond an hour', () => {
    const g = gaugeByKey(toSupervisorGauges({
      vitals: { credits: { paused: true, pausedUntil: '2026-08-15T14:14:00Z' } },
      now: Date.parse('2026-08-15T12:00:00Z'),
    }), 'credit-state')
    expect(g.value).toBe('paused — resumes in 2h14m')
  })

  it('renders "resume overdue" when pausedUntil has already passed', () => {
    const g = gaugeByKey(toSupervisorGauges({
      vitals: { credits: { paused: true, pausedUntil: '2026-08-15T11:00:00Z' } },
      now: Date.parse('2026-08-15T12:00:00Z'),
    }), 'credit-state')
    expect(g.value).toBe('paused — resume overdue')
  })

  it('falls back to bare "paused" when pausedUntil is unparseable, even with `now` supplied', () => {
    const g = gaugeByKey(toSupervisorGauges({
      vitals: { credits: { paused: true, pausedUntil: 'not-a-date' } },
      now: Date.parse('2026-08-15T12:00:00Z'),
    }), 'credit-state')
    expect(g.value).toBe('paused')
  })

  it('is warning-toned "failover engaged" when not paused but the latest snapshot flags failover', () => {
    const g = gaugeByKey(toSupervisorGauges({
      vitals: { credits: { paused: false } },
      supervisor: { latest: { snapshot: { creditFailoverActive: true } } },
    }), 'credit-state')
    expect(g.value).toBe('failover engaged')
    expect(g.tone).toBe('warning')
  })

  it('is warning-toned "probe overdue" when not paused/failed-over but the probe is overdue', () => {
    const g = gaugeByKey(toSupervisorGauges({
      vitals: { credits: { paused: false } },
      supervisor: { latest: { snapshot: { creditProbeOverdue: true } } },
    }), 'credit-state')
    expect(g.value).toBe('probe overdue')
    expect(g.tone).toBe('warning')
  })

  it('prioritizes paused over failover/probe-overdue when multiple signals are set', () => {
    const g = gaugeByKey(toSupervisorGauges({
      vitals: { credits: { paused: true, pausedUntil: '2026-08-15T13:00:00Z' } },
      supervisor: { latest: { snapshot: { creditFailoverActive: true, creditProbeOverdue: true } } },
    }), 'credit-state')
    expect(g.value).toBe('paused')
  })
})

describe('toSupervisorGauges — attempt budget', () => {
  it('renders "no data" (neutral) when no repair attempts were made', () => {
    const g = gaugeByKey(toSupervisorGauges({ fleet: { attemptBudget: { attempts: 0, successes: 0, failures: 0 } } }), 'attempt-budget')
    expect(g.value).toBe('no data')
    expect(g.tone).toBe('neutral')
  })

  it('is success-toned when every attempt succeeded', () => {
    const g = gaugeByKey(toSupervisorGauges({ fleet: { attemptBudget: { attempts: 5, successes: 5, failures: 0 } } }), 'attempt-budget')
    expect(g.tone).toBe('success')
    expect(g.value).toBe('5 attempts')
    expect(g.detail).toBe('5 ok / 0 failed')
  })

  it('is warning-toned when failures exist but do not outnumber successes', () => {
    const g = gaugeByKey(toSupervisorGauges({ fleet: { attemptBudget: { attempts: 5, successes: 3, failures: 2 } } }), 'attempt-budget')
    expect(g.tone).toBe('warning')
  })

  it('is danger-toned when failures outnumber successes', () => {
    const g = gaugeByKey(toSupervisorGauges({ fleet: { attemptBudget: { attempts: 5, successes: 1, failures: 4 } } }), 'attempt-budget')
    expect(g.tone).toBe('danger')
  })

  it('coerces non-finite attempt fields to 0', () => {
    const g = gaugeByKey(toSupervisorGauges({ fleet: { attemptBudget: { attempts: NaN, successes: Infinity, failures: 'x' } } }), 'attempt-budget')
    expect(g.value).toBe('no data')
  })
})

describe('toSupervisorGauges — cost burn', () => {
  it('formats the total to two decimal places with the window label', () => {
    const g = gaugeByKey(toSupervisorGauges({ cost: { totalCostUsd: 12.3, windowLabel: 'last 24h', totalCostUnknown: false } }), 'cost-burn')
    expect(g.value).toBe('$12.30')
    expect(g.detail).toBe('last 24h')
    expect(g.tone).toBe('neutral')
  })

  it('is warning-toned and notes unpriced models when totalCostUnknown is true', () => {
    const g = gaugeByKey(toSupervisorGauges({ cost: { totalCostUsd: 1, windowLabel: 'last 24h', totalCostUnknown: true } }), 'cost-burn')
    expect(g.tone).toBe('warning')
    expect(g.detail).toBe('last 24h (some models unpriced)')
  })

  it('coerces a non-finite / negative-Infinity total cost to 0.00 rather than throwing', () => {
    const g = gaugeByKey(toSupervisorGauges({ cost: { totalCostUsd: NaN } }), 'cost-burn')
    expect(g.value).toBe('$0.00')
    const g2 = gaugeByKey(toSupervisorGauges({ cost: { totalCostUsd: -Infinity } }), 'cost-burn')
    expect(g2.value).toBe('$0.00')
  })

  it('falls back to the default window label when absent', () => {
    const g = gaugeByKey(toSupervisorGauges({ cost: { totalCostUsd: 0 } }), 'cost-burn')
    expect(g.detail).toBe('last 24h')
  })
})

import { describe, it, expect } from 'vitest'
import { reducer } from '../HydraFlowContext'

/**
 * #11306: severity routes the destination.
 *
 * The banner is the highest-urgency surface (credit pauses, faults, HITL).
 * Advisories — an epic gone stale, a fleet-vitals shadow alarm — used to
 * render there with identical weight, which trains the operator to ignore
 * the banner. They now accumulate behind the bell.
 *
 * The load-bearing safety rule: UNCLASSIFIED defaults to BLOCKING. A new
 * alert kind must be demoted deliberately, never by omission.
 */
const base = { events: [], advisoryNotices: [], systemAlert: null }

const alert = (data) => ({ type: 'system_alert', data })

describe('system_alert severity routing (#11306)', () => {
  it('routes an advisory to the bell, not the banner', () => {
    const next = reducer(base, alert({
      kind: 'epic_stale', severity: 'warning', message: 'Epic #10914 is stale', source: 'epic_monitor',
    }))
    expect(next.systemAlert).toBeNull()
    expect(next.advisoryNotices).toHaveLength(1)
    expect(next.advisoryNotices[0].message).toBe('Epic #10914 is stale')
  })

  it('routes a blocking alert to the banner, not the bell', () => {
    const next = reducer(base, alert({
      kind: 'credit_pause', message: 'Credit limit reached', source: 'orchestrator',
    }))
    expect(next.systemAlert?.message).toBe('Credit limit reached')
    expect(next.advisoryNotices).toHaveLength(0)
  })

  it('defaults UNCLASSIFIED alerts to the banner (fail-loud)', () => {
    const next = reducer(base, alert({ kind: 'brand_new_kind', message: 'something happened' }))
    expect(next.systemAlert?.message).toBe('something happened')
    expect(next.advisoryNotices).toHaveLength(0)
  })

  it('dedupes a repeating advisory instead of piling it up', () => {
    const data = { kind: 'epic_stale', severity: 'warning', message: 'Epic #10914 is stale' }
    let state = reducer(base, alert(data))
    state = reducer(state, alert(data))
    state = reducer(state, alert(data))
    expect(state.advisoryNotices).toHaveLength(1)
  })

  it('keeps newest first and caps the digest', () => {
    let state = base
    for (let i = 0; i < 60; i += 1) {
      state = reducer(state, alert({ kind: 'k', severity: 'warning', message: `notice ${i}` }))
    }
    expect(state.advisoryNotices).toHaveLength(50)
    expect(state.advisoryNotices[0].message).toBe('notice 59')
  })

  it('dismisses one notice by id and all at once', () => {
    let state = reducer(base, alert({ kind: 'a', severity: 'warning', message: 'one' }))
    state = reducer(state, alert({ kind: 'b', severity: 'warning', message: 'two' }))
    const target = state.advisoryNotices[0].id
    state = reducer(state, { type: 'DISMISS_ADVISORY_NOTICE', id: target })
    expect(state.advisoryNotices).toHaveLength(1)
    state = reducer(state, { type: 'DISMISS_ALL_ADVISORY_NOTICES' })
    expect(state.advisoryNotices).toHaveLength(0)
  })
})

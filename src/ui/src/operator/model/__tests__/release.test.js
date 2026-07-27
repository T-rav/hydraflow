import { describe, it, expect } from 'vitest'
import { toReleasePromotion } from '../release'

// toReleasePromotion (epic #10556 follow-up) is the pure RELEASE PROMOTION
// adapter: it turns the /api/staging-promotion/status payload (+ the sticky
// background-worker slice) into the compact strip's view model. No React, no
// side effects, deterministic. State machine: open rc/ PR -> 'promoting';
// staging ahead of main with no PR -> 'behind'; nothing pending -> 'in_sync';
// no payload / disabled -> 'unknown'.

function payload(over = {}) {
  return {
    enabled: true,
    cadence_hours: 4,
    cadence_progress_hours: 1.5,
    last_rc_cut_at: '2026-07-24T12:00:00Z',
    last_sweep_at: '2026-07-24T12:05:00Z',
    open_promotion_pr: null,
    recent_window_days: 7,
    recent_promoted: 3,
    recent_failed: 0,
    recent_failure_rate: 0,
    ...over,
  }
}

const OPEN_PR = {
  number: 123,
  branch: 'rc/2026-07-24-1200',
  url: 'https://github.com/acme/repo/pull/123',
}

describe('toReleasePromotion', () => {
  it('reports in_sync when enabled with no open PR and not ahead', () => {
    const vm = toReleasePromotion(payload({ open_promotion_pr: null, commits_ahead: 0 }))
    expect(vm.state).toBe('in_sync')
    expect(vm.openPr).toBeNull()
    expect(vm.cadenceHours).toBe(4)
    expect(vm.cadenceProgressHours).toBe(1.5)
  })

  it('reports behind when staging is ahead of main with no promotion PR', () => {
    const vm = toReleasePromotion(payload({ open_promotion_pr: null, commits_ahead: 5 }))
    expect(vm.state).toBe('behind')
    expect(vm.commitsAhead).toBe(5)
    expect(vm.openPr).toBeNull()
  })

  it('reports promoting and surfaces the open RC PR when one is in flight', () => {
    const vm = toReleasePromotion(payload({ open_promotion_pr: OPEN_PR }))
    expect(vm.state).toBe('promoting')
    expect(vm.openPr).toEqual({ number: 123, url: 'https://github.com/acme/repo/pull/123' })
    expect(vm.lastRc).toEqual({ name: 'rc/2026-07-24-1200', ts: '2026-07-24T12:00:00Z' })
  })

  it('returns an unknown/empty shape for null/absent input', () => {
    expect(toReleasePromotion(null)).toEqual({
      state: 'unknown',
      enabled: false,
      commitsAhead: null,
      openPr: null,
      lastRc: null,
      cadenceHours: null,
      cadenceProgressHours: null,
      loop: null,
    })
    expect(toReleasePromotion(undefined).state).toBe('unknown')
  })

  it('reports unknown when the two-tier promotion model is disabled', () => {
    const vm = toReleasePromotion(payload({ enabled: false, open_promotion_pr: OPEN_PR }))
    expect(vm.state).toBe('unknown')
    expect(vm.enabled).toBe(false)
  })

  it('derives the promotion loop health from the sticky worker slice', () => {
    const workers = [
      { name: 'ci_monitor', status: 'ok', enabled: true },
      { name: 'staging_promotion', status: 'error', enabled: true },
    ]
    const vm = toReleasePromotion(payload(), { backgroundWorkers: workers })
    expect(vm.loop).toEqual({ status: 'error', severity: 'bad' })
  })

  it('marks a disabled promotion loop muted', () => {
    const workers = [{ name: 'staging_promotion', status: 'ok', enabled: false }]
    const vm = toReleasePromotion(payload(), { backgroundWorkers: workers })
    expect(vm.loop).toEqual({ status: 'ok', severity: 'muted' })
  })

  it('leaves loop null when the promotion worker has not reported', () => {
    const vm = toReleasePromotion(payload(), { backgroundWorkers: [{ name: 'ci_monitor', status: 'ok' }] })
    expect(vm.loop).toBeNull()
  })

  it('is pure: same input yields a deeply-equal, independent output and never mutates it', () => {
    const input = payload({ open_promotion_pr: OPEN_PR })
    const inputSnapshot = payload({ open_promotion_pr: { ...OPEN_PR } })
    const extras = { backgroundWorkers: [{ name: 'staging_promotion', status: 'ok', enabled: true }] }
    const a = toReleasePromotion(input, extras)
    const b = toReleasePromotion(input, extras)
    expect(a).toEqual(b)
    expect(a).not.toBe(b)
    expect(a.openPr).not.toBe(input.open_promotion_pr)
    expect(input).toEqual(inputSnapshot) // input untouched
  })
})

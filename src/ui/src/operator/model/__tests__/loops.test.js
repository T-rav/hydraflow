import { describe, it, expect } from 'vitest'
import { toLoops } from '../loops'

// toLoops (epic #10556 follow-up) reduces background-worker telemetry into the
// operator "all loops quick view": loops grouped by functional area (sourced
// from src/constants.js BACKGROUND_WORKERS `group`), with per-category counts
// and per-loop severity + the relevant recent message/error.
//
// Two input forms are supported and exercised here:
//   - the reducer's `backgroundWorkers` slice: { name, status, last_run,
//     details, enabled, interval_seconds }
//   - a raw newest-first event array of `background_worker_status` frames, with
//     correlated `error` frames for messages.

// A backgroundWorkers-slice entry.
const worker = (name, over = {}) => ({
  name,
  status: 'ok',
  last_run: '2026-07-26T12:00:00Z',
  details: {},
  enabled: true,
  interval_seconds: 300,
  ...over,
})

// A background_worker_status event frame (newest-first ordering by id).
const bg = (name, status, id, details = {}) => ({
  type: 'background_worker_status',
  timestamp: `2026-07-26T12:00:0${id}Z`,
  id,
  data: { worker: name, status, last_run: `2026-07-26T12:00:0${id}Z`, details },
})

// An ERROR event frame (base loops publish one alongside an error status).
const err = (source, message, id) => ({
  type: 'error',
  timestamp: `2026-07-26T12:00:0${id}Z`,
  id,
  data: { message, source },
})

describe('toLoops', () => {
  it('groups loops by functional area with per-category count + ok/total', () => {
    // ci_monitor -> repo_health, retrospective -> learning, adr_conformance -> governance
    const vm = toLoops([
      worker('ci_monitor'),
      worker('retrospective'),
      worker('adr_conformance'),
    ])
    const byName = Object.fromEntries(vm.categories.map(c => [c.name, c]))
    expect(byName['Repo Health'].count).toBe(1)
    expect(byName['Repo Health'].ok).toBe(1)
    expect(byName['Learning & Insights'].loops[0].key).toBe('retrospective')
    expect(byName['Governance & Audit'].loops[0].key).toBe('adr_conformance')
  })

  it('orders categories by the canonical WORKER_GROUPS order', () => {
    const vm = toLoops([
      worker('adr_conformance'), // governance (3rd)
      worker('ci_monitor'), // repo_health (1st)
      worker('retrospective'), // learning (2nd)
    ])
    expect(vm.categories.map(c => c.key)).toEqual(['repo_health', 'learning', 'governance'])
  })

  it('resolves a curated display name from the worker key', () => {
    const vm = toLoops([worker('staging_promotion')])
    expect(vm.categories[0].loops[0].name).toBe('Staging Promotion')
    expect(vm.categories[0].key).toBe('release')
  })

  it('derives severity: ok when running, bad when errored', () => {
    const vm = toLoops([
      worker('ci_monitor', { status: 'ok' }),
      worker('flake_tracker', { status: 'error' }),
    ])
    const loops = vm.categories.flatMap(c => c.loops)
    const ci = loops.find(l => l.key === 'ci_monitor')
    const flake = loops.find(l => l.key === 'flake_tracker')
    expect(ci.severity).toBe('ok')
    expect(flake.severity).toBe('bad')
  })

  it('marks a currently-ok but recently-restarted loop as warn', () => {
    // status is ok now, but the event history shows two error cycles.
    const events = [
      bg('ci_monitor', 'ok', 5),
      bg('ci_monitor', 'error', 3),
      bg('ci_monitor', 'error', 2),
    ]
    const vm = toLoops(events)
    const loop = vm.categories.flatMap(c => c.loops).find(l => l.key === 'ci_monitor')
    expect(loop.severity).toBe('warn')
    expect(loop.restarts).toBe(2)
  })

  it('marks a disabled loop as muted regardless of status', () => {
    const vm = toLoops([worker('ci_monitor', { enabled: false, status: 'ok' })])
    expect(vm.categories[0].loops[0].severity).toBe('muted')
    expect(vm.totals.disabled).toBe(1)
  })

  it('summarizes the details stats into a last message (dropping redundant status)', () => {
    const vm = toLoops([worker('auto_tighten', { details: { status: 'ok', tightened: 2, held: 1 } })])
    expect(vm.categories[0].loops[0].lastMessage).toBe('tightened=2, held=1')
  })

  it('correlates the latest ERROR-event message onto a bad loop', () => {
    const events = [
      bg('adr_conformance', 'error', 3),
      err('adr_conformance', 'Adr conformance loop error', 3),
    ]
    const vm = toLoops(events)
    const loop = vm.categories.flatMap(c => c.loops).find(l => l.key === 'adr_conformance')
    expect(loop.severity).toBe('bad')
    expect(loop.lastError).toBe('Adr conformance loop error')
  })

  it('accepts the backgroundWorkers slice with a separate events array for restarts', () => {
    const workers = [worker('ci_monitor', { status: 'ok' })]
    const events = [bg('ci_monitor', 'error', 2)]
    const vm = toLoops(workers, { events })
    const loop = vm.categories.flatMap(c => c.loops).find(l => l.key === 'ci_monitor')
    expect(loop.restarts).toBe(1)
    expect(loop.severity).toBe('warn')
  })

  it('drops unregistered workers — pipeline WORKFLOW stages and release promotion are not loops', () => {
    // Loops == registered BACKGROUND_WORKERS only. The workflow stages
    // (triage/plan/build/review, driven by the max_triagers/max_planners pools)
    // and the staging<->main release-promotion flow are not background loops and
    // must never render in the Loops panel (#10556 follow-up).
    const vm = toLoops([
      worker('ci_monitor'),   // registered background loop -> kept
      worker('triage'),       // pipeline workflow stage    -> dropped
      worker('plan'),         // pipeline workflow stage    -> dropped
      worker('mystery_loop'), // unknown / not a loop       -> dropped
    ])
    const keys = vm.categories.flatMap(c => c.loops.map(l => l.key))
    expect(keys).toEqual(['ci_monitor'])
    expect(vm.totals.total).toBe(1)
    // no catch-all 'Other' category is produced for non-loops
    expect(vm.categories.some(c => c.name === 'Other')).toBe(false)
  })

  it('rolls up totals across all loops', () => {
    const vm = toLoops(
      [
        worker('ci_monitor', { status: 'ok' }),
        worker('flake_tracker', { status: 'error' }),
        worker('retrospective', { enabled: false }),
      ],
      { events: [bg('ci_monitor', 'error', 1)] },
    )
    expect(vm.totals.total).toBe(3)
    expect(vm.totals.disabled).toBe(1)
    expect(vm.totals.restarted).toBe(1) // ci_monitor had an error cycle
    // ok = ok + muted: ci_monitor(warn) is NOT ok, flake(bad) NOT ok, retro(muted) ok
    expect(vm.totals.ok).toBe(1)
  })

  it('returns empty structure for empty/absent input', () => {
    expect(toLoops(undefined)).toEqual({ categories: [], totals: { ok: 0, total: 0, restarted: 0, disabled: 0 } })
    expect(toLoops([])).toEqual({ categories: [], totals: { ok: 0, total: 0, restarted: 0, disabled: 0 } })
  })

  it('is pure — identical input yields deeply-equal output', () => {
    const workers = [worker('ci_monitor'), worker('retrospective')]
    expect(toLoops(workers)).toEqual(toLoops(workers))
  })
})

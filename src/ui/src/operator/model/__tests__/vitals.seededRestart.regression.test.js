import { describe, it, expect } from 'vitest'
import { toVitals } from '../vitals'

// Regression for #10751 (sampled re-audit of PR #10739): the orchestrator's
// boot seed republishes each loop's *persisted* last status as a fresh
// `background_worker_status` event — including `error` when a loop was in error
// when the process last stopped. The restart tally counts every error event in
// the WS window, so without a marker every restart phantom-inflates the
// Restarts panel for any loop that was errored at shutdown, even though nothing
// failed in the new session. Seeded replays now carry `seeded: true` and the
// tally skips them; a genuine live failure (no `seeded`) is still counted.

// A boot-seed replay event, as `orchestrator._seed_background_worker_statuses`
// publishes it.
const seedEvent = (name, status, id) => ({
  type: 'background_worker_status',
  timestamp: '2026-07-27T12:00:00Z',
  id,
  data: { worker: name, status, last_run: null, details: {}, enabled: true, seeded: true },
})

// A live per-cycle event, as `base_background_loop` publishes it (no `seeded`).
const liveEvent = (name, status, id) => ({
  type: 'background_worker_status',
  timestamp: '2026-07-27T12:00:01Z',
  id,
  data: { worker: name, status, last_run: null, details: {} },
})

describe('toVitals restart tally excludes boot-seed replays (#10751)', () => {
  it('does not count a seeded error replay as a restart', () => {
    // Loop was in error at last shutdown; the boot seed replays that status.
    const events = [seedEvent('loop_boom', 'error', 1)]
    const vm = toVitals(events, { backgroundWorkers: [] })
    expect(vm.restarts).toEqual([])
  })

  it('still counts a live error cycle as a restart', () => {
    const events = [liveEvent('loop_boom', 'error', 2)]
    const vm = toVitals(events, { backgroundWorkers: [] })
    expect(vm.restarts).toEqual([{ loop: 'loop_boom', count: 1 }])
  })

  it('counts only the live failure when a seeded replay and a live error coexist', () => {
    // The boot replay of a prior-session error PLUS one genuine failure this
    // session → the panel should read exactly one restart, not two.
    const events = [
      seedEvent('loop_boom', 'error', 1),
      liveEvent('loop_boom', 'error', 2),
    ]
    const vm = toVitals(events, { backgroundWorkers: [] })
    expect(vm.restarts).toEqual([{ loop: 'loop_boom', count: 1 }])
  })
})

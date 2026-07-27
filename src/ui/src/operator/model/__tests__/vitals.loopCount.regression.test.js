import { describe, it, expect } from 'vitest'
import { toVitals } from '../vitals'

// Regression for #10556: the operator Vitals "Loops healthy" count fluctuated
// while running (observed 55/55 → 33/33). Root cause: toVitals derived
// loopsHealthy.total by scanning the bounded, newest-first WS *events* ring
// buffer, which is a moving window — high-frequency loops (transcript,
// github-cache, health-monitor) flood it while slow loops (pricing-refresh,
// wiki-maint, RC-promotion — hours-long intervals) have their last status age
// out, so they vanish from the window and `total` shrinks (55 → 33). The count
// was a window artifact, not the loop registry.
//
// The fix reads the reducer's STICKY `backgroundWorkers` slice (accumulated per
// name in HydraFlowContext, never evicted) — the same source `toLoops` uses.
// These tests pin that the count is registry-stable even when the event window
// only witnesses a subset of the loops.

// A sticky-slice worker as the reducer's `background_worker_status` case stores it.
const worker = (name, status = 'ok', enabled = true) => ({
  name, status, last_run: null, details: {}, enabled, interval_seconds: null, repo: null,
})

// A `background_worker_status` WS event as the (bounded) ring buffer stores it.
const bgEvent = (name, status, id) => ({
  type: 'background_worker_status',
  timestamp: '2026-07-26T12:00:00Z',
  id,
  data: { worker: name, status, last_run: null, details: {} },
})

describe('toVitals loop-health count is registry-stable (#10556, 55→33 fluctuation)', () => {
  it('takes total from the sticky backgroundWorkers slice, not the shrinking event window', () => {
    // 55 loops known to the reducer (the loop registry).
    const backgroundWorkers = Array.from({ length: 55 }, (_, i) => worker(`loop_${i}`))
    // The bounded event window only carries recent status for 33 of them — the
    // other 22 slow loops have aged out of the ring buffer.
    const events = Array.from({ length: 33 }, (_, i) => bgEvent(`loop_${i}`, 'ok', i))

    const vm = toVitals(events, { backgroundWorkers })

    // Registry-stable: 55, NOT the 33 the moving window would have produced.
    expect(vm.loopsHealthy.total).toBe(55)
    expect(vm.loopsHealthy.total).not.toBe(33)
    expect(vm.loopsHealthy.ok).toBe(55)
  })

  it('derives ok from the slice: one enabled loop in error → ok = total - 1', () => {
    const backgroundWorkers = [
      ...Array.from({ length: 54 }, (_, i) => worker(`loop_${i}`)),
      worker('loop_boom', 'error'),
    ]
    // The event window is irrelevant to the count now.
    const events = [bgEvent('loop_0', 'ok', 0)]

    const vm = toVitals(events, { backgroundWorkers })

    expect(vm.loopsHealthy.total).toBe(55)
    expect(vm.loopsHealthy.ok).toBe(54)
  })

  it('counts an intentionally-disabled loop as healthy (matches toLoops muted)', () => {
    const backgroundWorkers = [
      worker('loop_a', 'ok'),
      worker('loop_off', 'ok', false), // disabled → healthy, not a defect
    ]
    const vm = toVitals([], { backgroundWorkers })
    expect(vm.loopsHealthy).toEqual({ ok: 2, total: 2 })
  })

  it('falls back to the event-window computation when no slice is threaded', () => {
    // Backward-compat for older callers/tests without extras.backgroundWorkers.
    const events = [
      bgEvent('loop_c', 'error', 5),
      bgEvent('loop_b', 'ok', 4),
      bgEvent('loop_a', 'ok', 3),
    ]
    const vm = toVitals(events)
    expect(vm.loopsHealthy).toEqual({ ok: 2, total: 3 })
  })
})

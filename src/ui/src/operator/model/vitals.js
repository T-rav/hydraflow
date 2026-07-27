/**
 * Vitals view-model adapter for the operator console (epic #10556, Task 1).
 *
 * Pure, deterministic transform of the existing event stream into the compact
 * health readout that replaces the scattered `Loop … crashed` / `system alert`
 * / credit lines. No backend change; no React; no side effects — timestamps and
 * signals are read from the events/args, never from Date.now().
 *
 * Output shape (Task 1 interface):
 *   toVitals(events, extras?) -> {
 *     factory: { state, reason },
 *     loopsHealthy: { ok, total },
 *     restarts: [{ loop, count }],
 *     credits: { paused, pausedUntil, provider },
 *     mainStagingSync: { state, openPrNumber },
 *   }
 *
 * `events` is the WebSocket event array (newest-first, as the reducer stores
 * it). `extras.stagingPromotion` is the REST payload from
 * `/api/staging-promotion/status` — the main↔staging sync signal is not carried
 * on the WS bus, so it is threaded in explicitly rather than invented.
 *
 * `extras.backgroundWorkers` is the reducer's STICKY `backgroundWorkers` slice
 * (the deduped `background_worker_status` state, keyed by name and never
 * evicted). Loop-health `{ok,total}` is derived from it — not the bounded,
 * newest-first events window — so the count reflects the loop registry rather
 * than a moving window (see the loop-health block below and #10556).
 */

/**
 * Build the vitals view model.
 * @param {Array} events - WS events, newest-first
 * @param {{ stagingPromotion?: object, backgroundWorkers?: Array }} [extras]
 */
export function toVitals(events, extras = {}) {
  const list = events || []

  // ---- Factory run-state + credits (latest orchestrator_status) ----
  const latestOrch = list.find(e => e?.type === 'orchestrator_status')?.data ?? null
  const pausedUntil = latestOrch?.credits_paused_until ?? null
  const provider = latestOrch?.credits_paused_provider ?? null
  const creditsPaused = !!pausedUntil

  let factoryState
  let reason = null
  if (creditsPaused) {
    factoryState = 'paused'
    reason = `credits paused until ${pausedUntil}`
  } else if (latestOrch?.status) {
    factoryState = latestOrch.status
  } else {
    factoryState = 'unknown'
  }

  const credits = {
    paused: creditsPaused,
    pausedUntil,
    provider: creditsPaused ? provider : null,
  }

  // ---- Restarts (recent error cycles from the event window) ----
  // Restart tally is genuinely a recent-history signal: the sticky slice only
  // carries each loop's *current* status, not a count of how many times it has
  // errored, so restarts are always read from the event window (mirrors how
  // `toLoops` correlates restart counts by worker name).
  const errorCountByLoop = new Map()
  for (const e of list) {
    if (e?.type !== 'background_worker_status') continue
    const worker = e.data?.worker
    if (!worker) continue
    if (e.data?.status === 'error') {
      errorCountByLoop.set(worker, (errorCountByLoop.get(worker) ?? 0) + 1)
    }
  }
  const restarts = [...errorCountByLoop.entries()]
    .map(([loop, count]) => ({ loop, count }))
    .sort((a, b) => (b.count - a.count) || a.loop.localeCompare(b.loop))

  // ---- Loop health {ok,total} ----
  // Prefer the reducer's STICKY `backgroundWorkers` slice (accumulated per name,
  // never evicted) so the count is the loop registry, not a moving window. The
  // WS events ring buffer is bounded + newest-first, so low-frequency loops
  // (pricing-refresh, wiki-maint, RC-promotion — hours-long intervals) have
  // their last status age out of the window and vanish, shrinking an
  // event-derived total (the 55→33 fluctuation, #10556). A worker counts toward
  // `ok` unless it is enabled AND currently in error — an intentionally-disabled
  // loop reads as healthy, matching how `toLoops`/`LoopsPanel` count `muted`.
  const sticky = Array.isArray(extras?.backgroundWorkers) ? extras.backgroundWorkers : null
  let total = 0
  let ok = 0
  if (sticky) {
    total = sticky.length
    for (const w of sticky) {
      if (w?.enabled === false || w?.status !== 'error') ok += 1
    }
  } else {
    // Backward-compat: older callers/tests without the slice fall back to the
    // event-window computation (moving-window total, but nothing else to use).
    const latestStatusByLoop = new Map() // newest-first → first seen is latest
    for (const e of list) {
      if (e?.type !== 'background_worker_status') continue
      const worker = e.data?.worker
      if (!worker) continue
      if (!latestStatusByLoop.has(worker)) {
        latestStatusByLoop.set(worker, e.data?.status ?? 'ok')
      }
    }
    total = latestStatusByLoop.size
    for (const status of latestStatusByLoop.values()) {
      if (status !== 'error') ok += 1
    }
  }

  // ---- main ↔ staging sync (REST-sourced) ----
  const sp = extras?.stagingPromotion
  let mainStagingSync
  if (!sp) {
    mainStagingSync = { state: 'unknown', openPrNumber: null }
  } else if (sp.open_promotion_pr) {
    mainStagingSync = { state: 'behind', openPrNumber: sp.open_promotion_pr.number ?? null }
  } else {
    mainStagingSync = { state: 'in_sync', openPrNumber: null }
  }

  return {
    factory: { state: factoryState, reason },
    loopsHealthy: { ok, total },
    restarts,
    credits,
    mainStagingSync,
  }
}

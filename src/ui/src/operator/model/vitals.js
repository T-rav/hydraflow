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
 */

/**
 * Build the vitals view model.
 * @param {Array} events - WS events, newest-first
 * @param {{ stagingPromotion?: object }} [extras]
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

  // ---- Loop health + restarts (background_worker_status) ----
  const latestStatusByLoop = new Map() // newest-first → first seen is latest
  const errorCountByLoop = new Map()
  for (const e of list) {
    if (e?.type !== 'background_worker_status') continue
    const worker = e.data?.worker
    if (!worker) continue
    if (!latestStatusByLoop.has(worker)) {
      latestStatusByLoop.set(worker, e.data?.status ?? 'ok')
    }
    if (e.data?.status === 'error') {
      errorCountByLoop.set(worker, (errorCountByLoop.get(worker) ?? 0) + 1)
    }
  }
  const total = latestStatusByLoop.size
  let ok = 0
  for (const status of latestStatusByLoop.values()) {
    if (status !== 'error') ok += 1
  }
  const restarts = [...errorCountByLoop.entries()]
    .map(([loop, count]) => ({ loop, count }))
    .sort((a, b) => (b.count - a.count) || a.loop.localeCompare(b.loop))

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

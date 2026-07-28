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

import { stageDurationLabel } from './pipeline'

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
  //
  // Skip boot-seed replays (`seeded === true`): the orchestrator's boot seed
  // republishes each loop's *persisted* last status, so a loop that was in
  // error when the process last stopped would otherwise phantom-inflate the
  // restart count on every restart even though nothing failed this session
  // (#10751). A real live failure comes through the per-cycle path with no
  // `seeded` flag and is still counted.
  const errorCountByLoop = new Map()
  for (const e of list) {
    if (e?.type !== 'background_worker_status') continue
    if (e.data?.seeded === true) continue
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

/**
 * Best-effort factory-start timestamp (epoch-ms) from the socket state, or
 * `null` when no start signal is available. Prefers the current run session's
 * `started_at`; falls back to the newest still-active session; last resort is a
 * session id that encodes its start as a trailing `<YYYYMMDDTHHMMSS>` stamp
 * (e.g. `acme-web-20260727T221406`). Pure — never reads the wall clock.
 *
 * @param {{ sessions?: Array, currentSessionId?: string|null }} [socket]
 * @returns {number|null}
 */
export function factoryStartMs({ sessions, currentSessionId } = {}) {
  const list = Array.isArray(sessions) ? sessions : []

  // Prefer the current session, then any still-active session.
  let session = null
  if (currentSessionId != null) {
    session = list.find(s => s?.id === currentSessionId) ?? null
  }
  if (!session) {
    session = list.find(s => s?.status === 'active') ?? null
  }

  const startedAt = session?.started_at ?? null
  if (startedAt != null) {
    const ms = Date.parse(startedAt)
    if (!Number.isNaN(ms)) return ms
  }

  // Last resort: a session id that encodes its start (<repo>-YYYYMMDDTHHMMSS).
  return parseSessionIdStamp(currentSessionId ?? session?.id ?? null)
}

/** Parse a trailing `YYYYMMDDTHHMMSS` stamp out of a session id (UTC). */
function parseSessionIdStamp(id) {
  if (typeof id !== 'string') return null
  const m = /(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/.exec(id)
  if (!m) return null
  const [, y, mo, d, h, mi, s] = m
  const ms = Date.parse(`${y}-${mo}-${d}T${h}:${mi}:${s}Z`)
  return Number.isNaN(ms) ? null : ms
}

/**
 * Compact factory runtime/uptime label ("2h14m", "12m", "45s") from the socket's
 * best start signal, measured against an injected `now`. Returns '' when no
 * start signal exists so the caller can render nothing. Pure — `now` is passed
 * in, never read from `Date.now()` here (mirrors `stageDurationLabel`).
 *
 * @param {{ sessions?: Array, currentSessionId?: string|null }} socket
 * @param {number|string} now - epoch-ms (or ISO)
 * @returns {string}
 */
export function factoryUptimeLabel(socket, now) {
  const startMs = factoryStartMs(socket)
  if (startMs == null) return ''
  return stageDurationLabel(startMs, now)
}

/**
 * Loops view-model adapter for the operator console (epic #10556 follow-up).
 *
 * Pure, deterministic transform of the existing background-worker telemetry into
 * the "all loops quick view": every background loop grouped by functional area,
 * with per-category counts and per-loop status + the relevant recent message.
 * No backend change — the data already flows over the WS bus.
 *
 * Two honest sources, both already in the frontend:
 *   - Per-loop status/last_run/details/enabled/interval come from the reducer's
 *     `backgroundWorkers` slice (the deduped `background_worker_status` state),
 *     or, when passed a raw event array, are reduced here the same way `toVitals`
 *     reduces loop health (newest-first, first-seen-per-loop is the latest).
 *   - The per-loop CATEGORY is NOT in the WS payload. It is sourced from the
 *     UI-native `BACKGROUND_WORKERS` map in `src/constants.js` — each worker's
 *     `group` field (the same grouping the System > Workers tab and
 *     `docs/arch/functional_areas.yml` are kept in sync with) — plus the ordered
 *     `WORKER_GROUPS` list for category order + display labels.
 *
 * Restart counts + error messages are correlated by worker name from the event
 * history (mirrors `toVitals`' name-keyed restart tally). A worker with no live
 * status is not invented; only loops that have reported are shown.
 *
 * Output shape:
 *   toLoops(workerStatus | events, { events }?) -> {
 *     categories: [{ key, name, count, ok, loops: [{
 *       id, key, name, status, severity, lastMessage, lastError,
 *       restarts, lastRunTs, enabled, interval,
 *     }] }],
 *     totals: { ok, total, restarted, disabled },
 *   }
 *
 * No React, no side effects: given the same input it returns the same output.
 */

import { BACKGROUND_WORKERS, WORKER_GROUPS } from '../../constants'

// worker key (snake_case, === WS `data.worker`) -> { label, group }
const WORKER_META = new Map(
  BACKGROUND_WORKERS.map(w => [w.key, { label: w.label, group: w.group }]),
)
// group key -> display label, in the canonical WORKER_GROUPS order.
const GROUP_LABEL = new Map(WORKER_GROUPS.map(g => [g.key, g.label]))
const GROUP_ORDER = WORKER_GROUPS.map(g => g.key)

// The catch-all bucket for a reported loop with no `group` in the UI map.
const OTHER_KEY = 'other'
const OTHER_LABEL = 'Other'

// Statuses that read as an actively-broken loop (base loops emit only ok/error,
// but the watchdog + future statuses are handled defensively).
const BAD_STATUSES = new Set(['error', 'wedged', 'failed', 'crashed', 'timeout'])

// Severity paint order: problems first, off/quiet last.
const SEVERITY_RANK = { bad: 0, warn: 1, ok: 2, muted: 3 }

/** True when `input` is a raw HydraFlow event array (carries `type`, not `name`). */
function looksLikeEvents(arr) {
  return arr.some(e => e && typeof e === 'object' && e.type !== undefined)
}

/**
 * Reduce a newest-first event array to the latest `background_worker_status`
 * snapshot per worker — the same "first seen wins" reduction `toVitals` uses.
 */
function snapshotsFromEvents(events) {
  const seen = new Map()
  for (const e of events) {
    if (e?.type !== 'background_worker_status') continue
    const worker = e.data?.worker
    if (!worker || seen.has(worker)) continue
    seen.set(worker, {
      name: worker,
      status: e.data?.status ?? 'ok',
      last_run: e.data?.last_run ?? null,
      details: e.data?.details ?? {},
      enabled: e.data?.enabled ?? true,
      interval_seconds: e.data?.interval_seconds ?? null,
    })
  }
  return [...seen.values()]
}

/** Normalize the primary input into a per-loop snapshot array. */
function resolveWorkers(input) {
  if (!Array.isArray(input) || input.length === 0) return []
  if (looksLikeEvents(input)) return snapshotsFromEvents(input)
  // Already the reducer's `backgroundWorkers` slice — keep the latest per name.
  const seen = new Map()
  for (const w of input) {
    if (w?.name == null) continue
    seen.set(w.name, w)
  }
  return [...seen.values()]
}

/** Count error-status cycles per worker across the event history. */
function countErrorCycles(events) {
  const counts = new Map()
  for (const e of events) {
    if (e?.type !== 'background_worker_status') continue
    if (e.data?.status !== 'error') continue
    const worker = e.data?.worker
    if (!worker) continue
    counts.set(worker, (counts.get(worker) ?? 0) + 1)
  }
  return counts
}

/** Latest ERROR-event message per source (worker name), newest-first wins. */
function latestErrorMessages(events) {
  const messages = new Map()
  for (const e of events) {
    if (e?.type !== 'error') continue
    const source = e.data?.source
    const message = e.data?.message
    if (!source || !message || messages.has(source)) continue
    messages.set(source, message)
  }
  return messages
}

/** Prettify a snake_case worker key when it has no curated label. */
function prettifyKey(key) {
  return key
    .split('_')
    .filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

/**
 * Severity from status + enabled + restart history.
 *   disabled -> muted (intentionally off)
 *   error/wedged/... -> bad
 *   recently restarted (still ok) -> warn
 *   otherwise -> ok
 */
function severityFor(status, enabled, restarts) {
  if (enabled === false) return 'muted'
  if (BAD_STATUSES.has(String(status ?? '').toLowerCase())) return 'bad'
  if (restarts > 0) return 'warn'
  return 'ok'
}

/** Human-readable one-liner from a loop's `details` stats dict. */
function summarizeDetails(details) {
  if (!details || typeof details !== 'object') return null
  for (const field of ['message', 'summary', 'detail', 'note']) {
    const v = details[field]
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  const parts = Object.entries(details)
    .filter(([k, v]) => k !== 'status' && v != null && typeof v !== 'object')
    .map(([k, v]) => `${k}=${v}`)
  return parts.length ? parts.join(', ') : null
}

/**
 * Build the loops view model.
 * @param {Array|Object} input - `backgroundWorkers` slice OR a raw event array
 * @param {{ events?: Array }} [extras] - raw events for restart/error correlation
 */
export function toLoops(input, extras = {}) {
  const workers = resolveWorkers(input)
  const events = Array.isArray(extras.events)
    ? extras.events
    : (Array.isArray(input) && looksLikeEvents(input) ? input : [])

  const restartCounts = countErrorCycles(events)
  const errorMessages = latestErrorMessages(events)

  const loops = workers.map(w => {
    const key = w.name
    const meta = WORKER_META.get(key)
    const enabled = w.enabled !== false
    const restarts = restartCounts.get(key) ?? 0
    const severity = severityFor(w.status, enabled, restarts)
    const detailsMessage = summarizeDetails(w.details)
    const lastError = severity === 'bad'
      ? (errorMessages.get(key)
          ?? (typeof w.details?.error === 'string' ? w.details.error : null))
      : null

    return {
      id: key,
      key,
      name: meta?.label ?? prettifyKey(key),
      group: meta?.group ?? OTHER_KEY,
      status: w.status ?? 'unknown',
      severity,
      lastMessage: detailsMessage,
      lastError,
      restarts,
      lastRunTs: w.last_run ?? null,
      enabled,
      interval: w.interval_seconds ?? null,
    }
  })

  // Group into categories keyed by the loop's functional area.
  const byGroup = new Map()
  for (const loop of loops) {
    if (!byGroup.has(loop.group)) byGroup.set(loop.group, [])
    byGroup.get(loop.group).push(loop)
  }

  // Category order: canonical WORKER_GROUPS order first, then any unknown groups
  // (alphabetical), with the catch-all 'other' bucket always last.
  const presentGroups = [...byGroup.keys()]
  const orderedGroups = [
    ...GROUP_ORDER.filter(g => byGroup.has(g)),
    ...presentGroups
      .filter(g => !GROUP_ORDER.includes(g) && g !== OTHER_KEY)
      .sort((a, b) => a.localeCompare(b)),
    ...(byGroup.has(OTHER_KEY) ? [OTHER_KEY] : []),
  ]

  const categories = orderedGroups.map(groupKey => {
    const groupLoops = byGroup.get(groupKey).slice().sort(
      (a, b) => (SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]) || a.name.localeCompare(b.name),
    )
    const ok = groupLoops.filter(l => l.severity === 'ok' || l.severity === 'muted').length
    return {
      key: groupKey,
      name: groupKey === OTHER_KEY ? OTHER_LABEL : (GROUP_LABEL.get(groupKey) ?? prettifyKey(groupKey)),
      count: groupLoops.length,
      ok,
      loops: groupLoops,
    }
  })

  const totals = {
    total: loops.length,
    ok: loops.filter(l => l.severity === 'ok' || l.severity === 'muted').length,
    restarted: loops.filter(l => l.restarts > 0).length,
    disabled: loops.filter(l => l.enabled === false).length,
  }

  return { categories, totals }
}

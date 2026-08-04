/**
 * Finder-faceplate view-model for the operator console (#10826).
 *
 * Pure `toFinderFaceplates(raw)` — no fetch, no React. Turns the
 * `GET /api/diagnostics/finder-faceplates` payload (`{ finders: [row...],
 * generated_at }`, one row per generative finder in the calibration catalog)
 * into a stable shape the panel renders:
 *
 *   {
 *     total: number,            // finders in the payload (the catalog is 6)
 *     calibratedCount: number,  // finders with a measured noise floor
 *     aboveFloorCount: number,  // finders whose live rate exceeds their floor
 *     headerLabel: string,      // one glanceable line ("2 of 6 calibrated; 1 above floor")
 *     calibrated: [ Row ],      // rows with a floor, catalog order
 *     pending:    [ Row ],      // uncalibrated (deferred LLM) finders, catalog order
 *   }
 *
 * where each normalized Row (camelCase) is
 *
 *   {
 *     finderId, signalClass, calibrated, status, liveRate, label,
 *     // calibrated rows only:
 *     floorMean, floorSigma, floorLabel, threshold, sampleCount,
 *     lowConfidence, baselineVetted, baselineStale, baselineSha,
 *     lastCalibrated, driftDays, provisional, stale,
 *   }
 *
 * `status` mirrors the backend: `within_floor` (live output is indistinguishable
 * from the finder's own noise — a gain-down candidate), `above_floor` (live
 * output clears the floor — the finder is earning its keep), or `uncalibrated`
 * (no floor measured yet). `floorLabel` renders the noise floor as "mean ± sigma"
 * — or "mean ±0 deterministic" when the floor has zero variance (a finder that
 * flags the exact same count on every clean run). `provisional` folds the
 * engine's own low-confidence gate together with an unvetted baseline
 * (`baseline_vetted === false`): an unvouched "clean" tree miscalibrates
 * silently, so the panel must treat its floor as provisional, never authoritative.
 *
 * A missing / malformed / empty payload yields the frozen EMPTY view model,
 * never throws — a failed or empty feed leaves the panel rendering its calm
 * empty state.
 */

/** Faceplate statuses — the single source the model + panel agree on. */
export const STATUS_WITHIN_FLOOR = 'within_floor'
export const STATUS_ABOVE_FLOOR = 'above_floor'
export const STATUS_UNCALIBRATED = 'uncalibrated'
const KNOWN_STATUSES = new Set([STATUS_WITHIN_FLOOR, STATUS_ABOVE_FLOOR, STATUS_UNCALIBRATED])

/** The calm one-liner an uncalibrated finder's row carries. */
const PENDING_LABEL = 'pending — run calibration'

/** Frozen empty view model — the fallback for a missing / malformed payload. */
export const EMPTY_FINDER_FACEPLATES_VM = Object.freeze({
  total: 0,
  calibratedCount: 0,
  aboveFloorCount: 0,
  headerLabel: 'no finders',
  calibrated: Object.freeze([]),
  pending: Object.freeze([]),
})

function num(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

/** Coerce a live-rate to a number, preserving a genuine `null` (never 0-for-null). */
function liveRateOf(value) {
  if (value == null) return null // null/undefined → "no live rate", not 0
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

/** Render one finder's noise floor: "mean ±0 deterministic" when sigma is 0. */
function floorLabelOf(mean, sigma) {
  return sigma === 0 ? `${mean} ±0 deterministic` : `${mean} ± ${sigma}`
}

/** Normalize one raw faceplate row into a camelCase Row. */
function toRow(raw) {
  const o = raw && typeof raw === 'object' ? raw : {}
  const calibrated = o.calibrated === true
  const status = KNOWN_STATUSES.has(o.status)
    ? o.status
    : calibrated
      ? STATUS_WITHIN_FLOOR
      : STATUS_UNCALIBRATED
  const row = {
    finderId: String(o.finder_id ?? ''),
    signalClass: String(o.signal_class ?? ''),
    calibrated,
    status,
    liveRate: liveRateOf(o.live_rate),
  }

  // Uncalibrated (deferred LLM) finders carry only identity + a pending label —
  // the endpoint omits floor fields, and the count is never invented.
  if (!calibrated) {
    row.label = PENDING_LABEL
    return row
  }

  const floorMean = num(o.floor_mean)
  const floorSigma = num(o.floor_sigma)
  // Tri-state: true (aged past freshness), false (fresh), null (unknown — no
  // vetted baseline to age). Only an explicit boolean is trusted.
  const baselineStale =
    o.baseline_stale === true ? true : o.baseline_stale === false ? false : null
  // An unvetted baseline miscalibrates silently, so fold it into the caveat
  // alongside the engine's own too-few-samples low_confidence gate.
  const provisional = o.low_confidence === true || o.baseline_vetted === false

  row.floorMean = floorMean
  row.floorSigma = floorSigma
  row.floorLabel = floorLabelOf(floorMean, floorSigma)
  row.threshold = num(o.threshold)
  row.sampleCount = num(o.sample_count)
  row.lowConfidence = o.low_confidence === true
  row.baselineVetted = o.baseline_vetted === true
  row.baselineStale = baselineStale
  row.baselineSha = String(o.baseline_sha ?? '')
  row.lastCalibrated = String(o.last_calibrated ?? '')
  row.driftDays = num(o.drift_days)
  row.provisional = provisional
  row.stale = baselineStale === true
  row.label =
    row.liveRate == null
      ? `floor ${row.floorLabel} (no live rate)`
      : `live ${row.liveRate} vs floor ${row.floorLabel}`
  return row
}

/** Pull the finder list out of the payload (`{finders}` or a bare array). */
function rawFinders(raw) {
  if (Array.isArray(raw)) return raw
  if (raw && typeof raw === 'object' && Array.isArray(raw.finders)) return raw.finders
  return null
}

/**
 * @param {unknown} raw The `/finder-faceplates` payload (`{finders, generated_at}` or an array).
 * @returns {{total, calibratedCount, aboveFloorCount, headerLabel, calibrated, pending}}
 */
export function toFinderFaceplates(raw) {
  const list = rawFinders(raw)
  if (!Array.isArray(list) || list.length === 0) return EMPTY_FINDER_FACEPLATES_VM

  const rows = list.filter(r => r && typeof r === 'object').map(toRow)
  if (rows.length === 0) return EMPTY_FINDER_FACEPLATES_VM

  const calibrated = rows.filter(r => r.calibrated)
  const pending = rows.filter(r => !r.calibrated)
  const aboveFloorCount = rows.filter(r => r.status === STATUS_ABOVE_FLOOR).length

  return {
    total: rows.length,
    calibratedCount: calibrated.length,
    aboveFloorCount,
    headerLabel: `${calibrated.length} of ${rows.length} calibrated; ${aboveFloorCount} above floor`,
    calibrated,
    pending,
  }
}

export default toFinderFaceplates

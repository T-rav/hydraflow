/**
 * Loop-faceplate view-model for the operator console (#10826).
 *
 * Pure `toLoopFaceplates(raw, backgroundWorkers)` — no fetch, no React.
 * Joins the STATIC control-register payload from
 * `GET /api/diagnostics/loop-faceplates` (`{ loops: [row...], counts,
 * generated_at }`, one row per `control/fleet.yaml` entry) against the LIVE
 * `backgroundWorkers` slice the console already holds from the
 * BACKGROUND_WORKER_STATUS bus — the same client-side join the LoopsPanel
 * performs. The endpoint deliberately serves no live telemetry; serving it
 * twice would create a second, slower copy of the same signal.
 *
 *   {
 *     total: number,             // fleet size (65 today)
 *     regulatingCount: number,   // loops with an ACTIVE (signed) setpoint
 *     signedCount: number,       // setpoints signed (may exceed regulating if loop down)
 *     headerLabel: string,       // "65 loops · 2 convertible · 1 regulating"
 *     byClass: { [cls]: n },     // census from the endpoint's counts
 *     rows: [ Row ],             // regulator classes first, then name order
 *   }
 *
 * where each Row is
 *
 *   {
 *     workerName, controlClass, pvLabel, finderId, floorSigma,   // static
 *     setpoint: null | { value, band, units, direction, signed, signedBy, authority },
 *     live: { pv, quiescent, setpointActive, lastRunTs, enabled },
 *     mode: 'auto' | 'quiescent' | 'unconverted',
 *   }
 *
 * Honesty rules: absence of the regulator keys in a worker's `details` means
 * "not converted" — `pv: null`, mode `unconverted` — never zero. `floorSigma`
 * null means "cannot sense" (no finder join or uncalibrated), rendered as
 * absence. A missing / malformed payload yields the frozen EMPTY view model.
 */

/** Faceplate modes — the single source the model + panel agree on. */
export const MODE_AUTO = 'auto'
export const MODE_QUIESCENT = 'quiescent'
export const MODE_UNCONVERTED = 'unconverted'

/** Frozen empty view model — the fallback for a missing / malformed payload. */
export const EMPTY_LOOP_FACEPLATES_VM = Object.freeze({
  total: 0,
  regulatingCount: 0,
  signedCount: 0,
  headerLabel: 'no loops',
  byClass: Object.freeze({}),
  rows: Object.freeze([]),
})

/** Coerce to a finite number, preserving a genuine `null` (never 0-for-null). */
function numOrNull(value) {
  if (value == null) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function toSetpoint(raw) {
  if (!raw || typeof raw !== 'object') return null
  return {
    value: numOrNull(raw.value),
    band: numOrNull(raw.band),
    units: String(raw.units ?? ''),
    direction: String(raw.direction ?? 'above'),
    signed: raw.signed === true,
    signedBy: raw.signed_by == null ? null : String(raw.signed_by),
    authority: String(raw.authority ?? ''),
  }
}

/** The live half from a worker's BACKGROUND_WORKER_STATUS details. */
function toLive(worker) {
  const details =
    worker && typeof worker.details === 'object' && worker.details !== null
      ? worker.details
      : {}
  return {
    pv: numOrNull(details.pv_pass_rate),
    quiescent: details.quiescent === true ? true : details.quiescent === false ? false : null,
    setpointActive:
      details.setpoint_active === true
        ? true
        : details.setpoint_active === false
          ? false
          : null,
    lastRunTs: worker && worker.last_run != null ? String(worker.last_run) : null,
    enabled: worker ? worker.enabled !== false : null,
  }
}

/** Mode: only a loop actively regulating can be auto/quiescent. */
function modeOf(live) {
  if (live.setpointActive !== true) return MODE_UNCONVERTED
  return live.quiescent === true ? MODE_QUIESCENT : MODE_AUTO
}

function toRow(raw, workersByName) {
  const o = raw && typeof raw === 'object' ? raw : {}
  const workerName = String(o.worker_name ?? '')
  const live = toLive(workersByName.get(workerName))
  return {
    workerName,
    controlClass: String(o.control_class ?? ''),
    pvLabel: String(o.pv_label ?? ''),
    finderId: String(o.finder_id ?? ''),
    floorSigma: numOrNull(o.floor_sigma),
    setpoint: toSetpoint(o.setpoint),
    live,
    mode: modeOf(live),
  }
}

function rawLoops(raw) {
  if (raw && typeof raw === 'object' && Array.isArray(raw.loops)) return raw.loops
  return null
}

/**
 * @param {unknown} raw The `/loop-faceplates` payload (`{loops, counts, generated_at}`).
 * @param {Array<{name, details, last_run, enabled}>} backgroundWorkers Live WS slice.
 */
export function toLoopFaceplates(raw, backgroundWorkers) {
  const list = rawLoops(raw)
  if (!Array.isArray(list) || list.length === 0) return EMPTY_LOOP_FACEPLATES_VM

  const workersByName = new Map(
    (Array.isArray(backgroundWorkers) ? backgroundWorkers : [])
      .filter(w => w && typeof w === 'object' && w.name != null)
      .map(w => [String(w.name), w]),
  )

  const rows = list.filter(r => r && typeof r === 'object').map(r => toRow(r, workersByName))
  if (rows.length === 0) return EMPTY_LOOP_FACEPLATES_VM

  const byClass =
    raw.counts && typeof raw.counts === 'object' ? { ...raw.counts } : {}
  const signedCount = rows.filter(r => r.setpoint && r.setpoint.signed).length
  const regulatingCount = rows.filter(r => r.live.setpointActive === true).length
  const convertible = Number(byClass.convertible ?? 0)

  return {
    total: rows.length,
    regulatingCount,
    signedCount,
    headerLabel: `${rows.length} loops · ${convertible} convertible · ${regulatingCount} regulating`,
    byClass,
    rows,
  }
}

export default toLoopFaceplates

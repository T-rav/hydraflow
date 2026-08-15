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
 *     awaitingCount: number,     // signed but the loop hasn't ticked since (#11232)
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
 *     intervalS,                                               // tick cadence (null = unknown)
 *     setpoint: null | { value, band, units, direction, signed, signedBy, signedDate, authority },
 *     live: { pv, quiescent, setpointActive, lastRunTs, enabled },
 *     mode: 'auto' | 'quiescent' | 'unconverted'
 *         | 'awaiting_tick' | 'not_engaged',
 *     dueAt,                    // ISO — last tick + interval, awaiting rows only
 *     overdue,                  // awaiting && dueAt has passed (loop is late)
 *   }
 *
 * Honesty rules: absence of the regulator keys in a worker's `details` means
 * "not converted" — `pv: null`, mode `unconverted` — never zero. `floorSigma`
 * null means "cannot sense" (no finder join or uncalibrated), rendered as
 * absence. A missing / malformed payload yields the frozen EMPTY view model.
 *
 * #11232: a SIGNED setpoint whose loop hasn't ticked since signing renders
 * `awaiting_tick` with `dueAt = lastTick + intervalS` — an explicit
 * intermediate state instead of the blank lamp that read "signing didn't
 * take" for up to a full weekly cadence. If the loop HAS ticked since the
 * signing date and still reports `setpoint_active: false`, that is the
 * genuine fault `not_engaged`. `signed_date` is date-granular, so the split
 * compares dates: a same-day tick reads as pre-signing (benign — the loop is
 * demonstrably alive); a missing `signed_date` also stays benign.
 */

/** Faceplate modes — the single source the model + panel agree on. */
export const MODE_AUTO = 'auto'
export const MODE_QUIESCENT = 'quiescent'
export const MODE_UNCONVERTED = 'unconverted'
export const MODE_AWAITING_TICK = 'awaiting_tick'
export const MODE_NOT_ENGAGED = 'not_engaged'

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
    signedDate: raw.signed_date == null ? null : String(raw.signed_date),
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

/** Did the loop tick after the setpoint was signed (date-granular)? A
 * missing/unparseable signedDate can't answer — false keeps the row in the
 * benign awaiting state, never a false not-engaged accusation. */
function tickedSinceSigning(live, setpoint) {
  if (!live.lastRunTs || !setpoint.signedDate) return false
  const lastRunDay = String(live.lastRunTs).slice(0, 10)
  const signedDay = setpoint.signedDate.slice(0, 10)
  if (lastRunDay.length < 10 || signedDay.length < 10) return false
  return lastRunDay > signedDay
}

/** Mode: only a loop actively regulating can be auto/quiescent. A signed
 * setpoint that hasn't been read yet splits awaiting_tick vs not_engaged on
 * whether the loop has ticked since the signing date (#11232). */
function modeOf(live, setpoint) {
  if (live.setpointActive === true) {
    return live.quiescent === true ? MODE_QUIESCENT : MODE_AUTO
  }
  if (!setpoint || !setpoint.signed) return MODE_UNCONVERTED
  return tickedSinceSigning(live, setpoint) ? MODE_NOT_ENGAGED : MODE_AWAITING_TICK
}

function toRow(raw, workersByName, now) {
  const o = raw && typeof raw === 'object' ? raw : {}
  const workerName = String(o.worker_name ?? '')
  const live = toLive(workersByName.get(workerName))
  const intervalS = numOrNull(o.interval_s)
  const setpoint = toSetpoint(o.setpoint)
  const mode = modeOf(live, setpoint)
  // due = last tick + cadence; unknown cadence or no tick ever → null
  // ("due unknown"), never an invented date.
  const dueAtMs =
    mode === MODE_AWAITING_TICK && live.lastRunTs && intervalS != null
      ? Date.parse(live.lastRunTs) + intervalS * 1000
      : null
  const dueAt = dueAtMs != null && !Number.isNaN(dueAtMs)
    ? new Date(dueAtMs).toISOString()
    : null
  return {
    workerName,
    controlClass: String(o.control_class ?? ''),
    pvLabel: String(o.pv_label ?? ''),
    finderId: String(o.finder_id ?? ''),
    floorSigma: numOrNull(o.floor_sigma),
    intervalS,
    setpoint,
    live,
    mode,
    dueAt,
    overdue: mode === MODE_AWAITING_TICK && dueAt != null && Date.parse(dueAt) <= now,
  }
}

function rawLoops(raw) {
  if (raw && typeof raw === 'object' && Array.isArray(raw.loops)) return raw.loops
  return null
}

/**
 * @param {unknown} raw The `/loop-faceplates` payload (`{loops, counts, generated_at}`).
 * @param {Array<{name, details, last_run, enabled}>} backgroundWorkers Live WS slice.
 * @param {{ now?: number }} [options] Injected clock (ms epoch) for the
 *   overdue classification — deterministic in tests, wall clock by default.
 */
export function toLoopFaceplates(raw, backgroundWorkers, { now = Date.now() } = {}) {
  const list = rawLoops(raw)
  if (!Array.isArray(list) || list.length === 0) return EMPTY_LOOP_FACEPLATES_VM

  const workersByName = new Map(
    (Array.isArray(backgroundWorkers) ? backgroundWorkers : [])
      .filter(w => w && typeof w === 'object' && w.name != null)
      .map(w => [String(w.name), w]),
  )

  const rows = list
    .filter(r => r && typeof r === 'object')
    .map(r => toRow(r, workersByName, now))
  if (rows.length === 0) return EMPTY_LOOP_FACEPLATES_VM

  const byClass =
    raw.counts && typeof raw.counts === 'object' ? { ...raw.counts } : {}
  const signedCount = rows.filter(r => r.setpoint && r.setpoint.signed).length
  const regulatingCount = rows.filter(r => r.live.setpointActive === true).length
  const awaitingCount = rows.filter(r => r.mode === MODE_AWAITING_TICK).length
  const convertible = Number(byClass.convertible ?? 0)
  // The awaiting suffix appears only when something IS awaiting — the
  // zero-awaiting header stays byte-identical to the pre-#11232 label.
  const awaitingSuffix = awaitingCount > 0 ? ` · ${awaitingCount} awaiting` : ''

  return {
    total: rows.length,
    regulatingCount,
    awaitingCount,
    signedCount,
    headerLabel: `${rows.length} loops · ${convertible} convertible · ${regulatingCount} regulating${awaitingSuffix}`,
    byClass,
    rows,
  }
}

export default toLoopFaceplates

/**
 * Judge-calibration view-model for the operator console (#10836).
 *
 * Pure `toJudgeCalibration(raw)` — no fetch, no React. Turns the
 * `GET /api/diagnostics/judge-calibration` payload
 * (`{ judges: [JudgeScore...], resolved_total, grace_window_days, generated_at }`,
 * one row per review judge — e.g. `post_verify`) into a stable shape the panel
 * renders:
 *
 *   {
 *     total: number,          // judges in the payload
 *     scoredCount: number,    // judges with resolved verdicts (a score exists)
 *     resolvedTotal: number,  // total resolved verdicts across all judges
 *     graceWindowDays: number,// days a verdict waits before its outcome resolves
 *     headerLabel: string,    // one glanceable line ("1 of 2 scored · 14 resolved")
 *     scored:  [ Row ],       // judges with a proper score, judgeId order
 *     pending: [ Row ],       // judges still awaiting resolved verdicts, judgeId order
 *   }
 *
 * where each normalized Row (camelCase) is
 *
 *   {
 *     judgeId, judgeFamily, nResolved, scored, status, label,
 *     // scored rows only:
 *     brier, brierLabel, logScore,
 *     calibrationError, calibrationLabel,          // ECE — the calibration axis
 *     discrimination, discriminationLabel,         // AUC — the discrimination axis
 *     discriminationUndefined, lowConfidence, provisional,
 *   }
 *
 * The two axes are kept DELIBERATELY SEPARATE — a judge can be well-calibrated
 * (ECE ≈ 0) yet non-discriminating (AUC ≈ 0.5), or vice-versa; collapsing them
 * into one number hides exactly the failure the instrument exists to surface.
 * So the panel shows `calibrationError` (lower is better) and `discrimination`
 * (higher is better; 0.5 = coin-flip) side by side, never a blended grade.
 * `brier` is the overall proper score (lower is better).
 *
 * `status` is a DATA-SUFFICIENCY state, not a quality verdict: `scored` (enough
 * resolved verdicts to score), or `pending` (none resolved yet — the calm
 * awaiting state, mirroring the faceplate's uncalibrated finders). A scored
 * judge with too few resolved verdicts carries `provisional` (the engine's
 * `low_confidence` gate) — its scores exist but shouldn't be trusted as
 * authoritative. `discriminationUndefined` (AUC has no meaning when every
 * resolved outcome is the same class) renders AUC as "n/a", never a fake 0.5.
 *
 * A missing / malformed / empty payload yields the frozen EMPTY view model,
 * never throws — a failed or empty feed leaves the panel rendering its calm
 * empty state.
 */

/** Judge data-sufficiency states — the single source the model + panel agree on. */
export const STATUS_SCORED = 'scored'
export const STATUS_PENDING = 'pending'

/** The calm one-liner a not-yet-resolved judge's row carries. */
const PENDING_LABEL = 'awaiting resolved verdicts'

/** AUC has no meaning when every resolved outcome is one class — never fake a 0.5. */
const AUC_UNDEFINED_LABEL = 'n/a'

/** Frozen empty view model — the fallback for a missing / malformed payload. */
export const EMPTY_JUDGE_CALIBRATION_VM = Object.freeze({
  total: 0,
  scoredCount: 0,
  resolvedTotal: 0,
  graceWindowDays: 0,
  headerLabel: 'no judges',
  scored: Object.freeze([]),
  pending: Object.freeze([]),
})

function num(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

/** A finite float or null (never coerce a genuine null-score to 0). */
function scoreOrNull(value) {
  if (value == null) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

/** Round to 3 decimals for a compact, stable label. */
function round3(n) {
  return Math.round(n * 1000) / 1000
}

/** Render a 0..1 score, or an em-dash for a missing one. */
function scoreLabel(value) {
  return value == null ? '—' : String(round3(value))
}

/** Normalize one raw JudgeScore into a camelCase Row. */
function toRow(raw) {
  const o = raw && typeof raw === 'object' ? raw : {}
  const nResolved = num(o.n_resolved)
  const brier = scoreOrNull(o.brier)
  // A judge is "scored" once it has resolved verdicts with a computed score.
  const scored = nResolved > 0 && brier != null

  const row = {
    judgeId: String(o.judge_id ?? ''),
    judgeFamily: String(o.judge_family ?? ''),
    nResolved,
    scored,
    status: scored ? STATUS_SCORED : STATUS_PENDING,
  }

  if (!scored) {
    row.label = PENDING_LABEL
    return row
  }

  const discrimination = scoreOrNull(o.discrimination)
  const discriminationUndefined = o.discrimination_undefined === true
  const calibrationError = scoreOrNull(o.calibration_error)

  row.brier = brier
  row.brierLabel = scoreLabel(brier)
  row.logScore = scoreOrNull(o.log_score)
  row.calibrationError = calibrationError
  row.calibrationLabel = scoreLabel(calibrationError)
  row.discrimination = discrimination
  row.discriminationLabel = discriminationUndefined
    ? AUC_UNDEFINED_LABEL
    : scoreLabel(discrimination)
  row.discriminationUndefined = discriminationUndefined
  row.lowConfidence = o.low_confidence === true
  // Too few resolved verdicts → the scores exist but aren't authoritative.
  row.provisional = o.low_confidence === true
  return row
}

/** Pull the judge list out of the payload (`{judges}` or a bare array). */
function rawJudges(raw) {
  if (Array.isArray(raw)) return raw
  if (raw && typeof raw === 'object' && Array.isArray(raw.judges)) return raw.judges
  return null
}

/** Stable display order: by judgeId ascending (the payload order isn't contractual). */
function byJudgeId(a, b) {
  return a.judgeId < b.judgeId ? -1 : a.judgeId > b.judgeId ? 1 : 0
}

/**
 * @param {unknown} raw The `/judge-calibration` payload (`{judges, resolved_total,
 *   grace_window_days, generated_at}` or a bare array).
 * @returns {{total, scoredCount, resolvedTotal, graceWindowDays, headerLabel, scored, pending}}
 */
export function toJudgeCalibration(raw) {
  const list = rawJudges(raw)
  if (!Array.isArray(list) || list.length === 0) return EMPTY_JUDGE_CALIBRATION_VM

  const rows = list.filter(r => r && typeof r === 'object').map(toRow)
  if (rows.length === 0) return EMPTY_JUDGE_CALIBRATION_VM

  const scored = rows.filter(r => r.scored).sort(byJudgeId)
  const pending = rows.filter(r => !r.scored).sort(byJudgeId)
  const envelope = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}
  // Prefer the payload's authoritative resolved_total; fall back to summing rows.
  const resolvedTotal =
    envelope.resolved_total != null
      ? num(envelope.resolved_total)
      : rows.reduce((sum, r) => sum + r.nResolved, 0)
  const graceWindowDays = num(envelope.grace_window_days)

  return {
    total: rows.length,
    scoredCount: scored.length,
    resolvedTotal,
    graceWindowDays,
    headerLabel: `${scored.length} of ${rows.length} scored · ${resolvedTotal} resolved`,
    scored,
    pending,
  }
}

export default toJudgeCalibration

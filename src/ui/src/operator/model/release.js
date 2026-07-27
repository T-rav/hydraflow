/**
 * Release-promotion view-model adapter for the operator console (epic #10556
 * follow-up).
 *
 * Pure, deterministic transform of the staging↔main promotion telemetry into the
 * compact strip the operator console renders. No backend change, no React, no
 * side effects — given the same input it returns the same output (never reads
 * Date.now(); every timestamp comes straight from the payload).
 *
 * The operator console separates three concepts that were previously blurred:
 * WORKFLOW (triage→plan→build→review), RELEASE PROMOTION (staging↔main), and
 * LOOPS (background workers). This adapter owns the RELEASE PROMOTION slice.
 *
 * Two honest sources, both already in the frontend:
 *   - `stagingPromotion` — the REST payload from `/api/staging-promotion/status`
 *     (`enabled`, `cadence_hours`, `cadence_progress_hours`, `last_rc_cut_at`,
 *     `open_promotion_pr: { number, branch, url }`, recent throughput). The
 *     two-tier branch model is ADR-0042: the factory runs on `staging`; `main`
 *     advances only via auto-promoted `rc/YYYY-MM-DD-HHMM` PRs cut by the
 *     StagingPromotionLoop every `cadence_hours`.
 *   - `extras.backgroundWorkers` — the reducer's sticky `backgroundWorkers` slice
 *     (deduped `background_worker_status`, keyed by name). The StagingPromotionLoop
 *     reports under the `staging_promotion` worker key; its status feeds `loop`.
 *
 * State machine (see `deriveState`): an open `rc/` promotion PR is a promotion in
 * flight → 'promoting'; staging ahead of main with no PR yet → 'behind'; nothing
 * pending → 'in_sync'; no payload / promotion disabled → 'unknown'.
 *
 * Output shape:
 *   toReleasePromotion(stagingPromotion, extras?) -> {
 *     state: 'in_sync'|'behind'|'promoting'|'unknown',
 *     enabled: boolean,
 *     commitsAhead: number|null,
 *     openPr: { number, url }|null,
 *     lastRc: { name, ts }|null,
 *     cadenceHours: number|null,
 *     cadenceProgressHours: number|null,
 *     loop: { status, severity }|null,
 *   }
 */

// The StagingPromotionLoop's background-worker key (=== WS `data.worker`).
const PROMOTION_WORKER = 'staging_promotion'

// Statuses that read as an actively-broken loop (mirrors model/loops.js).
const BAD_STATUSES = new Set(['error', 'wedged', 'failed', 'crashed', 'timeout'])

/** Severity for the promotion loop worker: disabled→muted, broken→bad, else ok. */
function loopSeverity(status, enabled) {
  if (enabled === false) return 'muted'
  if (BAD_STATUSES.has(String(status ?? '').toLowerCase())) return 'bad'
  return 'ok'
}

/** The StagingPromotionLoop's sticky worker snapshot as `{ status, severity }`, or null. */
function findPromotionLoop(backgroundWorkers) {
  if (!Array.isArray(backgroundWorkers)) return null
  // Sticky slice is deduped by name; keep the last occurrence to mirror the reducer.
  let found = null
  for (const w of backgroundWorkers) {
    if (w?.name === PROMOTION_WORKER) found = w
  }
  if (!found) return null
  const enabled = found.enabled !== false
  return { status: found.status ?? 'unknown', severity: loopSeverity(found.status, enabled) }
}

/** First finite number among the candidates, else null (tolerates camel/snake keys). */
function firstNumber(...candidates) {
  for (const v of candidates) {
    if (typeof v === 'number' && Number.isFinite(v)) return v
  }
  return null
}

/**
 * Derive the promotion state.
 *   disabled / no payload  -> 'unknown'
 *   open promotion PR       -> 'promoting'  (an rc/ PR is in flight to main)
 *   staging ahead, no PR    -> 'behind'     (a promotion is due, not yet cut)
 *   otherwise               -> 'in_sync'
 */
function deriveState({ enabled, hasOpenPr, commitsAhead }) {
  if (!enabled) return 'unknown'
  if (hasOpenPr) return 'promoting'
  if (typeof commitsAhead === 'number' && commitsAhead > 0) return 'behind'
  return 'in_sync'
}

/** The empty readout returned when there is no payload to interpret. */
function unknownModel(loop) {
  return {
    state: 'unknown',
    enabled: false,
    commitsAhead: null,
    openPr: null,
    lastRc: null,
    cadenceHours: null,
    cadenceProgressHours: null,
    loop,
  }
}

/**
 * Build the release-promotion view model.
 * @param {object|null|undefined} stagingPromotion - `/api/staging-promotion/status` payload
 * @param {{ backgroundWorkers?: Array }} [extras]
 */
export function toReleasePromotion(stagingPromotion, extras = {}) {
  const loop = findPromotionLoop(extras?.backgroundWorkers)
  const sp = stagingPromotion
  if (!sp || typeof sp !== 'object') return unknownModel(loop)

  const enabled = sp.enabled !== false

  const rawPr = sp.open_promotion_pr ?? sp.openPromotionPr ?? null
  const openPr = rawPr && rawPr.number != null
    ? { number: rawPr.number, url: rawPr.url ?? null }
    : null

  // `commits_ahead` is not part of the current REST payload; read it defensively
  // so the 'behind' state lights up if/when the backend starts publishing it.
  const commitsAhead = firstNumber(sp.commits_ahead, sp.commitsAhead)

  // The most-recent RC is the currently-open one, so its branch is the RC name;
  // `last_rc_cut_at` is the cut timestamp (kept even after the RC has merged).
  const lastRcTs = sp.last_rc_cut_at ?? sp.lastRcCutAt ?? null
  const lastRcName = (rawPr && rawPr.branch) || null
  const lastRc = (lastRcTs || lastRcName) ? { name: lastRcName, ts: lastRcTs } : null

  const cadenceHours = firstNumber(sp.cadence_hours, sp.cadenceHours)
  const cadenceProgressHours = firstNumber(sp.cadence_progress_hours, sp.cadenceProgressHours)

  const state = deriveState({ enabled, hasOpenPr: openPr != null, commitsAhead })

  return {
    state,
    enabled,
    commitsAhead,
    openPr,
    lastRc,
    cadenceHours,
    cadenceProgressHours,
    loop,
  }
}

export default toReleasePromotion

/**
 * Supervisor-thread view-model for the operator console (#10733, ADR-0124).
 *
 * Pure `toSupervisorThread(raw)` — no fetch, no React. Turns the
 * `GET /api/diagnostics/supervisor/thread` payload (the Tier-2 goal-supervisor's
 * append-only observation thread — healthy ticks write nothing, so the thread
 * only carries the non-trivial observations) into a stable shape the panel
 * renders:
 *
 *   {
 *     verdict: 'healthy' | 'degraded' | 'escalations' | 'empty',
 *     verdictLabel: string,        // one glanceable line ("2 escalations pending")
 *     escalationCount: number,     // escalations awaiting a human (latest tick)
 *     count: number,               // observations in the thread
 *     latest: Observation | null,  // newest observation (drives the verdict)
 *     observations: [ Observation ], // NEWEST FIRST
 *   }
 *
 * where each normalized Observation is
 *
 *   {
 *     id: string,                  // stable key (ts + index)
 *     ts: string,
 *     assessment: string,
 *     snapshot: {                  // normalized health snapshot (camelCase)
 *       healthy, stalledLoops, errorLoops, creditFailoverActive,
 *       creditProbeOverdue, bootShaStale, commitsBehind, eventLoopStalled,
 *       vitalsVerdict,
 *     },
 *     insights: [string],
 *     nudges: [string],            // nudges_taken (pending verification)
 *     escalations: [string],       // surfaced, want a human — never self-done
 *     deferred: [string],          // transients waited out / re-run
 *     counts: { insights, nudges, escalations, deferred },
 *     hasEscalations: boolean,     // drives the row's distinct styling
 *   }
 *
 * The verdict is derived from the LATEST (newest) observation, per the honest-
 * thread contract (rule 6/8): a still-present incident re-appears each tick, so
 * the newest observation IS the current state. A missing / malformed payload
 * yields the EMPTY view model, never throws — a failed or empty feed leaves the
 * panel rendering its calm empty state.
 */

/** Frozen empty view model — the fallback for a missing / malformed payload. */
export const EMPTY_SUPERVISOR_VM = Object.freeze({
  verdict: 'empty',
  verdictLabel: 'no observations',
  escalationCount: 0,
  count: 0,
  latest: null,
  observations: Object.freeze([]),
})

function num(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

/** Coerce an arbitrary value to a clean array of trimmed non-empty strings. */
function toStringList(value) {
  if (!Array.isArray(value)) return []
  return value
    .map(v => (typeof v === 'string' ? v : String(v ?? '')))
    .map(s => s.trim())
    .filter(Boolean)
}

/** Parse an ISO-8601 timestamp to epoch ms; 0 when absent / unparseable. */
function epoch(ts) {
  const ms = Date.parse(String(ts ?? ''))
  return Number.isFinite(ms) ? ms : 0
}

/** Normalize the raw health-snapshot summary into a stable camelCase shape. */
function toSnapshot(raw) {
  const s = raw && typeof raw === 'object' ? raw : {}
  return {
    healthy: typeof s.healthy === 'boolean' ? s.healthy : null,
    stalledLoops: toStringList(s.stalled_loops),
    errorLoops: toStringList(s.error_loops),
    creditFailoverActive: Boolean(s.credit_failover_active),
    creditProbeOverdue: Boolean(s.credit_probe_overdue),
    bootShaStale: Boolean(s.boot_sha_stale),
    commitsBehind: num(s.commits_behind),
    eventLoopStalled: Boolean(s.event_loop_stalled),
    vitalsVerdict: String(s.vitals_verdict ?? ''),
  }
}

/** Map + bucket one raw observation record into a normalized Observation. */
function toObservation(raw, index) {
  const o = raw && typeof raw === 'object' ? raw : {}
  const insights = toStringList(o.insights)
  const nudges = toStringList(o.nudges_taken)
  const escalations = toStringList(o.escalations)
  const deferred = toStringList(o.deferred)
  const ts = String(o.ts ?? '')
  return {
    id: `${ts}#${index}`,
    ts,
    assessment: String(o.assessment ?? ''),
    snapshot: toSnapshot(o.snapshot),
    insights,
    nudges,
    escalations,
    deferred,
    counts: {
      insights: insights.length,
      nudges: nudges.length,
      escalations: escalations.length,
      deferred: deferred.length,
    },
    hasEscalations: escalations.length > 0,
  }
}

/** Pull the observation list out of the payload (either `{observations}` or a bare array). */
function rawObservations(raw) {
  if (Array.isArray(raw)) return raw
  if (raw && typeof raw === 'object' && Array.isArray(raw.observations)) return raw.observations
  return null
}

/** Derive the glanceable top-level verdict from the newest observation. */
function deriveVerdict(latest) {
  if (!latest) return { verdict: 'empty', escalationCount: 0, verdictLabel: 'no observations' }
  const escalationCount = latest.escalations.length
  if (escalationCount > 0) {
    return {
      verdict: 'escalations',
      escalationCount,
      verdictLabel: `${escalationCount} escalation${escalationCount === 1 ? '' : 's'} pending`,
    }
  }
  if (latest.snapshot.healthy === false) {
    return { verdict: 'degraded', escalationCount: 0, verdictLabel: 'degraded' }
  }
  return { verdict: 'healthy', escalationCount: 0, verdictLabel: 'healthy' }
}

/**
 * @param {unknown} raw The `/supervisor/thread` payload (`{observations, count}` or an array).
 * @returns {{verdict, verdictLabel, escalationCount, count, latest, observations}}
 */
export function toSupervisorThread(raw) {
  const list = rawObservations(raw)
  if (!Array.isArray(list) || list.length === 0) return EMPTY_SUPERVISOR_VM

  const observations = list
    .filter(r => r && typeof r === 'object')
    .map((r, i) => ({ obs: toObservation(r, i), index: i }))
    // Newest first: sort by timestamp descending, tie-break by input order so a
    // newest-last thread (the endpoint's storage order) surfaces newest-first.
    .sort((a, b) => epoch(b.obs.ts) - epoch(a.obs.ts) || b.index - a.index)
    .map(({ obs }) => obs)

  if (observations.length === 0) return EMPTY_SUPERVISOR_VM

  const latest = observations[0]
  const { verdict, escalationCount, verdictLabel } = deriveVerdict(latest)

  return {
    verdict,
    verdictLabel,
    escalationCount,
    count: observations.length,
    latest,
    observations,
  }
}

export default toSupervisorThread

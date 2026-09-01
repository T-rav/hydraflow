import { PIPELINE_STALENESS_TRIPWIRE_MS } from '../constants'

/**
 * #11350: is the rail rendering a snapshot old enough to be a lie?
 *
 * The rail derives from four surfaces on four cadences (labels, REST
 * snapshot, WS deltas, event-derived workstream). Only the authoritative
 * snapshot reconciles them back to GitHub labels. When that snapshot goes
 * stale — a missed poll, a dropped socket, a server restart — the console
 * must SAY it is resyncing rather than render a confidently-empty or
 * confidently-stale rail (operator repro, 2026-08-15).
 *
 * Never-snapshotted (null) is 'resyncing', not 'fresh': at boot the rail
 * has nothing authoritative behind it yet, which is exactly the empty-rail
 * case operators reported.
 */
export function isPipelineResyncing(snapshotAt, now = Date.now(), tripwireMs = PIPELINE_STALENESS_TRIPWIRE_MS) {
  if (snapshotAt === null || snapshotAt === undefined) return true
  const age = now - snapshotAt
  if (Number.isNaN(age)) return true
  return age >= tripwireMs
}

/**
 * #11924: is the rail untrustworthy right now, by EITHER signal?
 *
 * The rail carries two independent staleness signals and neither implies the
 * other. `snapshotReady` is the server saying this snapshot is not
 * authoritative yet (#11279). `snapshotAt` is the freshness stamp the reducer
 * clears whenever it empties the rail outside the snapshot path — session
 * reset, repo switch, orchestrator restart (#11414).
 *
 * Two consumers derived the answer two different ways: the operator console
 * from the stamp, StreamView from the flag. So #11414, which cleared only the
 * stamp, repaired one console and left the other rendering a confidently-empty
 * rail on all three reset paths — the exact lie #11350 exists to prevent,
 * shipped for a second time one component over
 * (escape sampled-audit:11403:0bae96175dde).
 *
 * One question, one answer. Callers pass state and never re-derive it; a
 * signal added here reaches every consumer at once, which is the property
 * that was missing.
 */
export function railIsResyncing(
  { snapshotAt, snapshotReady } = {},
  now = Date.now(),
  tripwireMs = PIPELINE_STALENESS_TRIPWIRE_MS,
) {
  if (snapshotReady === false) return true
  return isPipelineResyncing(snapshotAt, now, tripwireMs)
}

/** Age in ms of the last authoritative snapshot (null when never taken). */
export function pipelineSnapshotAgeMs(snapshotAt, now = Date.now()) {
  if (snapshotAt === null || snapshotAt === undefined) return null
  return Math.max(0, now - snapshotAt)
}

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

/** Age in ms of the last authoritative snapshot (null when never taken). */
export function pipelineSnapshotAgeMs(snapshotAt, now = Date.now()) {
  if (snapshotAt === null || snapshotAt === undefined) return null
  return Math.max(0, now - snapshotAt)
}

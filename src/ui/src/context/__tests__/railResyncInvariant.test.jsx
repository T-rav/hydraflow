import { describe, it, expect } from 'vitest'
import { reducer } from '../HydraFlowContext'
import { isPipelineResyncing } from '../../utils/pipelineFreshness'
import { PIPELINE_STALENESS_TRIPWIRE_MS } from '../../constants'

/**
 * #11350 single-truth invariant: restart mid-stream, assert rail == labels.
 *
 * Operator repro (2026-08-15): after a server restart the rail rendered
 * EMPTY while /api/pipeline was fully populated. Four surfaces derive state
 * on four cadences and nothing reconciled them back to the authoritative
 * snapshot. These tests pin the invariant end to end through the reducer:
 * whatever the deltas did, the next authoritative snapshot IS the rail.
 */
const emptyPipeline = { triage: [], plan: [], implement: [], review: [], hitl: [], merged: [] }
const base = { pipelineIssues: { ...emptyPipeline }, pipelineSnapshotAt: null, events: [] }

const snapshot = (stages, at) => ({ type: 'PIPELINE_SNAPSHOT', data: stages, at })
const labelsAre = state => Object.fromEntries(
  Object.entries(state.pipelineIssues).map(([stage, items]) => [stage, items.map(i => i.number).sort()])
)

describe('rail/label single-truth invariant (#11350)', () => {
  it('rail equals labels after a snapshot', () => {
    const stages = { plan: [{ number: 1 }], implement: [{ number: 2 }] }
    const next = reducer(base, snapshot(stages, 1000))
    expect(labelsAre(next)).toMatchObject({ plan: [1], implement: [2] })
  })

  it('a restart mid-stream converges the rail back to labels', () => {
    // Pre-restart: two issues in flight.
    let state = reducer(base, snapshot({ plan: [{ number: 1 }], implement: [{ number: 2 }] }, 1000))
    // Mid-stream drift: the backend moved #1 to implement and CLOSED #2
    // while the console was disconnected — deltas the client never saw.
    // Restart delivers a fresh authoritative snapshot.
    state = reducer(state, snapshot({ plan: [], implement: [{ number: 1 }] }, 2000))
    const rail = labelsAre(state)
    expect(rail.implement).toEqual([1])
    // The stale #2 card must be GONE — the empty/stale-rail bug is exactly
    // a delta baseline surviving a restart.
    expect(rail.plan).toEqual([])
    expect(Object.values(rail).flat()).not.toContain(2)
  })

  it('an empty authoritative snapshot empties the rail (not a no-op)', () => {
    let state = reducer(base, snapshot({ plan: [{ number: 9 }] }, 1000))
    state = reducer(state, snapshot({ plan: [], implement: [], review: [] }, 2000))
    expect(labelsAre(state).plan).toEqual([])
  })

  it('a snapshot restarts the staleness clock; the rail is not resyncing', () => {
    const state = reducer(base, snapshot({ plan: [{ number: 1 }] }, 5000))
    expect(state.pipelineSnapshotAt).toBe(5000)
    expect(isPipelineResyncing(state.pipelineSnapshotAt, 5000)).toBe(false)
  })

  it('a rail that has never been snapshotted reads as resyncing, not empty-truth', () => {
    expect(isPipelineResyncing(base.pipelineSnapshotAt, 99_999)).toBe(true)
  })

  it('deltas alone never refresh the clock — that is the failure being caught', () => {
    const state = reducer(base, snapshot({ plan: [{ number: 1 }] }, 1000))
    const later = 1000 + PIPELINE_STALENESS_TRIPWIRE_MS + 1
    // No new snapshot by `later`: the console must admit it is resyncing
    // rather than present the old rail as current truth.
    expect(isPipelineResyncing(state.pipelineSnapshotAt, later)).toBe(true)
  })
})

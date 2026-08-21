import { describe, it, expect } from 'vitest'
import { reducer } from '../HydraFlowContext'
import { isPipelineResyncing } from '../../utils/pipelineFreshness'

/**
 * #11414 (sampled re-audit of #11350): clearing the rail OUTSIDE the
 * authoritative-snapshot path must also clear its freshness stamp.
 *
 * Otherwise a repo switch or session reset empties pipelineIssues while
 * pipelineSnapshotAt still reads fresh — the console then presents a
 * confidently-EMPTY rail as current truth, which is precisely the lie the
 * tripwire was built to prevent.
 */
const emptyPipeline = { triage: [], plan: [], implement: [], review: [], hitl: [], merged: [] }
const seeded = () => reducer(
  { pipelineIssues: { ...emptyPipeline }, pipelineSnapshotAt: null, events: [] },
  { type: 'PIPELINE_SNAPSHOT', data: { plan: [{ number: 1 }] }, at: 1000 },
)

describe('rail freshness resets with the rail (#11414)', () => {
  it('a snapshot leaves the rail fresh', () => {
    const state = seeded()
    expect(state.pipelineSnapshotAt).toBe(1000)
    expect(isPipelineResyncing(state.pipelineSnapshotAt, 1000)).toBe(false)
  })

  it('SESSION_RESET clears the stamp with the rail', () => {
    const state = reducer(seeded(), { type: 'SESSION_RESET' })
    expect(state.pipelineIssues.plan).toEqual([])
    expect(state.pipelineSnapshotAt).toBeNull()
    expect(isPipelineResyncing(state.pipelineSnapshotAt, 2000)).toBe(true)
  })

  it('never shows a fresh clock over an empty rail', () => {
    for (const action of [{ type: 'SESSION_RESET' }]) {
      const state = reducer(seeded(), action)
      const railEmpty = Object.values(state.pipelineIssues).every(v => v.length === 0)
      if (railEmpty) {
        expect(state.pipelineSnapshotAt).toBeNull()
      }
    }
  })
})

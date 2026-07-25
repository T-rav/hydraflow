import { describe, it, expect } from 'vitest'
import { STAGE_KEYS } from '../../hooks/useTimeline'
import { buildSyntheticStages, currentStageStatus, overallStatus } from '../stageStatus'

// Backs StreamView.toStreamIssue — the single chokepoint that fabricates a
// StreamCard-shaped stages map from a raw PipelineIssue snapshot entry.
// Extracted so the stage/status vocabulary mapping is unit-testable in
// isolation from React rendering, mirroring the pipelineTracks.js precedent
// of deriving behaviour from PIPELINE_STAGES properties (#10509).

describe('currentStageStatus', () => {
  it('maps merged to done', () => {
    expect(currentStageStatus({ status: 'merged' })).toBe('done')
  })

  it('maps active to active', () => {
    expect(currentStageStatus({ status: 'active' })).toBe('active')
  })

  it('maps processing to active', () => {
    expect(currentStageStatus({ status: 'processing' })).toBe('active')
  })

  it('maps failed to failed', () => {
    expect(currentStageStatus({ status: 'failed' })).toBe('failed')
  })

  it('maps hitl to hitl', () => {
    expect(currentStageStatus({ status: 'hitl' })).toBe('hitl')
  })

  it('maps queued to queued', () => {
    expect(currentStageStatus({ status: 'queued' })).toBe('queued')
  })

  it('maps an unknown status to queued', () => {
    expect(currentStageStatus({ status: 'something_else' })).toBe('queued')
  })

  it('maps an undefined status to queued', () => {
    expect(currentStageStatus({})).toBe('queued')
  })
})

describe('overallStatus', () => {
  it('maps hitl to hitl', () => {
    expect(overallStatus({ status: 'hitl' })).toBe('hitl')
  })

  it('maps failed to failed', () => {
    expect(overallStatus({ status: 'failed' })).toBe('failed')
  })

  it('maps error to failed', () => {
    expect(overallStatus({ status: 'error' })).toBe('failed')
  })

  it('maps merged to done', () => {
    expect(overallStatus({ status: 'merged' })).toBe('done')
  })

  it('maps active to active', () => {
    expect(overallStatus({ status: 'active' })).toBe('active')
  })

  it('maps processing to active', () => {
    expect(overallStatus({ status: 'processing' })).toBe('active')
  })

  it('maps queued to queued', () => {
    expect(overallStatus({ status: 'queued' })).toBe('queued')
  })

  it('maps an unknown status to queued', () => {
    expect(overallStatus({ status: 'something_else' })).toBe('queued')
  })
})

describe('buildSyntheticStages', () => {
  it('marks every stage before the current index as done', () => {
    const stages = buildSyntheticStages({ status: 'active' }, 'review')
    expect(stages.triage.status).toBe('done')
    expect(stages.plan.status).toBe('done')
    expect(stages.implement.status).toBe('done')
  })

  it('marks the current stage from currentStageStatus', () => {
    const stages = buildSyntheticStages({ status: 'active' }, 'implement')
    expect(stages.implement.status).toBe('active')
  })

  it('marks every stage after the current index as pending', () => {
    const stages = buildSyntheticStages({ status: 'active' }, 'plan')
    expect(stages.implement.status).toBe('pending')
    expect(stages.review.status).toBe('pending')
    expect(stages.hitl.status).toBe('pending')
    expect(stages.merged.status).toBe('pending')
  })

  it('returns an entry for every STAGE_KEYS with status/startTime/endTime/transcript', () => {
    const stages = buildSyntheticStages({ status: 'active' }, 'plan')
    for (const key of STAGE_KEYS) {
      expect(stages).toHaveProperty(key)
      expect(stages[key]).toEqual({ status: expect.any(String), startTime: null, endTime: null, transcript: [] })
    }
  })

  it('skips hitl (pending, hollow) for a merged issue that never visited hitl', () => {
    const stages = buildSyntheticStages({ status: 'merged', hitl_visited: false }, 'merged')
    expect(stages.hitl.status).toBe('pending')
    expect(stages.merged.status).toBe('done')
  })

  it('skips hitl (pending, hollow) when hitl_visited is absent (old payloads)', () => {
    const stages = buildSyntheticStages({ status: 'merged' }, 'merged')
    expect(stages.hitl.status).toBe('pending')
  })

  it('fills hitl (done) for a merged issue that previously visited hitl', () => {
    const stages = buildSyntheticStages({ status: 'merged', hitl_visited: true }, 'merged')
    expect(stages.hitl.status).toBe('done')
  })

  it('renders hitl as the live hitl status when the issue currently sits in hitl', () => {
    const stages = buildSyntheticStages({ status: 'hitl' }, 'hitl')
    expect(stages.hitl.status).toBe('hitl')
  })
})

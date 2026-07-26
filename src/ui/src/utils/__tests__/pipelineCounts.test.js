import { describe, it, expect } from 'vitest'
import { countRegion, countPipeline } from '../pipelineCounts'

// countRegion / countPipeline turn StreamView's {stage, issues} groups into
// per-region and per-pipeline issue counts for the pipeline flow region
// header numbers (#10488, PR count dropped in #10593). issues is an array of
// toStreamIssue(...)-shaped objects.

function makeIssue(pr) {
  return { issueNumber: 1, title: 'x', pr }
}

describe('countRegion', () => {
  it('counts a group of 3 issues regardless of whether they carry a pr', () => {
    const group = {
      stage: { key: 'implement' },
      issues: [makeIssue({ number: 1, url: 'u1' }), makeIssue(null), makeIssue({ number: 2, url: 'u2' })],
    }
    expect(countRegion(group)).toEqual({ issues: 3 })
  })

  it('does not expose a prs field on the returned shape', () => {
    const group = {
      stage: { key: 'review' },
      issues: [makeIssue({ number: 1, url: 'u1' })],
    }
    expect(countRegion(group)).not.toHaveProperty('prs')
  })

  it('reports zero counts for an empty group', () => {
    const group = { stage: { key: 'triage' }, issues: [] }
    expect(countRegion(group)).toEqual({ issues: 0 })
  })

  it('reports zero counts when issues is undefined instead of throwing', () => {
    const group = { stage: { key: 'hitl' } }
    expect(countRegion(group)).toEqual({ issues: 0 })
  })
})

describe('countPipeline', () => {
  it('sums per-stage issue counts keyed by stage.key and a grand total across regions', () => {
    const stageGroups = [
      {
        stage: { key: 'triage' },
        issues: [makeIssue(null), makeIssue(null)],
      },
      {
        stage: { key: 'review' },
        issues: [makeIssue({ number: 5, url: 'u5' })],
      },
    ]
    expect(countPipeline(stageGroups)).toEqual({
      perStage: {
        triage: { issues: 2 },
        review: { issues: 1 },
      },
      total: { issues: 3 },
    })
  })

  it('does not expose a prs field on perStage entries or the total', () => {
    const stageGroups = [
      { stage: { key: 'review' }, issues: [makeIssue({ number: 5, url: 'u5' })] },
    ]
    const result = countPipeline(stageGroups)
    expect(result.total).not.toHaveProperty('prs')
    expect(result.perStage.review).not.toHaveProperty('prs')
  })

  it('returns empty perStage and zeroed total for an empty array', () => {
    expect(countPipeline([])).toEqual({ perStage: {}, total: { issues: 0 } })
  })
})

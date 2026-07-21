import { describe, it, expect } from 'vitest'
import { PIPELINE_STAGES } from '../../constants'
import {
  splitPipelineTracks,
  isTerminalStage,
  TERMINAL_TRACK_KEYS,
} from '../pipelineTracks'

// This is the anti-drift lock (#9564): Header's compact pipeline row and
// StreamView's PipelineFlow both derive their triage / linear / terminal-fork
// layout from splitPipelineTracks. Asserting the split against the REAL
// constants means the two renderers can no longer diverge silently.

describe('TERMINAL_TRACK_KEYS', () => {
  it('is exactly the no-role, no-configKey end-states (hitl, merged)', () => {
    expect([...TERMINAL_TRACK_KEYS].sort()).toEqual(['hitl', 'merged'])
  })

  it('derives from PIPELINE_STAGES (role null AND configKey null)', () => {
    const derived = PIPELINE_STAGES.filter(s => !s.role && !s.configKey).map(s => s.key)
    expect([...TERMINAL_TRACK_KEYS]).toEqual(derived)
  })
})

describe('isTerminalStage', () => {
  it('isTerminalStage matches TERMINAL_TRACK_KEYS (hitl, merged)', () => {
    expect(isTerminalStage('hitl')).toBe(true)
    expect(isTerminalStage('merged')).toBe(true)
  })

  it('isTerminalStage is false for worker-bearing stages', () => {
    expect(isTerminalStage('triage')).toBe(false)
    expect(isTerminalStage('plan')).toBe(false)
    expect(isTerminalStage('review')).toBe(false)
  })
})

describe('splitPipelineTracks with the real PIPELINE_STAGES', () => {
  const tracks = splitPipelineTracks(PIPELINE_STAGES)

  it('puts the triage junction on the triage track', () => {
    expect(tracks.triage).not.toBeNull()
    expect(tracks.triage.key).toBe('triage')
  })

  it('routes plan→implement→review into the linear post-triage track', () => {
    expect(tracks.postTriage.map(s => s.key)).toEqual(['plan', 'implement', 'review'])
  })

  it('routes hitl/merged into the terminal fork, hitl before merged', () => {
    expect(tracks.terminal.map(s => s.key)).toEqual(['hitl', 'merged'])
  })

  it('main = every stage, in pipeline order', () => {
    expect(tracks.main.map(s => s.key)).toEqual([
      'triage', 'plan', 'implement', 'review', 'hitl', 'merged',
    ])
  })

  it('partitions every stage into exactly one of postTriage / terminal / triage', () => {
    const covered = [
      tracks.triage.key,
      ...tracks.postTriage.map(s => s.key),
      ...tracks.terminal.map(s => s.key),
    ]
    expect(covered.sort()).toEqual(PIPELINE_STAGES.map(s => s.key).sort())
    expect(new Set(covered).size).toBe(PIPELINE_STAGES.length)
  })
})

describe('splitPipelineTracks with a custom getKey (StreamView group shape)', () => {
  // StreamView feeds {stage, issues} groups through the same splitter.
  const groups = PIPELINE_STAGES.map(stage => ({ stage, issues: [] }))
  const tracks = splitPipelineTracks(groups, g => g.stage.key)

  it('splits the {stage,issues} shape identically to the {key} shape', () => {
    expect(tracks.triage.stage.key).toBe('triage')
    expect(tracks.postTriage.map(g => g.stage.key)).toEqual(['plan', 'implement', 'review'])
    expect(tracks.terminal.map(g => g.stage.key)).toEqual(['hitl', 'merged'])
  })
})

describe('splitPipelineTracks edge cases', () => {
  it('returns empty tracks and null triage for an empty array', () => {
    const tracks = splitPipelineTracks([])
    expect(tracks.triage).toBeNull()
    expect(tracks.postTriage).toEqual([])
    expect(tracks.terminal).toEqual([])
    expect(tracks.main).toEqual([])
  })

  it('tolerates null/undefined input', () => {
    expect(splitPipelineTracks(null).main).toEqual([])
    expect(splitPipelineTracks(undefined).triage).toBeNull()
  })
})

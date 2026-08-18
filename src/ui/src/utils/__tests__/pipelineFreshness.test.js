import { describe, it, expect } from 'vitest'
import { isPipelineResyncing, pipelineSnapshotAgeMs } from '../pipelineFreshness'
import { PIPELINE_STALENESS_TRIPWIRE_MS } from '../../constants'

const NOW = 1_760_000_000_000

describe('pipeline freshness tripwire (#11350)', () => {
  it('treats a never-snapshotted rail as resyncing, not fresh', () => {
    expect(isPipelineResyncing(null, NOW)).toBe(true)
    expect(isPipelineResyncing(undefined, NOW)).toBe(true)
  })

  it('is fresh immediately after a snapshot', () => {
    expect(isPipelineResyncing(NOW, NOW)).toBe(false)
  })

  it('stays fresh inside the tripwire window', () => {
    expect(isPipelineResyncing(NOW - (PIPELINE_STALENESS_TRIPWIRE_MS - 1), NOW)).toBe(false)
  })

  it('trips at the boundary and beyond', () => {
    expect(isPipelineResyncing(NOW - PIPELINE_STALENESS_TRIPWIRE_MS, NOW)).toBe(true)
    expect(isPipelineResyncing(NOW - PIPELINE_STALENESS_TRIPWIRE_MS * 4, NOW)).toBe(true)
  })

  it('reports snapshot age, null when never taken', () => {
    expect(pipelineSnapshotAgeMs(NOW - 5000, NOW)).toBe(5000)
    expect(pipelineSnapshotAgeMs(null, NOW)).toBeNull()
  })

  it('never reports a negative age from clock skew', () => {
    expect(pipelineSnapshotAgeMs(NOW + 5000, NOW)).toBe(0)
  })
})

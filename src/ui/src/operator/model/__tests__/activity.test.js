import { describe, it, expect } from 'vitest'
import { toActivityFeed } from '../activity'

// Events arrive newest-first (as the HydraFlowContext reducer stores them);
// the feed preserves that order and collapses *consecutive* runs.

const transcript = (issue, text, id) => ({
  type: 'transcript_line',
  timestamp: `2026-07-26T12:00:${String(id).padStart(2, '0')}Z`,
  id,
  data: { issue, line: text },
})

const stats = (id) => ({
  type: 'pipeline_stats',
  timestamp: `2026-07-26T12:00:${String(id).padStart(2, '0')}Z`,
  id,
  data: { timestamp: '2026-07-26T12:00:00Z', stages: {}, queue: {}, throughput: {}, uptime_seconds: 1 },
})

const errorEvent = (message, id) => ({
  type: 'error',
  timestamp: `2026-07-26T12:00:${String(id).padStart(2, '0')}Z`,
  id,
  data: { message },
})

const hitl = (issue, id) => ({
  type: 'hitl_escalation',
  timestamp: `2026-07-26T12:00:${String(id).padStart(2, '0')}Z`,
  id,
  data: { issue },
})

const alert = (message, id) => ({
  type: 'system_alert',
  timestamp: `2026-07-26T12:00:${String(id).padStart(2, '0')}Z`,
  id,
  data: { message, severity: 'warning' },
})

const merge = (pr, id) => ({
  type: 'merge_update',
  timestamp: `2026-07-26T12:00:${String(id).padStart(2, '0')}Z`,
  id,
  data: { pr, status: 'merged' },
})

describe('toActivityFeed', () => {
  it('collapses 11 identical transcript lines into one row with count:11', () => {
    const events = Array.from({ length: 11 }, (_, i) => transcript(10493, 'writing file', 20 - i))
    const feed = toActivityFeed(events)
    const transcriptRows = feed.filter(r => r.type === 'transcript_line')
    expect(transcriptRows).toHaveLength(1)
    expect(transcriptRows[0].count).toBe(11)
    expect(transcriptRows[0].groupKey).toBe('transcript:10493')
  })

  it('collapses a run of identical heartbeats into one row with a count', () => {
    const events = [stats(3), stats(2), stats(1)]
    const feed = toActivityFeed(events)
    expect(feed).toHaveLength(1)
    expect(feed[0].count).toBe(3)
    expect(feed[0].severity).toBe('info')
  })

  it('NEVER merges two consecutive error rows (spec §11)', () => {
    const feed = toActivityFeed([errorEvent('boom A', 2), errorEvent('boom B', 1)])
    expect(feed).toHaveLength(2)
    expect(feed.every(r => r.count === 1)).toBe(true)
    expect(feed.every(r => r.severity === 'error')).toBe(true)
  })

  it('NEVER merges consecutive hitl or alert rows (spec §11)', () => {
    const hitlFeed = toActivityFeed([hitl(1, 2), hitl(2, 1)])
    expect(hitlFeed).toHaveLength(2)

    const alertFeed = toActivityFeed([alert('disk low', 2), alert('cpu high', 1)])
    expect(alertFeed).toHaveLength(2)
  })

  it('does not collapse across an interrupting non-groupable event', () => {
    // stats, ERROR, stats → the error breaks the heartbeat run into two rows.
    const feed = toActivityFeed([stats(3), errorEvent('boom', 2), stats(1)])
    expect(feed.map(r => r.type)).toEqual(['pipeline_stats', 'error', 'pipeline_stats'])
    expect(feed.every(r => r.count === 1)).toBe(true)
  })

  it('classifies merges as their own type with info severity', () => {
    const feed = toActivityFeed([merge(528, 1)])
    expect(feed[0].type).toBe('merge_update')
    expect(feed[0].severity).toBe('info')
    expect(feed[0].summary).toContain('528')
  })

  it('preserves newest-first order and carries the newest ts on a collapsed group', () => {
    const events = [transcript(7, 'c', 3), transcript(7, 'b', 2), transcript(7, 'a', 1)]
    const feed = toActivityFeed(events)
    expect(feed[0].ts).toBe('2026-07-26T12:00:03Z')
  })

  it('is pure — identical input yields deeply-equal output', () => {
    const events = [stats(2), errorEvent('x', 1)]
    expect(toActivityFeed(events)).toEqual(toActivityFeed(events))
  })
})

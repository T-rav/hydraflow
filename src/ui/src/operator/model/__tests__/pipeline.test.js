import { describe, it, expect } from 'vitest'
import {
  toPipeline,
  OPERATOR_STAGES,
  WORKFLOW_STAGE_KEYS,
  activeWorkflowItems,
  stageDurationLabel,
  stageColorKey,
  stageTransitionTs,
} from '../pipeline'
import { PIPELINE_STAGES } from '../../../constants'

// Raw event shapes are taken verbatim from the live WebSocket stream as parsed
// by the HydraFlowContext reducer:
//   - `pipeline_snapshot` → { seq, stages: { <stage>: PipelineIssue[] } }
//   - `pipeline_stats`    → PipelineStats { timestamp, stages: { <stage>: StageStats } }
// PipelineIssue: { issue_number, title, status, epic_number, is_epic_child, repo }
// StageStats:    { queued, active, completed_session, worker_count, worker_cap }

const snapshotEvent = (stages, id = 10) => ({
  type: 'pipeline_snapshot',
  timestamp: '2026-07-26T12:00:00Z',
  id,
  data: { seq: 1, stages },
})

const statsEvent = (stages, id = 11) => ({
  type: 'pipeline_stats',
  timestamp: '2026-07-26T12:00:01Z',
  id,
  data: {
    timestamp: '2026-07-26T12:00:01Z',
    stages,
    queue: { queue_depth: {}, active_count: {}, in_flight_count: 0 },
    throughput: { triage: 0, plan: 0, implement: 0, review: 0, hitl: 0 },
    uptime_seconds: 120,
  },
})

const fullStats = {
  triage: { queued: 1, active: 0, completed_session: 3, worker_count: 0, worker_cap: 2 },
  plan: { queued: 0, active: 0, completed_session: 1, worker_count: 0, worker_cap: 2 },
  implement: { queued: 0, active: 1, completed_session: 4, worker_count: 2, worker_cap: 5 },
  review: { queued: 0, active: 1, completed_session: 2, worker_count: 1, worker_cap: 3 },
  hitl: { queued: 4, active: 0, completed_session: 0, worker_count: 0, worker_cap: null },
  merged: { queued: 0, active: 0, completed_session: 9, worker_count: 0, worker_cap: null },
}

const fullSnapshot = {
  triage: [{ issue_number: 101, title: 'Triage me', status: 'queued' }],
  plan: [],
  implement: [
    { issue_number: 201, title: 'Build A', status: 'active' },
    { issue_number: 202, title: 'Build B', status: 'failed' },
  ],
  review: [{ issue_number: 301, title: 'Review me', status: 'active' }],
  hitl: [
    { issue_number: 401, title: 'Stuck 1', status: 'hitl' },
    { issue_number: 402, title: 'Stuck 2', status: 'hitl' },
    { issue_number: 403, title: 'Stuck 3', status: 'hitl' },
    { issue_number: 404, title: 'Stuck 4', status: 'hitl' },
  ],
  merged: [{ issue_number: 501, title: 'Done', status: 'merged' }],
}

describe('toPipeline', () => {
  it('produces the six canonical operator stages in lifecycle order', () => {
    const vm = toPipeline([])
    expect(vm.stages.map(s => s.key)).toEqual([
      'triage', 'plan', 'implement', 'review', 'hitl', 'merged',
    ])
    expect(vm.stages.map(s => s.label)).toEqual([
      'Triage', 'Plan', 'Build', 'Review', 'HITL', 'Merged',
    ])
    // OPERATOR_STAGES is the exported source of truth consumed by later tasks.
    expect(OPERATOR_STAGES).toHaveLength(6)
  })

  it('maps snapshot items to {id,title,status} and derives slots from stats', () => {
    const vm = toPipeline([snapshotEvent(fullSnapshot), statsEvent(fullStats)])
    const byKey = Object.fromEntries(vm.stages.map(s => [s.key, s]))

    // Build (implement) tile: 2/5 worker slots, two chips.
    expect(byKey.implement.label).toBe('Build')
    expect(byKey.implement.slots).toEqual({ used: 2, cap: 5 })
    expect(byKey.implement.count).toBe(2)
    expect(byKey.implement.items).toEqual([
      { id: 201, title: 'Build A', status: 'active' },
      { id: 202, title: 'Build B', status: 'failed' },
    ])

    // Triage carries a chip and its worker cap.
    expect(byKey.triage.slots).toEqual({ used: 0, cap: 2 })
    expect(byKey.triage.items).toEqual([{ id: 101, title: 'Triage me', status: 'queued' }])

    // No-role stages (hitl, merged) have no worker slots.
    expect(byKey.hitl.slots).toBeNull()
    expect(byKey.merged.slots).toBeNull()
    expect(byKey.merged.items).toEqual([{ id: 501, title: 'Done', status: 'done' }])
  })

  it('derives attention (hitl depth + failed count) per stage', () => {
    const vm = toPipeline([snapshotEvent(fullSnapshot), statsEvent(fullStats)])
    const byKey = Object.fromEntries(vm.stages.map(s => [s.key, s]))

    // A failed Build item raises the failed badge on that stage only.
    expect(byKey.implement.attention).toEqual({ hitl: 0, failed: 1 })
    // The HITL tile's attention badge equals the HITL queue depth (4).
    expect(byKey.hitl.attention.hitl).toBe(4)
    expect(byKey.hitl.count).toBe(4)
    // Clean stages carry no attention.
    expect(byKey.triage.attention).toEqual({ hitl: 0, failed: 0 })
  })

  it('derives counts/slots/attention from a stats+queue fixture with no snapshot', () => {
    // Stats-only: no per-stage issue lists, so counts fall back to stats depth.
    const vm = toPipeline([statsEvent(fullStats)])
    const byKey = Object.fromEntries(vm.stages.map(s => [s.key, s]))

    expect(byKey.triage.count).toBe(1) // queued 1 + active 0
    expect(byKey.implement.count).toBe(1) // queued 0 + active 1
    expect(byKey.implement.slots).toEqual({ used: 2, cap: 5 })
    expect(byKey.hitl.count).toBe(4) // queued 4 (hitl depth)
    expect(byKey.hitl.attention.hitl).toBe(4)
    expect(byKey.merged.count).toBe(9) // completed_session
    // No snapshot → no chips and no failed items.
    expect(byKey.implement.items).toEqual([])
    expect(byKey.implement.attention).toEqual({ hitl: 0, failed: 0 })
  })

  it('accepts a plain {stages, stats} snapshot object as well as an event array', () => {
    const vm = toPipeline({ stages: fullSnapshot, stats: { stages: fullStats } })
    const byKey = Object.fromEntries(vm.stages.map(s => [s.key, s]))
    expect(byKey.implement.slots).toEqual({ used: 2, cap: 5 })
    expect(byKey.hitl.attention.hitl).toBe(4)
  })

  it('is pure — identical input yields deeply-equal output', () => {
    const events = [snapshotEvent(fullSnapshot), statsEvent(fullStats)]
    expect(toPipeline(events)).toEqual(toPipeline(events))
  })

  it('returns empty stages (no throw) for an empty stream', () => {
    const vm = toPipeline([])
    for (const stage of vm.stages) {
      expect(stage.items).toEqual([])
      expect(stage.count).toBe(0)
      expect(stage.attention).toEqual({ hitl: 0, failed: 0 })
    }
  })
})

describe('activeWorkflowItems', () => {
  it('spans triage → plan → build → review, not just Build (#13)', () => {
    expect(WORKFLOW_STAGE_KEYS).toEqual(['triage', 'plan', 'implement', 'review'])

    const vm = toPipeline([snapshotEvent(fullSnapshot), statsEvent(fullStats)])
    const items = activeWorkflowItems(vm)

    // Every workflow-stage item surfaces, in lifecycle order, tagged by stage.
    expect(items.map(i => i.id)).toEqual([101, 201, 202, 301])
    expect(items.map(i => i.stage)).toEqual(['triage', 'implement', 'implement', 'review'])
    expect(items.map(i => i.stageLabel)).toEqual(['Triage', 'Build', 'Build', 'Review'])
  })

  it('excludes the terminal hitl and merged stages', () => {
    const vm = toPipeline([snapshotEvent(fullSnapshot), statsEvent(fullStats)])
    const ids = activeWorkflowItems(vm).map(i => i.id)
    // 401-404 are hitl, 501 is merged — none appear.
    expect(ids).not.toContain(401)
    expect(ids).not.toContain(501)
  })

  it('is tolerant of a missing / empty pipeline', () => {
    expect(activeWorkflowItems(null)).toEqual([])
    expect(activeWorkflowItems({})).toEqual([])
    expect(activeWorkflowItems({ stages: [] })).toEqual([])
  })
})

describe('stageDurationLabel', () => {
  const start = Date.parse('2026-07-27T10:00:00Z')

  it('formats sub-minute elapsed as seconds', () => {
    expect(stageDurationLabel('2026-07-27T10:00:00Z', start + 45_000)).toBe('45s')
  })

  it('formats sub-hour elapsed as whole minutes', () => {
    expect(stageDurationLabel('2026-07-27T10:00:00Z', start + 12 * 60_000)).toBe('12m')
  })

  it('formats multi-hour elapsed as `h`+zero-padded minutes', () => {
    expect(stageDurationLabel('2026-07-27T10:00:00Z', start + 64 * 60_000)).toBe('1h04m')
    expect(stageDurationLabel('2026-07-27T10:00:00Z', start + 60 * 60_000)).toBe('1h00m')
  })

  it('accepts epoch-ms as well as ISO for the start', () => {
    expect(stageDurationLabel(start, start + 90_000)).toBe('1m')
  })

  it('is deterministic — never reads the wall clock (now is injected)', () => {
    const now = start + 5 * 60_000
    expect(stageDurationLabel('2026-07-27T10:00:00Z', now)).toBe('5m')
    expect(stageDurationLabel('2026-07-27T10:00:00Z', now)).toBe('5m')
  })

  it('returns "" for a missing, unparseable, or future start', () => {
    expect(stageDurationLabel(null, start)).toBe('')
    expect(stageDurationLabel(undefined, start)).toBe('')
    expect(stageDurationLabel('not-a-date', start)).toBe('')
    expect(stageDurationLabel('2026-07-27T10:05:00Z', start)).toBe('') // start after now
  })
})

describe('stageColorKey', () => {
  it('maps each operator stage to its classic-palette token colour key (#10)', () => {
    expect(stageColorKey('triage')).toBe('yellow')
    expect(stageColorKey('plan')).toBe('purple')
    expect(stageColorKey('implement')).toBe('accent')
    expect(stageColorKey('review')).toBe('orange')
    expect(stageColorKey('hitl')).toBe('red')
    expect(stageColorKey('merged')).toBe('green')
  })

  it('never drifts from constants.PIPELINE_STAGES', () => {
    // The colour key is the `x` in each classic stage's `var(--x)` reference.
    for (const s of PIPELINE_STAGES) {
      const raw = /var\(--([a-z0-9-]+)\)/.exec(s.color)[1]
      const expected = raw.replace(/-([a-z])/g, (_, c) => c.toUpperCase())
      expect(stageColorKey(s.key)).toBe(expected)
    }
  })

  it('returns null for an unknown stage key', () => {
    expect(stageColorKey('nope')).toBeNull()
    expect(stageColorKey(undefined)).toBeNull()
  })
})

describe('stageTransitionTs', () => {
  const rowAt = (ts, source) => ({ ts, meta: { source } })

  it('returns the ts at which the current stage began (last source change)', () => {
    const rows = [
      rowAt('2026-07-27T10:00:00Z', 'triage'),
      rowAt('2026-07-27T10:02:00Z', 'triage'),
      rowAt('2026-07-27T10:10:00Z', 'reviewer'),
      rowAt('2026-07-27T10:11:00Z', 'reviewer'),
    ]
    expect(stageTransitionTs(rows)).toBe('2026-07-27T10:10:00Z')
  })

  it('returns null when every row shares one source (no observed transition)', () => {
    const rows = [
      rowAt('2026-07-27T10:00:00Z', 'implementer'),
      rowAt('2026-07-27T10:05:00Z', 'implementer'),
    ]
    expect(stageTransitionTs(rows)).toBeNull()
  })

  it('treats a missing source as its own stage value', () => {
    const rows = [
      rowAt('2026-07-27T10:00:00Z', 'triage'),
      rowAt('2026-07-27T10:05:00Z', undefined),
    ]
    expect(stageTransitionTs(rows)).toBe('2026-07-27T10:05:00Z')
  })

  it('is tolerant of empty / non-array input', () => {
    expect(stageTransitionTs([])).toBeNull()
    expect(stageTransitionTs(null)).toBeNull()
    expect(stageTransitionTs(undefined)).toBeNull()
  })
})

import { describe, it, expect } from 'vitest'
import {
  WORKER_STATE,
  AGENT_STATE_ORDER,
  AGENT_STATE_META,
  CLAIM_LABEL,
  DEFAULT_STALL_MS,
  isActiveClaim,
  splitPhaseItems,
  classifyAgentState,
  deriveAgentStates,
} from '../agents'

// The shared per-worker-state derivation (#10943 + #10944). It is a pure,
// deterministic transform: the clock is always injected, so stall detection
// never reads the wall clock.

const NOW = Date.parse('2026-08-01T12:00:00Z')
const minsAgo = (m) => new Date(NOW - m * 60_000).toISOString()

// ── #10943: ACTIVE / QUEUED bucketing ───────────────────────────────────────

describe('isActiveClaim', () => {
  it('treats only the normalized "active" status as a live worker claim', () => {
    expect(isActiveClaim('active')).toBe(true)
    expect(isActiveClaim('queued')).toBe(false)
    expect(isActiveClaim('failed')).toBe(false)
    expect(isActiveClaim(undefined)).toBe(false)
  })
})

describe('splitPhaseItems', () => {
  it('splits BUILD 15 (1 active / 14 queued) into exactly 1 ACTIVE and 14 QUEUED', () => {
    // The acceptance case: 15 build items, one worker on one of them.
    const items = [
      { id: 200, title: 'building', status: 'active' },
      ...Array.from({ length: 14 }, (_, i) => ({ id: 300 + i, title: `q${i}`, status: 'queued' })),
    ]
    const { active, queued } = splitPhaseItems(items)
    expect(active).toHaveLength(1)
    expect(active[0].id).toBe(200)
    expect(queued).toHaveLength(14)
  })

  it('preserves the backend queue order for the QUEUED bucket', () => {
    const items = [
      { id: 9, status: 'queued' },
      { id: 3, status: 'active' },
      { id: 7, status: 'queued' },
    ]
    const { active, queued } = splitPhaseItems(items)
    expect(active.map(i => i.id)).toEqual([3])
    expect(queued.map(i => i.id)).toEqual([9, 7])
  })

  it('is tolerant of a missing / non-array items input', () => {
    expect(splitPhaseItems(undefined)).toEqual({ active: [], queued: [] })
    expect(splitPhaseItems(null)).toEqual({ active: [], queued: [] })
  })
})

// ── #10944: 5-state classification ──────────────────────────────────────────

describe('classifyAgentState — each of the 5 states', () => {
  it('RUNNING when live with a fresh heartbeat', () => {
    expect(classifyAgentState({ status: 'running', lastActivityTs: minsAgo(1), now: NOW }))
      .toBe(WORKER_STATE.RUNNING)
  })

  it('STALLED when no output for longer than the threshold (silent-failure catch)', () => {
    expect(classifyAgentState({ status: 'running', lastActivityTs: minsAgo(30), now: NOW }))
      .toBe(WORKER_STATE.STALLED)
  })

  it('does NOT stall when the heartbeat is missing (absence never fabricates an alarm)', () => {
    expect(classifyAgentState({ status: 'running', lastActivityTs: null, now: NOW }))
      .toBe(WORKER_STATE.RUNNING)
  })

  it('WAITING-CI for a ci_wait worker, and it outranks a stall (CI wait is not a stall)', () => {
    expect(classifyAgentState({ status: 'ci_wait', lastActivityTs: minsAgo(30), now: NOW }))
      .toBe(WORKER_STATE.WAITING_CI)
  })

  it('BLOCKED for an escalated or failed worker, outranking a stall', () => {
    expect(classifyAgentState({ status: 'escalated', lastActivityTs: minsAgo(30), now: NOW }))
      .toBe(WORKER_STATE.BLOCKED)
    expect(classifyAgentState({ status: 'failed', lastActivityTs: minsAgo(1), now: NOW }))
      .toBe(WORKER_STATE.BLOCKED)
  })

  it('PAUSED (fleet-wide) outranks everything and suppresses a false stall', () => {
    expect(classifyAgentState({ status: 'running', factoryPaused: true, lastActivityTs: minsAgo(90), now: NOW }))
      .toBe(WORKER_STATE.PAUSED)
    expect(classifyAgentState({ status: 'escalated', factoryPaused: true, lastActivityTs: minsAgo(1), now: NOW }))
      .toBe(WORKER_STATE.PAUSED)
  })

  it('honours a custom stall threshold', () => {
    expect(classifyAgentState({ status: 'running', lastActivityTs: minsAgo(5), now: NOW, stallThresholdMs: 60_000 }))
      .toBe(WORKER_STATE.STALLED)
    expect(classifyAgentState({ status: 'running', lastActivityTs: minsAgo(5), now: NOW, stallThresholdMs: 10 * 60_000 }))
      .toBe(WORKER_STATE.RUNNING)
  })
})

describe('metadata contract', () => {
  it('exposes ordered filter states with token tones (no hardcoded colour)', () => {
    expect(AGENT_STATE_ORDER).toEqual([
      WORKER_STATE.RUNNING, WORKER_STATE.PAUSED, WORKER_STATE.STALLED,
      WORKER_STATE.WAITING_CI, WORKER_STATE.BLOCKED,
    ])
    for (const state of AGENT_STATE_ORDER) {
      const meta = AGENT_STATE_META[state]
      expect(meta.label).toBeTruthy()
      expect(['success', 'warning', 'danger', 'info', 'accent', 'neutral']).toContain(meta.tone)
    }
    // Only RUNNING carries the live pulse.
    expect(AGENT_STATE_META[WORKER_STATE.RUNNING].pulse).toBe(true)
    expect(AGENT_STATE_META[WORKER_STATE.STALLED].pulse).toBe(false)
  })

  it('uses the canonical #10168 claim label and an 8-minute default stall window', () => {
    expect(CLAIM_LABEL).toBe('hydraflow-in-progress')
    expect(DEFAULT_STALL_MS).toBe(8 * 60 * 1000)
  })
})

// ── #10944: deriveAgentStates (integration of the sources) ───────────────────

function pipelineWith({ triage = [], plan = [], implement = [], review = [] } = {}) {
  const stage = (key, label, items) => ({ key, label, count: items.length, slots: null, items, attention: { hitl: 0, failed: 0 } })
  return {
    stages: [
      stage('triage', 'Triage', triage),
      stage('plan', 'Plan', plan),
      stage('implement', 'Build', implement),
      stage('review', 'Review', review),
      stage('hitl', 'HITL', []),
      stage('merged', 'Merged', []),
    ],
  }
}

describe('deriveAgentStates', () => {
  it('surfaces a pipeline-active item with no worker record as a RUNNING agent', () => {
    const pipeline = pipelineWith({ implement: [{ id: 42, title: 'Fix login', status: 'active' }] })
    const events = [{ type: 'transcript_line', timestamp: minsAgo(1), data: { issue: 42, line: 'go' } }]
    const agents = deriveAgentStates({ pipeline, events, now: NOW })
    expect(agents).toHaveLength(1)
    expect(agents[0]).toMatchObject({ id: 42, phase: 'implement', state: WORKER_STATE.RUNNING, claimLabel: CLAIM_LABEL })
  })

  it('excludes queued pipeline items entirely (no "No transcript yet" cards)', () => {
    const pipeline = pipelineWith({ implement: [{ id: 7, status: 'queued' }, { id: 8, status: 'active' }] })
    const agents = deriveAgentStates({ pipeline, events: [], now: NOW })
    expect(agents.map(a => a.id)).toEqual([8])
  })

  it('classifies granular worker statuses (running / ci_wait / escalated) from the workers slice', () => {
    const workers = {
      '101': { role: 'implementer', status: 'running', worker: 1, title: 'Issue #101', lastActivity: { timestamp: minsAgo(1) } },
      'review-202': { role: 'reviewer', status: 'ci_wait', worker: 2, pr: 202, title: 'PR #202' },
      'triage-303': { role: 'triage', status: 'escalated', worker: 3, title: 'Triage #303' },
    }
    const agents = deriveAgentStates({ workers, now: NOW })
    const byId = Object.fromEntries(agents.map(a => [a.id, a]))
    expect(byId[101].state).toBe(WORKER_STATE.RUNNING)
    expect(byId[101].phase).toBe('implement')
    expect(byId[202].state).toBe(WORKER_STATE.WAITING_CI)
    expect(byId[202].phase).toBe('review')
    expect(byId[303].state).toBe(WORKER_STATE.BLOCKED)
    expect(byId[303].phase).toBe('triage')
  })

  it('flags a worker with a stale heartbeat as STALLED', () => {
    const workers = {
      '55': { role: 'implementer', status: 'running', worker: 1, lastActivity: { timestamp: minsAgo(45) } },
    }
    const [agent] = deriveAgentStates({ workers, now: NOW })
    expect(agent.state).toBe(WORKER_STATE.STALLED)
  })

  it('marks every live agent PAUSED (with reason + resume ETA) when the factory is credit-paused', () => {
    const workers = { '55': { role: 'implementer', status: 'running', worker: 1, lastActivity: { timestamp: minsAgo(1) } } }
    const factory = { state: 'paused', reason: 'credits paused until 2026-08-01T13:00:00Z' }
    const credits = { pausedUntil: '2026-08-01T13:00:00Z', provider: 'anthropic' }
    const [agent] = deriveAgentStates({ workers, factory, credits, now: NOW })
    expect(agent.state).toBe(WORKER_STATE.PAUSED)
    expect(agent.reason).toContain('credits paused')
    expect(agent.resumeEta).toBe('2026-08-01T13:00:00Z')
    expect(agent.provider).toBe('anthropic')
  })

  it('drops non-live workers (queued / done / merged) from the agent view', () => {
    const workers = {
      '1': { role: 'implementer', status: 'queued', worker: 0 },
      '2': { role: 'implementer', status: 'done', worker: 1 },
      '3': { role: 'implementer', status: 'running', worker: 2, lastActivity: { timestamp: minsAgo(1) } },
    }
    const agents = deriveAgentStates({ workers, now: NOW })
    expect(agents.map(a => a.id)).toEqual([3])
  })

  it('does not double-count an issue present in both the workers slice and the pipeline', () => {
    const workers = { '42': { role: 'implementer', status: 'running', worker: 1, lastActivity: { timestamp: minsAgo(1) } } }
    const pipeline = pipelineWith({ implement: [{ id: 42, title: 'Fix login', status: 'active' }] })
    const agents = deriveAgentStates({ workers, pipeline, now: NOW })
    expect(agents).toHaveLength(1)
    expect(agents[0].workerId).toBe(1)
  })

  it('returns an empty list for empty input', () => {
    expect(deriveAgentStates({ now: NOW })).toEqual([])
    expect(deriveAgentStates()).toEqual([])
  })
})

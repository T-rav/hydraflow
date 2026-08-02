import { describe, it, expect } from 'vitest'
import { toSupervisorThread, EMPTY_SUPERVISOR_VM } from '../supervisorThread'

// toSupervisorThread (#10733, ADR-0124) turns the `/supervisor/thread` payload
// (the Tier-2 goal-supervisor's append-only observation thread, newest LAST as
// stored) into a stable panel VM: newest first, a derived top-level verdict, and
// each observation's nudges/escalations/deferred bucketed with counts. A missing
// / malformed payload yields the EMPTY VM, never throws.

const obs = (over = {}) => ({
  ts: '2026-08-02T17:31:46Z',
  snapshot: {
    healthy: false,
    stalled_loops: [],
    error_loops: ['flake_tracker'],
    credit_failover_active: false,
    credit_probe_overdue: false,
    boot_sha_stale: false,
    commits_behind: 0,
    event_loop_stalled: false,
    vitals_verdict: 'green',
  },
  assessment: 'flake_tracker is erroring',
  insights: ['verified: flake_tracker cleared last tick'],
  nudges_taken: ['restart_stalled_loop [flake_tracker] — wedged heartbeat'],
  escalations: [],
  deferred: ['rerun_flaky_check — CI auto-retry'],
  ...over,
})

describe('toSupervisorThread — normalization + bucketing', () => {
  it('returns the EMPTY VM for a missing / malformed payload', () => {
    expect(toSupervisorThread(null)).toBe(EMPTY_SUPERVISOR_VM)
    expect(toSupervisorThread(undefined)).toBe(EMPTY_SUPERVISOR_VM)
    expect(toSupervisorThread(42)).toBe(EMPTY_SUPERVISOR_VM)
    expect(toSupervisorThread({})).toBe(EMPTY_SUPERVISOR_VM)
    expect(toSupervisorThread({ observations: [] })).toBe(EMPTY_SUPERVISOR_VM)
  })

  it('accepts both the {observations} envelope and a bare array', () => {
    expect(toSupervisorThread({ observations: [obs()] }).count).toBe(1)
    expect(toSupervisorThread([obs()]).count).toBe(1)
  })

  it('orders observations newest first (thread stores newest last)', () => {
    const vm = toSupervisorThread({
      observations: [
        obs({ ts: '2026-08-02T10:00:00Z', assessment: 'oldest' }),
        obs({ ts: '2026-08-02T12:00:00Z', assessment: 'middle' }),
        obs({ ts: '2026-08-02T14:00:00Z', assessment: 'newest' }),
      ],
    })
    expect(vm.observations.map(o => o.assessment)).toEqual(['newest', 'middle', 'oldest'])
    expect(vm.latest.assessment).toBe('newest')
  })

  it('buckets each observation into nudges / escalations / deferred with counts', () => {
    const vm = toSupervisorThread({ observations: [obs()] })
    const o = vm.observations[0]
    expect(o.nudges).toEqual(['restart_stalled_loop [flake_tracker] — wedged heartbeat'])
    expect(o.escalations).toEqual([])
    expect(o.deferred).toEqual(['rerun_flaky_check — CI auto-retry'])
    expect(o.insights).toHaveLength(1)
    expect(o.counts).toEqual({ insights: 1, nudges: 1, escalations: 0, deferred: 1 })
  })

  it('normalizes the snapshot into a stable camelCase shape', () => {
    const vm = toSupervisorThread({ observations: [obs()] })
    expect(vm.observations[0].snapshot).toEqual({
      healthy: false,
      stalledLoops: [],
      errorLoops: ['flake_tracker'],
      creditFailoverActive: false,
      creditProbeOverdue: false,
      bootShaStale: false,
      commitsBehind: 0,
      eventLoopStalled: false,
      vitalsVerdict: 'green',
    })
  })

  it('flags an observation with escalations via hasEscalations', () => {
    const vm = toSupervisorThread({
      observations: [obs({ escalations: ['force_push [main] — RC wedged'] })],
    })
    expect(vm.observations[0].hasEscalations).toBe(true)
    expect(vm.observations[0].counts.escalations).toBe(1)
  })
})

describe('toSupervisorThread — verdict derivation (from the newest observation)', () => {
  it('is "empty" with no observations', () => {
    expect(toSupervisorThread({ observations: [] }).verdict).toBe('empty')
    expect(EMPTY_SUPERVISOR_VM.verdict).toBe('empty')
  })

  it('is "escalations" with a pending-escalation count when the latest tick escalated', () => {
    const vm = toSupervisorThread({
      observations: [obs({ escalations: ['force_push [main] — RC wedged', 'delete_branch — orphan'] })],
    })
    expect(vm.verdict).toBe('escalations')
    expect(vm.escalationCount).toBe(2)
    expect(vm.verdictLabel).toBe('2 escalations pending')
  })

  it('singularizes the escalation label for a single escalation', () => {
    const vm = toSupervisorThread({ observations: [obs({ escalations: ['force_push [main]'] })] })
    expect(vm.verdictLabel).toBe('1 escalation pending')
  })

  it('is "degraded" when the latest snapshot is unhealthy with no escalations', () => {
    const vm = toSupervisorThread({ observations: [obs({ escalations: [], snapshot: { healthy: false } })] })
    expect(vm.verdict).toBe('degraded')
    expect(vm.verdictLabel).toBe('degraded')
  })

  it('is "healthy" when the latest snapshot is healthy with no escalations', () => {
    const vm = toSupervisorThread({ observations: [obs({ escalations: [], snapshot: { healthy: true } })] })
    expect(vm.verdict).toBe('healthy')
    expect(vm.verdictLabel).toBe('healthy')
  })

  it('derives the verdict from the NEWEST observation, not an older escalating one', () => {
    const vm = toSupervisorThread({
      observations: [
        obs({ ts: '2026-08-02T10:00:00Z', escalations: ['force_push [main]'] }), // older, escalated
        obs({ ts: '2026-08-02T14:00:00Z', escalations: [], snapshot: { healthy: true } }), // newest, clear
      ],
    })
    expect(vm.verdict).toBe('healthy')
    expect(vm.escalationCount).toBe(0)
  })
})

describe('toSupervisorThread — escalation acks (honest thread, rule 6)', () => {
  it('surfaces acked / unacked escalations from the backend acked_escalations JOIN', () => {
    const vm = toSupervisorThread({
      observations: [obs({
        escalations: ['force_push [main]', 'delete_branch — orphan'],
        acked_escalations: ['force_push [main]'],
      })],
    })
    const o = vm.observations[0]
    expect(o.ackedEscalations).toEqual(['force_push [main]'])
    expect(o.unackedEscalations).toEqual(['delete_branch — orphan'])
    expect(o.hasEscalations).toBe(true) // one still wants a human
    expect(o.counts.escalations).toBe(2) // count stays the raw bucket size
  })

  it('drops a FULLY-acked observation out of the verdict / escalationCount', () => {
    const vm = toSupervisorThread({
      observations: [obs({
        escalations: ['force_push [main]'],
        acked_escalations: ['force_push [main]'],
        snapshot: { healthy: false },
      })],
    })
    expect(vm.verdict).toBe('degraded') // a handled escalation stops nagging
    expect(vm.escalationCount).toBe(0)
    expect(vm.observations[0].hasEscalations).toBe(false)
  })

  it('still escalates the verdict for a PARTIALLY-acked observation', () => {
    const vm = toSupervisorThread({
      observations: [obs({ escalations: ['a', 'b'], acked_escalations: ['a'] })],
    })
    expect(vm.verdict).toBe('escalations')
    expect(vm.escalationCount).toBe(1)
    expect(vm.verdictLabel).toBe('1 escalation pending')
  })

  it('ignores a stray ack that names no real escalation of the observation', () => {
    const vm = toSupervisorThread({
      observations: [obs({ escalations: ['a'], acked_escalations: ['ghost'] })],
    })
    expect(vm.observations[0].ackedEscalations).toEqual([])
    expect(vm.observations[0].unackedEscalations).toEqual(['a'])
  })
})

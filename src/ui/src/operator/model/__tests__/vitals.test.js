import { describe, it, expect } from 'vitest'
import { toVitals, factoryStartMs, factoryUptimeLabel } from '../vitals'

// Event shapes match the HydraFlowContext reducer:
//   orchestrator_status → data { status, credits_paused_until, credits_paused_provider }
//   background_worker_status → data { worker, status: 'ok'|'error', last_run, details }
// The main↔staging sync signal is REST-sourced (/api/staging-promotion/status),
// passed via the optional `extras.stagingPromotion` argument.

const orch = (data, id = 1) => ({
  type: 'orchestrator_status',
  timestamp: '2026-07-26T12:00:00Z',
  id,
  data,
})

const bg = (worker, status, id) => ({
  type: 'background_worker_status',
  timestamp: `2026-07-26T12:00:0${id}Z`,
  id,
  data: { worker, status, last_run: `2026-07-26T12:00:0${id}Z`, details: {} },
})

describe('toVitals', () => {
  it('reports loops healthy as ok/total from the latest status per worker', () => {
    const events = [
      // newest first
      bg('loop_c', 'error', 5),
      bg('loop_b', 'ok', 4),
      bg('loop_a', 'ok', 3),
      bg('loop_c', 'ok', 2), // stale — superseded by id 5
    ]
    const vm = toVitals(events)
    expect(vm.loopsHealthy).toEqual({ ok: 2, total: 3 })
  })

  it('counts restart/error cycles per loop (a restarted loop shows up)', () => {
    const events = [
      bg('loop_c', 'error', 5),
      bg('loop_a', 'ok', 4),
      bg('loop_c', 'error', 3), // crashed earlier too → count 2
      bg('loop_b', 'ok', 2),
    ]
    const vm = toVitals(events)
    expect(vm.restarts).toEqual([{ loop: 'loop_c', count: 2 }])
  })

  it('marks the factory paused with a credit reason when credits are paused', () => {
    const events = [
      orch({
        status: 'running',
        credits_paused_until: '2026-07-29T00:00:00Z',
        credits_paused_provider: 'anthropic',
      }),
    ]
    const vm = toVitals(events)
    expect(vm.factory.state).toBe('paused')
    expect(vm.factory.reason).toContain('credits')
    expect(vm.credits).toEqual({
      paused: true,
      pausedUntil: '2026-07-29T00:00:00Z',
      provider: 'anthropic',
    })
  })

  it('reflects a plain running factory with no credit pause', () => {
    const vm = toVitals([orch({ status: 'running' })])
    expect(vm.factory.state).toBe('running')
    expect(vm.factory.reason).toBeNull()
    expect(vm.credits.paused).toBe(false)
  })

  it('derives main↔staging sync state from the staging-promotion status', () => {
    const behind = toVitals([], {
      stagingPromotion: {
        open_promotion_pr: { number: 555, branch: 'rc/2026-07-26-1200', url: 'https://x/555' },
        cadence_hours: 4,
        recent_promoted: 3,
        recent_failed: 1,
      },
    })
    expect(behind.mainStagingSync).toEqual({ state: 'behind', openPrNumber: 555 })

    const inSync = toVitals([], { stagingPromotion: { open_promotion_pr: null } })
    expect(inSync.mainStagingSync.state).toBe('in_sync')

    const unknown = toVitals([])
    expect(unknown.mainStagingSync.state).toBe('unknown')
  })

  it('is pure — identical input yields deeply-equal output', () => {
    const events = [bg('loop_a', 'ok', 1), orch({ status: 'running' }, 2)]
    expect(toVitals(events)).toEqual(toVitals(events))
  })
})

// Factory runtime / uptime (#12) — derived from the socket's best start signal,
// measured against an injected `now` (never the wall clock).
describe('factoryStartMs', () => {
  it('prefers the current session\'s started_at', () => {
    const socket = {
      currentSessionId: 'acme-20260727T100000',
      sessions: [
        { id: 'old', status: 'completed', started_at: '2026-07-26T00:00:00Z' },
        { id: 'acme-20260727T100000', status: 'active', started_at: '2026-07-27T10:00:00Z' },
      ],
    }
    expect(factoryStartMs(socket)).toBe(Date.parse('2026-07-27T10:00:00Z'))
  })

  it('falls back to the newest active session when no current id is set', () => {
    const socket = {
      sessions: [{ id: 's1', status: 'active', started_at: '2026-07-27T09:30:00Z' }],
    }
    expect(factoryStartMs(socket)).toBe(Date.parse('2026-07-27T09:30:00Z'))
  })

  it('parses a session id that encodes its start when no started_at exists', () => {
    const socket = { currentSessionId: 'acme-web-20260727T221406', sessions: [] }
    expect(factoryStartMs(socket)).toBe(Date.parse('2026-07-27T22:14:06Z'))
  })

  it('returns null when no start signal is available', () => {
    expect(factoryStartMs({})).toBeNull()
    expect(factoryStartMs()).toBeNull()
    expect(factoryStartMs({ sessions: [], currentSessionId: null })).toBeNull()
  })
})

describe('factoryUptimeLabel', () => {
  it('formats the elapsed runtime compactly against an injected now', () => {
    const socket = {
      currentSessionId: 'a-20260727T100000',
      sessions: [{ id: 'a-20260727T100000', status: 'active', started_at: '2026-07-27T10:00:00Z' }],
    }
    expect(factoryUptimeLabel(socket, Date.parse('2026-07-27T12:14:00Z'))).toBe('2h14m')
  })

  it('returns "" when no start signal exists (so the header renders nothing)', () => {
    expect(factoryUptimeLabel({}, Date.now())).toBe('')
  })

  it('is deterministic — never reads the wall clock', () => {
    const socket = { currentSessionId: 'a-20260727T100000', sessions: [] }
    const now = Date.parse('2026-07-27T10:45:00Z')
    expect(factoryUptimeLabel(socket, now)).toBe('45m')
    expect(factoryUptimeLabel(socket, now)).toBe('45m')
  })
})

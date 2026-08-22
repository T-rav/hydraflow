/**
 * Pure gateway routing view models (#11534, ADR-0138).
 *
 * The reducers must stay HONEST about a missing source: an unreachable gateway
 * is not an empty account list, and an account with no evidence is not healthy.
 */

import { describe, it, expect } from 'vitest'
import {
  EMPTY_GATEWAY_ACCOUNTS_VM,
  EMPTY_GATEWAY_LIVE_VM,
  formatAge,
  formatCost,
  formatLatency,
  healthTone,
  statusTone,
  toGatewayAccounts,
  toGatewayLiveRoutes,
} from '../gatewayRouting'

const ACCOUNT = {
  account_id: 'legacy-zai-harness',
  display_name: 'z.ai harness (legacy upstream)',
  provider_binding: 'zai-harness',
  base_origin: 'https://zai.test',
  auth_style: 'bearer',
  credential_env: 'GATEWAY_ZAI_HARNESS_API_KEY',
  configured: true,
  administrative_state: 'enabled',
  leased: true,
  lease_count: 2,
  in_flight: true,
  in_flight_count: 1,
  observed: true,
  observed_request_count: 5,
  observed_error_count: 0,
  last_observed_at: '2026-08-22T12:00:00Z',
  health: 'healthy',
  health_reason: null,
}

function accountsEnvelope(overrides = {}) {
  return {
    available: true,
    source_state: 'available',
    data: {
      as_of: '2026-08-22T12:00:00Z',
      evidence_since: '2026-08-22T11:00:00Z',
      window_seconds: 900,
      summary: { configured: 1, enabled: 1, leased: 1, in_flight: 1 },
      accounts: [{ ...ACCOUNT, ...overrides }],
    },
  }
}

function activeEnvelope() {
  return {
    available: true,
    source_state: 'available',
    data: {
      evidence_since: '2026-08-22T11:00:00Z',
      leases: [
        {
          key_id: 'key-1',
          account_id: 'legacy-zai-harness',
          provider_binding: 'zai-harness',
          repo_slug: 'acme/hydraflow',
          principal_id: 'implementer',
          worker_role: 'implementer',
          issue_number: 11534,
          age_seconds: 95,
          expires_at: '2026-08-22T12:05:00Z',
        },
      ],
      in_flight: [
        {
          request_id: 'req-live',
          account_id: 'legacy-zai-harness',
          provider_binding: 'zai-harness',
          repo_slug: 'acme/hydraflow',
          principal_id: 'adr_review',
          worker_role: null,
          path: '/v1/messages',
          age_seconds: 4,
        },
      ],
    },
  }
}

function recentEnvelope(overrides = {}) {
  return {
    available: true,
    source_state: 'available',
    data: {
      evidence_since: '2026-08-22T11:00:00Z',
      capacity: 200,
      truncated: false,
      routes: [
        {
          request_id: 'req-done',
          account_id: 'legacy-zai-harness',
          provider_binding: 'zai-harness',
          repo_slug: 'acme/hydraflow',
          principal_id: 'implementer',
          worker_role: 'implementer',
          model_requested: 'glm-5.2',
          model_served: 'glm-5.3',
          status: 'completed',
          status_code: 200,
          latency_ms: 1500,
          cost_usd: 0.1234,
          cost_unknown: false,
          started_at: '2026-08-22T11:59:00Z',
        },
      ],
      ...overrides,
    },
  }
}

describe('toGatewayAccounts', () => {
  it('projects an account row from the envelope', () => {
    expect(toGatewayAccounts(accountsEnvelope()).accounts[0].accountId).toBe(
      'legacy-zai-harness',
    )
  })

  it('keeps the summary counters', () => {
    expect(toGatewayAccounts(accountsEnvelope()).summary.leased).toBe(1)
  })

  it('publishes the window the payload was computed under', () => {
    expect(toGatewayAccounts(accountsEnvelope()).windowSeconds).toBe(900)
  })

  it('returns the empty VM for an unavailable source', () => {
    const vm = toGatewayAccounts({ available: false, source_state: 'unreachable', data: null })
    expect(vm.accounts).toEqual([])
  })

  it('carries the unavailable reason so the panel can explain itself', () => {
    const vm = toGatewayAccounts({ available: false, source_state: 'unreachable', data: null })
    expect(vm.sourceState).toBe('unreachable')
  })

  it('never reports an unavailable source as available', () => {
    const vm = toGatewayAccounts({ available: false, source_state: 'unreachable', data: null })
    expect(vm.available).toBe(false)
  })

  it('returns the frozen empty VM for a malformed payload', () => {
    expect(toGatewayAccounts(null)).toEqual(EMPTY_GATEWAY_ACCOUNTS_VM)
  })

  it('coerces a malformed count to zero rather than NaN', () => {
    const vm = toGatewayAccounts(accountsEnvelope({ lease_count: 'many' }))
    expect(vm.accounts[0].leaseCount).toBe(0)
  })

  it('keeps configured and health as separate facts', () => {
    const vm = toGatewayAccounts(accountsEnvelope({ health: 'unverified' }))
    expect([vm.accounts[0].configured, vm.accounts[0].health]).toEqual([true, 'unverified'])
  })
})

describe('healthTone', () => {
  it('never renders unverified as a success tone', () => {
    expect(healthTone('unverified')).toBe('neutral')
  })

  it('renders healthy as success', () => {
    expect(healthTone('healthy')).toBe('success')
  })

  it('renders degraded as danger', () => {
    expect(healthTone('degraded')).toBe('danger')
  })
})

describe('statusTone', () => {
  it('does not treat a client abort as an upstream failure', () => {
    expect(statusTone('client-aborted')).toBe('warning')
  })

  it('treats an upstream error as danger', () => {
    expect(statusTone('upstream-error')).toBe('danger')
  })
})

describe('toGatewayLiveRoutes', () => {
  it('projects a lease row', () => {
    const vm = toGatewayLiveRoutes(activeEnvelope(), recentEnvelope())
    expect(vm.leases[0].keyId).toBe('key-1')
  })

  it('labels a lease age in minutes past a minute', () => {
    const vm = toGatewayLiveRoutes(activeEnvelope(), recentEnvelope())
    expect(vm.leases[0].ageLabel).toBe('1m')
  })

  it('projects an in-flight row', () => {
    const vm = toGatewayLiveRoutes(activeEnvelope(), recentEnvelope())
    expect(vm.inFlight[0].requestId).toBe('req-live')
  })

  it('falls back to the principal id when no canonical role matched', () => {
    const vm = toGatewayLiveRoutes(activeEnvelope(), recentEnvelope())
    expect(vm.inFlight[0].role).toBe('adr_review')
  })

  it('keeps the canonical role null when the principal is not a worker role', () => {
    const vm = toGatewayLiveRoutes(activeEnvelope(), recentEnvelope())
    expect(vm.inFlight[0].canonicalRole).toBeNull()
  })

  it('projects requested and served model separately', () => {
    const vm = toGatewayLiveRoutes(activeEnvelope(), recentEnvelope())
    expect([vm.recent[0].modelRequested, vm.recent[0].modelServed]).toEqual([
      'glm-5.2',
      'glm-5.3',
    ])
  })

  it('surfaces a truncated ring so the view cannot claim completeness', () => {
    const vm = toGatewayLiveRoutes(activeEnvelope(), recentEnvelope({ truncated: true }))
    expect(vm.truncated).toBe(true)
  })

  it('degrades the whole view when only the recent read failed', () => {
    const vm = toGatewayLiveRoutes(activeEnvelope(), {
      available: false,
      source_state: 'unreachable',
      data: null,
    })
    expect(vm.available).toBe(false)
  })

  it('returns the frozen empty VM when both reads failed', () => {
    expect(toGatewayLiveRoutes(null, null)).toEqual({
      ...EMPTY_GATEWAY_LIVE_VM,
      sourceState: 'not-configured',
    })
  })
})

describe('formatters', () => {
  it('shows sub-minute ages in seconds', () => {
    expect(formatAge(42)).toBe('42s')
  })

  it('shows multi-hour ages in hours and minutes', () => {
    expect(formatAge(3_900)).toBe('1h 5m')
  })

  it('shows sub-second latency in milliseconds', () => {
    expect(formatLatency(250)).toBe('250ms')
  })

  it('shows an unknown cost as a dash rather than a misleading zero', () => {
    expect(formatCost(null, true)).toBe('—')
  })

  it('shows a known cost to four decimals', () => {
    expect(formatCost(0.1234, false)).toBe('$0.1234')
  })
})

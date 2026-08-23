/**
 * Pure gateway routing view models (#11534, ADR-0138).
 *
 * The reducers must stay HONEST about a missing source: an unreachable gateway
 * is not an empty account list, and an account with no evidence is not healthy.
 */

import { describe, it, expect } from 'vitest'
import {
  EMPTY_ACCOUNT_ADMIN_VM,
  EMPTY_GATEWAY_ACCOUNTS_VM,
  EMPTY_GATEWAY_LIVE_VM,
  adminRejectionMessage,
  accountWriteGateMessage,
  circuitTone,
  formatAge,
  formatCapacity,
  formatCost,
  formatLatency,
  healthTone,
  statusTone,
  toAccountAdmin,
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
  observed_aborted_count: 0,
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

  it('carries the aborted count that makes the health verdict reproducible', () => {
    const vm = toGatewayAccounts(accountsEnvelope({ observed_aborted_count: 2 }))
    expect(vm.accounts[0].observedAbortedCount).toBe(2)
  })

  it('surfaces truncated evidence so health cannot read as complete', () => {
    const raw = accountsEnvelope()
    raw.data.evidence_truncated = true
    expect(toGatewayAccounts(raw).evidenceTruncated).toBe(true)
  })
})

describe('toGatewayAccounts pool facts (#11540, ADR-0142)', () => {
  it('keeps an undeclared lease ceiling as null, never zero', () => {
    const vm = toGatewayAccounts(accountsEnvelope({ lease_capacity: null }))
    expect(vm.accounts[0].leaseCapacity).toBeNull()
  })

  it('keeps an undeclared request ceiling as null, never zero', () => {
    const vm = toGatewayAccounts(accountsEnvelope({ request_capacity: null }))
    expect(vm.accounts[0].requestCapacity).toBeNull()
  })

  it('carries a declared lease ceiling as a number', () => {
    const vm = toGatewayAccounts(accountsEnvelope({ lease_capacity: 8 }))
    expect(vm.accounts[0].leaseCapacity).toBe(8)
  })

  it('labels lease capacity as used over limit where a limit exists', () => {
    const vm = toGatewayAccounts(accountsEnvelope({ lease_capacity: 8 }))
    expect(vm.accounts[0].leaseCapacityLabel).toBe('2 / 8')
  })

  it('says "no limit" rather than inventing a ceiling nobody set', () => {
    const vm = toGatewayAccounts(accountsEnvelope({ lease_capacity: null }))
    expect(vm.accounts[0].leaseCapacityLabel).toBe('2 / no limit')
  })

  it('labels request capacity from the in-flight count, not the lease count', () => {
    const vm = toGatewayAccounts(accountsEnvelope({ request_capacity: 4 }))
    expect(vm.accounts[0].requestCapacityLabel).toBe('1 / 4')
  })

  it('defaults a missing circuit state to closed rather than blank', () => {
    expect(toGatewayAccounts(accountsEnvelope()).accounts[0].circuitState).toBe('closed')
  })

  it('carries an open circuit through with its trip condition', () => {
    const vm = toGatewayAccounts(
      accountsEnvelope({
        circuit_state: 'open',
        circuit_last_condition: 'rate_limited',
        circuit_reset_at: '2026-08-22T12:05:00Z',
        circuit_consecutive_failures: 3,
      }),
    )
    expect([
      vm.accounts[0].circuitState,
      vm.accounts[0].circuitLastCondition,
      vm.accounts[0].circuitResetAt,
      vm.accounts[0].circuitConsecutiveFailures,
    ]).toEqual(['open', 'rate_limited', '2026-08-22T12:05:00Z', 3])
  })

  it('coerces a malformed failure count to zero rather than NaN', () => {
    const vm = toGatewayAccounts(
      accountsEnvelope({ circuit_consecutive_failures: 'lots' }),
    )
    expect(vm.accounts[0].circuitConsecutiveFailures).toBe(0)
  })
})

describe('circuitTone', () => {
  it('never renders a closed breaker as a success tone', () => {
    expect(circuitTone('closed')).toBe('neutral')
  })

  it('renders an open breaker as danger', () => {
    expect(circuitTone('open')).toBe('danger')
  })
})

describe('formatCapacity', () => {
  it('states an undeclared ceiling instead of drawing a zero', () => {
    expect(formatCapacity(3, null)).toBe('3 / no limit')
  })

  it('renders used over limit where a limit exists', () => {
    expect(formatCapacity(3, 10)).toBe('3 / 10')
  })

  it('never renders a negative use', () => {
    expect(formatCapacity(-4, 10)).toBe('0 / 10')
  })
})

function adminEnvelope(overrides = {}, dataOverrides = {}) {
  return {
    available: true,
    source_state: 'available',
    write_gate: 'enabled',
    editable: true,
    ...overrides,
    data: {
      schema_version: 1,
      revision: 4,
      chain_verified: true,
      entries: [
        {
          seq: 3,
          recorded_at: '2026-08-22T12:00:00Z',
          mutation: 'set-state',
          account_id: 'legacy-zai-harness',
          actor: 'travis',
          actor_authenticated_by: 'gateway-control-token',
          prior_revision: 3,
          next_revision: 4,
          administrative_state: 'draining',
          revoked_key_count: null,
        },
      ],
      ...dataOverrides,
    },
  }
}

describe('toAccountAdmin', () => {
  it('carries the revision the controls must be composed against', () => {
    expect(toAccountAdmin(adminEnvelope()).revision).toBe(4)
  })

  it('projects the audited history', () => {
    expect(toAccountAdmin(adminEnvelope()).entries[0].actor).toBe('travis')
  })

  it('takes editability from the backend gate rather than inferring it', () => {
    expect(toAccountAdmin(adminEnvelope()).editable).toBe(true)
  })

  it('is not editable when the backend closed the gate', () => {
    const vm = toAccountAdmin(
      adminEnvelope({ editable: false, write_gate: 'dashboard-not-loopback' }),
    )
    expect(vm.editable).toBe(false)
  })

  it('carries the closed gate reason so the panel can explain itself', () => {
    const vm = toAccountAdmin(
      adminEnvelope({ editable: false, write_gate: 'dashboard-not-loopback' }),
    )
    expect(vm.writeGate).toBe('dashboard-not-loopback')
  })

  it('refuses to be editable when the audit chain does not verify', () => {
    const vm = toAccountAdmin(adminEnvelope({}, { chain_verified: false }))
    expect(vm.editable).toBe(false)
  })

  it('renders no history from a chain that does not verify', () => {
    const vm = toAccountAdmin(adminEnvelope({}, { chain_verified: false }))
    expect(vm.entries).toEqual([])
  })

  it('leaves the revision null when the overlay was never read', () => {
    const vm = toAccountAdmin({ available: false, source_state: 'unreachable', data: null })
    expect(vm.revision).toBeNull()
  })

  it('is never editable from an unavailable feed', () => {
    const vm = toAccountAdmin({
      available: false,
      source_state: 'unreachable',
      data: null,
      editable: true,
    })
    expect(vm.editable).toBe(false)
  })

  it('returns the frozen empty VM for a malformed payload', () => {
    expect(toAccountAdmin(null)).toEqual(EMPTY_ACCOUNT_ADMIN_VM)
  })
})

describe('admin messages', () => {
  it('renders a 409 as an instruction to reload, not as an error', () => {
    expect(adminRejectionMessage('stale-revision')).toMatch(/Reload/)
  })

  it('names the account plane rather than the policy plane in the gate reason', () => {
    expect(accountWriteGateMessage('dashboard-not-loopback')).toMatch(
      /Account administration/,
    )
  })

  it('falls back to the raw code rather than swallowing an unknown refusal', () => {
    expect(adminRejectionMessage('some-future-code')).toBe('some-future-code')
  })

  it('returns an empty string when there is no refusal to explain', () => {
    expect(adminRejectionMessage(null)).toBe('')
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

  it('treats an available envelope with no payload as malformed, not available', () => {
    const vm = toGatewayLiveRoutes(
      { available: true, source_state: 'available', data: null },
      { available: true, source_state: 'available', data: { routes: [] } },
    )
    expect(vm.sourceState).toBe('invalid')
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

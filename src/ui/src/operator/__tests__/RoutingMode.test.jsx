/**
 * RoutingMode — the read-only gateway Accounts + Live views (#11534, ADR-0138).
 *
 * Pins the honesty contracts: an unavailable source explains itself rather than
 * rendering an empty list, account facts stay separate, and the recent view
 * shows requested vs served model with its terminal status.
 */

import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import RoutingMode from '../RoutingMode'
import {
  toAccountAdmin,
  toGatewayAccounts,
  toGatewayLiveRoutes,
} from '../model/gatewayRouting'

const ACCOUNTS = toGatewayAccounts({
  available: true,
  source_state: 'available',
  data: {
    as_of: '2026-08-22T12:00:00Z',
    evidence_since: '2026-08-22T11:00:00Z',
    window_seconds: 900,
    summary: { configured: 1, enabled: 1, leased: 1, in_flight: 1 },
    accounts: [
      {
        account_id: 'legacy-anthropic',
        display_name: 'Anthropic (legacy upstream)',
        provider_binding: 'anthropic',
        base_origin: 'https://api.anthropic.test',
        auth_style: 'x-api-key',
        credential_env: 'GATEWAY_ANTHROPIC_API_KEY',
        configured: false,
        administrative_state: 'enabled',
        leased: false,
        lease_count: 0,
        in_flight: false,
        in_flight_count: 0,
        observed: false,
        observed_request_count: 0,
        observed_aborted_count: 0,
        observed_error_count: 0,
        last_observed_at: null,
        health: 'unverified',
        health_reason: 'credential-missing',
      },
      {
        account_id: 'legacy-zai-harness',
        display_name: 'z.ai harness (legacy upstream)',
        provider_binding: 'zai-harness',
        base_origin: 'https://zai.test',
        auth_style: 'bearer',
        credential_env: 'GATEWAY_ZAI_HARNESS_API_KEY',
        configured: true,
        administrative_state: 'enabled',
        lease_capacity: 8,
        request_capacity: 4,
        circuit_state: 'closed',
        circuit_consecutive_failures: 0,
        circuit_reset_at: null,
        circuit_last_condition: null,
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
      },
    ],
  },
})

const ZAI = 'legacy-zai-harness'

function adminVm({ editable = true, revision = 4, chainVerified = true, writeGate = 'enabled' } = {}) {
  return toAccountAdmin({
    available: true,
    source_state: 'available',
    write_gate: writeGate,
    editable,
    data: { revision, chain_verified: chainVerified, entries: [] },
  })
}

/** Render the accounts view with host-admin wired, and enter the operator token. */
function renderAdmin({ admin = adminVm(), onSetAccountState = vi.fn(), onRevokeLeases = vi.fn(), token = 'hfop_secret' } = {}) {
  render(
    <RoutingMode
      accounts={ACCOUNTS}
      admin={admin}
      routingView="accounts"
      onSetAccountState={onSetAccountState}
      onRevokeLeases={onRevokeLeases}
    />,
  )
  if (token && admin.editable) {
    fireEvent.change(screen.getByTestId('routing-admin-token'), {
      target: { value: token },
    })
  }
  return { onSetAccountState, onRevokeLeases }
}

const LIVE = toGatewayLiveRoutes(
  {
    available: true,
    source_state: 'available',
    data: {
      evidence_since: '2026-08-22T11:00:00Z',
      leases: [
        {
          key_id: 'key-1',
          account_id: 'legacy-zai-harness',
          repo_slug: 'acme/hydraflow',
          principal_id: 'implementer',
          worker_role: 'implementer',
          age_seconds: 30,
          expires_at: '2026-08-22T12:05:00Z',
        },
      ],
      in_flight: [
        {
          request_id: 'req-live',
          account_id: 'legacy-zai-harness',
          repo_slug: 'acme/hydraflow',
          principal_id: 'implementer',
          worker_role: 'implementer',
          issue_number: 11534,
          path: '/v1/messages',
          age_seconds: 4,
        },
      ],
    },
  },
  {
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
        },
      ],
    },
  },
)

describe('RoutingMode accounts view', () => {
  it('renders one row per compiled account', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="accounts" />)
    expect(screen.getByTestId('routing-account-legacy-zai-harness')).toBeInTheDocument()
  })

  it('marks an unconfigured account as credential missing', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="accounts" />)
    expect(screen.getByTestId('routing-account-credential-legacy-anthropic')).toHaveTextContent(
      'credential missing',
    )
  })

  it('shows an unconfigured account as unverified, never healthy', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="accounts" />)
    expect(screen.getByTestId('routing-account-health-legacy-anthropic')).toHaveTextContent(
      'unverified',
    )
  })

  it('reports leases separately from in-flight requests', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="accounts" />)
    expect(screen.getByTestId('routing-account-leases-legacy-zai-harness')).toHaveTextContent('2')
  })

  it('reports the in-flight count for an actively routing account', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="accounts" />)
    expect(screen.getByTestId('routing-account-inflight-legacy-zai-harness')).toHaveTextContent('1')
  })

  it('shows an idle account as observed "none" rather than a zero-looking count', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="accounts" />)
    expect(screen.getByTestId('routing-account-observed-legacy-anthropic')).toHaveTextContent('none')
  })

  it('shows the error count against the qualifying denominator when degraded', () => {
    const degraded = toGatewayAccounts({
      available: true,
      source_state: 'available',
      data: {
        window_seconds: 900,
        summary: { configured: 1, enabled: 1, leased: 0, in_flight: 0 },
        accounts: [
          {
            account_id: 'legacy-anthropic',
            display_name: 'Anthropic',
            provider_binding: 'anthropic',
            configured: true,
            administrative_state: 'enabled',
            observed: true,
            observed_request_count: 10,
            observed_aborted_count: 6,
            observed_error_count: 3,
            health: 'degraded',
            health_reason: 'upstream-errors',
          },
        ],
      },
    })
    render(<RoutingMode accounts={degraded} routingView="accounts" />)
    expect(screen.getByTestId('routing-account-errors-legacy-anthropic')).toHaveTextContent('3/4')
  })

  it('hides the error fact entirely when nothing failed', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="accounts" />)
    expect(screen.queryByTestId('routing-account-errors-legacy-zai-harness')).toBeNull()
  })

  it('warns when health was computed from an evicted subsample', () => {
    const truncated = toGatewayAccounts({
      available: true,
      source_state: 'available',
      data: {
        window_seconds: 900,
        evidence_truncated: true,
        summary: { configured: 0, enabled: 0, leased: 0, in_flight: 0 },
        accounts: [],
      },
    })
    render(<RoutingMode accounts={truncated} routingView="accounts" />)
    expect(screen.getByTestId('routing-accounts-truncated')).toBeInTheDocument()
  })

  it('explains an unavailable source instead of rendering an empty inventory', () => {
    render(
      <RoutingMode
        accounts={toGatewayAccounts({ available: false, source_state: 'unreachable', data: null })}
        routingView="accounts"
      />,
    )
    expect(screen.getByTestId('routing-accounts-unavailable')).toHaveTextContent('unreachable')
  })

  it('names the missing environment variable when no control token is set', () => {
    render(
      <RoutingMode
        accounts={toGatewayAccounts({ available: false, source_state: 'not-configured', data: null })}
        routingView="accounts"
      />,
    )
    expect(screen.getByTestId('routing-accounts-unavailable')).toHaveTextContent(
      'HYDRAFLOW_GATEWAY_CONTROL_TOKEN',
    )
  })
})

describe('RoutingMode account capacity and circuit (#11540, ADR-0142)', () => {
  it('shows lease capacity as used over the declared limit', () => {
    render(<RoutingMode accounts={ACCOUNTS} routingView="accounts" />)
    expect(screen.getByTestId(`routing-account-leases-${ZAI}`)).toHaveTextContent('2 / 8')
  })

  it('shows request capacity as used over the declared limit', () => {
    render(<RoutingMode accounts={ACCOUNTS} routingView="accounts" />)
    expect(screen.getByTestId(`routing-account-inflight-${ZAI}`)).toHaveTextContent('1 / 4')
  })

  it('says "no limit" for an account that declares no ceiling', () => {
    render(<RoutingMode accounts={ACCOUNTS} routingView="accounts" />)
    expect(screen.getByTestId('routing-account-leases-legacy-anthropic')).toHaveTextContent(
      '0 / no limit',
    )
  })

  it('shows a closed circuit as its own fact', () => {
    render(<RoutingMode accounts={ACCOUNTS} routingView="accounts" />)
    expect(screen.getByTestId(`routing-account-circuit-${ZAI}`)).toHaveTextContent(
      'circuit closed',
    )
  })

  it('does not show a reset time or trip condition while the circuit is closed', () => {
    render(<RoutingMode accounts={ACCOUNTS} routingView="accounts" />)
    expect(screen.queryByTestId(`routing-account-circuit-detail-${ZAI}`)).toBeNull()
  })

  it('names the condition and the reset time when the circuit is open', () => {
    const open = toGatewayAccounts({
      available: true,
      source_state: 'available',
      data: {
        window_seconds: 900,
        summary: { configured: 1, enabled: 0, leased: 0, in_flight: 0 },
        accounts: [
          {
            account_id: ZAI,
            display_name: 'z.ai harness',
            provider_binding: 'zai-harness',
            configured: true,
            administrative_state: 'enabled',
            circuit_state: 'open',
            circuit_last_condition: 'rate_limited',
            circuit_reset_at: '2026-08-22T12:05:00Z',
            circuit_consecutive_failures: 3,
            health: 'degraded',
          },
        ],
      },
    })
    render(<RoutingMode accounts={open} routingView="accounts" />)
    expect(screen.getByTestId(`routing-account-circuit-detail-${ZAI}`)).toHaveTextContent(
      'rate_limited · resets 2026-08-22T12:05:00Z · 3 consecutive',
    )
  })
})

describe('RoutingMode host-admin controls (#11540, ADR-0142)', () => {
  it('renders no controls at all until the admin overlay has been read', () => {
    render(<RoutingMode accounts={ACCOUNTS} routingView="accounts" />)
    expect(screen.queryByTestId(`routing-account-controls-${ZAI}`)).toBeNull()
  })

  it('shows the overlay revision the controls act against', () => {
    renderAdmin()
    expect(screen.getByTestId('routing-admin-revision')).toHaveTextContent('revision 4')
  })

  it.each([
    ['enabled'],
    ['draining'],
    ['disabled'],
  ])('disables the %s control when the write gate is closed', state => {
    renderAdmin({
      admin: adminVm({ editable: false, writeGate: 'dashboard-not-loopback' }),
    })
    expect(screen.getByTestId(`routing-account-${state}-${ZAI}`)).toBeDisabled()
  })

  it('disables revoke when the write gate is closed rather than hiding it', () => {
    renderAdmin({
      admin: adminVm({ editable: false, writeGate: 'dashboard-not-loopback' }),
    })
    expect(screen.getByTestId(`routing-account-revoke-${ZAI}`)).toBeDisabled()
  })

  it('explains WHY the write gate is closed', () => {
    renderAdmin({
      admin: adminVm({ editable: false, writeGate: 'dashboard-not-loopback' }),
    })
    expect(screen.getByTestId('routing-admin-write-gate')).toHaveTextContent('loopback')
  })

  it('offers no token field while the gate is closed', () => {
    renderAdmin({ admin: adminVm({ editable: false }) })
    expect(screen.queryByTestId('routing-admin-token')).toBeNull()
  })

  it('refuses to write against an audit chain that does not verify', () => {
    renderAdmin({ admin: adminVm({ chainVerified: false }) })
    expect(screen.getByTestId(`routing-account-draining-${ZAI}`)).toBeDisabled()
  })

  it('says the chain is broken rather than blaming the write gate', () => {
    renderAdmin({ admin: adminVm({ chainVerified: false }) })
    expect(screen.getByTestId('routing-admin-write-gate')).toHaveTextContent(
      /audit chain does not verify/,
    )
  })

  it('keeps every control inert until the operator token is entered', () => {
    render(
      <RoutingMode accounts={ACCOUNTS} admin={adminVm()} routingView="accounts" />,
    )
    expect(screen.getByTestId(`routing-account-draining-${ZAI}`)).toBeDisabled()
  })

  it('does not offer the administrative state already in force', () => {
    renderAdmin()
    expect(screen.getByTestId(`routing-account-enabled-${ZAI}`)).toBeDisabled()
  })

  it('sends the state change with the revision the view was loaded with', () => {
    const { onSetAccountState } = renderAdmin()

    fireEvent.click(screen.getByTestId(`routing-account-draining-${ZAI}`))

    expect(onSetAccountState).toHaveBeenCalledWith(
      ZAI,
      { administrativeState: 'draining', expectedRevision: 4 },
      'hfop_secret',
    )
  })

  it('does not revoke leases on the first click', () => {
    const { onRevokeLeases } = renderAdmin()

    fireEvent.click(screen.getByTestId(`routing-account-revoke-${ZAI}`))

    expect(onRevokeLeases).not.toHaveBeenCalled()
  })

  it('names the blast radius in the confirmation step', () => {
    renderAdmin()

    fireEvent.click(screen.getByTestId(`routing-account-revoke-${ZAI}`))

    expect(screen.getByTestId(`routing-account-revoke-confirm-${ZAI}`)).toHaveTextContent(
      'end 2 lease(s)',
    )
  })

  it('revokes only after the explicit confirmation', () => {
    const { onRevokeLeases } = renderAdmin()

    fireEvent.click(screen.getByTestId(`routing-account-revoke-${ZAI}`))
    fireEvent.click(screen.getByTestId(`routing-account-revoke-confirm-${ZAI}`))

    expect(onRevokeLeases).toHaveBeenCalledWith(ZAI, { expectedRevision: 4 }, 'hfop_secret')
  })

  it('lets the operator back out of a revocation', () => {
    const { onRevokeLeases } = renderAdmin()

    fireEvent.click(screen.getByTestId(`routing-account-revoke-${ZAI}`))
    fireEvent.click(screen.getByTestId(`routing-account-revoke-cancel-${ZAI}`))

    expect(onRevokeLeases).not.toHaveBeenCalled()
  })

  it('confirms one account at a time, never every row at once', () => {
    renderAdmin()

    fireEvent.click(screen.getByTestId(`routing-account-revoke-${ZAI}`))

    expect(
      screen.queryByTestId('routing-account-revoke-confirm-legacy-anthropic'),
    ).toBeNull()
  })

  it('renders a 409 as "reload, someone else changed this"', async () => {
    renderAdmin({
      onSetAccountState: vi.fn().mockResolvedValue({ ok: false, code: 'stale-revision' }),
    })

    fireEvent.click(screen.getByTestId(`routing-account-draining-${ZAI}`))

    await waitFor(() =>
      expect(screen.getByTestId('routing-admin-conflict')).toHaveTextContent(/Reload/),
    )
  })

  it('does not render a generic error for a refusal it can name', async () => {
    renderAdmin({
      onSetAccountState: vi.fn().mockResolvedValue({ ok: false, code: 'stale-revision' }),
    })

    fireEvent.click(screen.getByTestId(`routing-account-draining-${ZAI}`))

    await waitFor(() =>
      expect(screen.getByTestId('routing-admin-conflict')).toHaveTextContent(
        /administrative overlay moved/,
      ),
    )
  })

  it('warns and stops writing when someone else advanced the revision underneath', () => {
    const { rerender } = render(
      <RoutingMode accounts={ACCOUNTS} admin={adminVm({ revision: 4 })} routingView="accounts" />,
    )
    fireEvent.change(screen.getByTestId('routing-admin-token'), {
      target: { value: 'hfop_secret' },
    })

    rerender(
      <RoutingMode accounts={ACCOUNTS} admin={adminVm({ revision: 5 })} routingView="accounts" />,
    )

    expect(screen.getByTestId('routing-admin-rebased')).toBeInTheDocument()
  })

  it('holds the pinned revision rather than following the live poll', () => {
    const onSetAccountState = vi.fn()
    const { rerender } = render(
      <RoutingMode
        accounts={ACCOUNTS}
        admin={adminVm({ revision: 4 })}
        routingView="accounts"
        onSetAccountState={onSetAccountState}
      />,
    )
    fireEvent.change(screen.getByTestId('routing-admin-token'), {
      target: { value: 'hfop_secret' },
    })
    rerender(
      <RoutingMode
        accounts={ACCOUNTS}
        admin={adminVm({ revision: 5 })}
        routingView="accounts"
        onSetAccountState={onSetAccountState}
      />,
    )
    fireEvent.click(screen.getByTestId('routing-admin-rebase-button'))

    fireEvent.click(screen.getByTestId(`routing-account-draining-${ZAI}`))

    expect(onSetAccountState).toHaveBeenCalledWith(
      ZAI,
      { administrativeState: 'draining', expectedRevision: 5 },
      'hfop_secret',
    )
  })

  it('never puts the operator token in the DOM as readable text', () => {
    renderAdmin()
    expect(screen.getByTestId('routing-admin-token')).toHaveAttribute('type', 'password')
  })
})

describe('RoutingMode live view', () => {
  it('shows the streaming request', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="live" />)
    expect(screen.getByTestId('routing-inflight-req-live')).toBeInTheDocument()
  })

  it('shows the lease age', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="live" />)
    expect(screen.getByTestId('routing-lease-age-key-1')).toHaveTextContent('30s')
  })

  it('shows the requested model for a terminal route', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="live" />)
    expect(screen.getByTestId('routing-recent-requested-req-done')).toHaveTextContent('glm-5.2')
  })

  it('shows the served model for a terminal route', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="live" />)
    expect(screen.getByTestId('routing-recent-served-req-done')).toHaveTextContent('glm-5.3')
  })

  it('shows the terminal status and code', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="live" />)
    expect(screen.getByTestId('routing-recent-status-req-done')).toHaveTextContent('completed 200')
  })

  it('renders a calm empty state when nothing is streaming', () => {
    const idle = toGatewayLiveRoutes(
      { available: true, source_state: 'available', data: { leases: [], in_flight: [] } },
      { available: true, source_state: 'available', data: { routes: [] } },
    )
    render(<RoutingMode accounts={ACCOUNTS} live={idle} routingView="live" />)
    expect(screen.getByTestId('routing-inflight-empty')).toBeInTheDocument()
  })

  it('explains an unavailable source instead of claiming no traffic', () => {
    render(
      <RoutingMode
        live={toGatewayLiveRoutes(null, null)}
        routingView="live"
      />,
    )
    expect(screen.getByTestId('routing-live-unavailable')).toBeInTheDocument()
  })
})

describe('RoutingMode view selection', () => {
  it('defaults to the accounts view for an unknown sub-view', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="bogus" />)
    expect(screen.getByTestId('routing-accounts')).toBeInTheDocument()
  })

  it('selects the live view through the URL-addressable selection', () => {
    const select = vi.fn()
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="accounts" select={select} />)

    fireEvent.click(screen.getByTestId('routing-view-live'))

    expect(select).toHaveBeenCalledWith('routingView', 'live')
  })

  it.each([
    ['effective', 'effective-routes'],
    ['policies', 'policy-workspace'],
    ['audit', 'policy-audit'],
  ])('renders the %s workspace view (#11538)', (view, testid) => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView={view} />)
    expect(screen.getByTestId(testid)).toBeInTheDocument()
  })

  it('offers all five sub-views the routing design reserves', () => {
    render(<RoutingMode accounts={ACCOUNTS} live={LIVE} routingView="accounts" />)
    expect(screen.getAllByRole('tab').map(tab => tab.textContent)).toEqual([
      'Accounts',
      'Effective routes',
      'Policies',
      'Live',
      'Audit',
    ])
  })
})

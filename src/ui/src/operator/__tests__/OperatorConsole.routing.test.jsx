/**
 * Routing-mode container wiring (#11534, ADR-0138).
 *
 * Pins the seams a panel-only test cannot see: the mode is reachable from the
 * toggle, URL-addressable, idle-EXEMPT (a quiet factory is exactly when an
 * operator asks whether any account is configured), and the two gateway VMs
 * flow from the container props into the rendered rows.
 */

import React from 'react'
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { OperatorConsoleView } from '../OperatorConsole'
import { toGatewayAccounts, toGatewayLiveRoutes } from '../model/gatewayRouting'

const EMPTY_STAGES = {
  triage: [],
  plan: [],
  implement: [],
  review: [],
  hitl: [],
  merged: [],
}

function idleSocket() {
  return { events: [], pipelineIssues: EMPTY_STAGES, pipelineStats: null }
}

const ACCOUNTS = toGatewayAccounts({
  available: true,
  source_state: 'available',
  data: {
    window_seconds: 900,
    evidence_since: '2026-08-22T11:00:00Z',
    summary: { configured: 1, enabled: 1, leased: 0, in_flight: 0 },
    accounts: [
      {
        account_id: 'legacy-zai-harness',
        display_name: 'z.ai harness (legacy upstream)',
        provider_binding: 'zai-harness',
        base_origin: 'https://zai.test',
        configured: true,
        administrative_state: 'enabled',
        leased: false,
        lease_count: 0,
        in_flight: false,
        in_flight_count: 0,
        observed: false,
        observed_request_count: 0,
        observed_error_count: 0,
        health: 'unverified',
        health_reason: 'no-evidence',
      },
    ],
  },
})

const LIVE = toGatewayLiveRoutes(
  {
    available: true,
    source_state: 'available',
    data: {
      leases: [],
      in_flight: [
        {
          request_id: 'req-live',
          account_id: 'legacy-zai-harness',
          repo_slug: 'acme/hydraflow',
          principal_id: 'implementer',
          worker_role: 'implementer',
          age_seconds: 3,
        },
      ],
    },
  },
  { available: true, source_state: 'available', data: { routes: [], truncated: false } },
)

describe('OperatorConsole — Routing mode', () => {
  let originalHref

  beforeEach(() => {
    originalHref = window.location.href
    window.history.replaceState({}, '', '/')
  })

  afterEach(() => {
    window.history.replaceState({}, '', originalHref)
  })

  it('offers Routing in the mode toggle', () => {
    render(<OperatorConsoleView socket={idleSocket()} />)

    expect(screen.getByTestId('mode-toggle-routing')).toBeInTheDocument()
  })

  it('renders the routing workspace when the mode is selected', () => {
    render(<OperatorConsoleView socket={idleSocket()} gatewayAccounts={ACCOUNTS} />)

    fireEvent.click(screen.getByTestId('mode-toggle-routing'))

    expect(screen.getByTestId('routing-mode')).toBeInTheDocument()
  })

  it('mirrors the routing mode into the URL', () => {
    render(<OperatorConsoleView socket={idleSocket()} gatewayAccounts={ACCOUNTS} />)

    fireEvent.click(screen.getByTestId('mode-toggle-routing'))

    expect(new URLSearchParams(window.location.search).get('mode')).toBe('routing')
  })

  it('survives an idle factory (idle exemption)', () => {
    render(<OperatorConsoleView socket={idleSocket()} gatewayAccounts={ACCOUNTS} />)

    fireEvent.click(screen.getByTestId('mode-toggle-routing'))

    expect(screen.queryByTestId('idle-state')).toBeNull()
  })

  it('flows the accounts view model through to a rendered account row', () => {
    window.history.replaceState({}, '', '/?mode=routing')
    render(<OperatorConsoleView socket={idleSocket()} gatewayAccounts={ACCOUNTS} />)

    expect(screen.getByTestId('routing-account-legacy-zai-harness')).toBeInTheDocument()
  })

  it('restores the live sub-view straight from the URL', () => {
    window.history.replaceState({}, '', '/?mode=routing&routingView=live')
    render(
      <OperatorConsoleView socket={idleSocket()} gatewayAccounts={ACCOUNTS} gatewayLive={LIVE} />,
    )

    expect(screen.getByTestId('routing-inflight-req-live')).toBeInTheDocument()
  })

  it('mirrors the routing sub-view into the URL', () => {
    window.history.replaceState({}, '', '/?mode=routing')
    render(
      <OperatorConsoleView socket={idleSocket()} gatewayAccounts={ACCOUNTS} gatewayLive={LIVE} />,
    )

    fireEvent.click(screen.getByTestId('routing-view-live'))

    expect(new URLSearchParams(window.location.search).get('routingView')).toBe('live')
  })

  it('renders the degraded source state when no gateway data was fetched', () => {
    window.history.replaceState({}, '', '/?mode=routing')
    render(<OperatorConsoleView socket={idleSocket()} />)

    expect(screen.getByTestId('routing-accounts-unavailable')).toBeInTheDocument()
  })
})

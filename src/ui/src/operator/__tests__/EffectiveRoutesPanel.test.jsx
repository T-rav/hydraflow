/**
 * EffectiveRoutesPanel — the pinned route matrix (#11538, ADR-0140).
 *
 * The grid's job is to be readable without being reassuring: an unclaimed route
 * is neutral (legacy still decides it), a held route says which guard held it,
 * and selecting a cell opens the explanation the batch ALREADY returned rather
 * than triggering a fresh resolve against a newer revision.
 */

import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import EffectiveRoutesPanel from '../EffectiveRoutesPanel'
import { toEffectiveMatrix } from '../model/policyWorkspace'

const MANAGED_KEY = 'implementer|agentic|capability:balanced'
const UNMANAGED_KEY = 'reviewer|one-shot|capability:balanced'

function matrix(overrides = {}) {
  return toEffectiveMatrix({
    repo: 'acme/hydraflow',
    policy_revision: 4,
    snapshot_hash: 'sha256:abc',
    snapshot_state: 'ok',
    cells: [
      {
        key: MANAGED_KEY,
        role: 'implementer',
        request_face: 'agentic',
        requirement: { kind: 'capability', value: 'balanced' },
        state: 'managed',
        outcome: 'selected',
        reason: 'matched-policy',
        policy_source: 'managed-policy',
        policy_id: 'pin-zai',
        policy_revision: 4,
        account_id: 'legacy-zai-harness',
        provider_binding: 'zai-harness',
        effective_model: 'glm-5.3',
        explanation: {
          context: { worker_role: 'implementer' },
          considered: [
            {
              policy_id: 'pin-zai',
              precedence_level: 4,
              priority: 0,
              matched: true,
              reason: 'matched',
            },
          ],
          rejected_accounts: [
            { account_id: 'legacy-anthropic', reason: 'provider-lock-mismatch' },
          ],
        },
      },
      {
        key: UNMANAGED_KEY,
        role: 'reviewer',
        request_face: 'one-shot',
        requirement: { kind: 'capability', value: 'balanced' },
        state: 'unmanaged',
        outcome: 'held',
        reason: 'no-legacy-route',
        policy_source: 'none',
        policy_id: null,
        policy_revision: 4,
        account_id: null,
        provider_binding: null,
        effective_model: null,
        explanation: { context: {}, considered: [] },
      },
    ],
    ...overrides,
  })
}

describe('EffectiveRoutesPanel', () => {
  it('pins the policy revision the grid was drawn from', () => {
    render(<EffectiveRoutesPanel matrix={matrix()} />)
    expect(screen.getByTestId('effective-revision')).toHaveTextContent('policy revision 4')
  })

  it('shows the account a managed route resolves to', () => {
    render(<EffectiveRoutesPanel matrix={matrix()} />)
    expect(screen.getByTestId(`effective-account-${MANAGED_KEY}`)).toHaveTextContent(
      'legacy-zai-harness',
    )
  })

  it('draws an unclaimed route as unmanaged rather than failed', () => {
    render(<EffectiveRoutesPanel matrix={matrix()} />)
    expect(screen.getByTestId(`effective-state-${UNMANAGED_KEY}`)).toHaveTextContent('unmanaged')
  })

  it('prompts for a selection before showing a trace', () => {
    render(<EffectiveRoutesPanel matrix={matrix()} />)
    expect(screen.getByTestId('effective-trace-empty')).toBeInTheDocument()
  })

  it('round-trips the selected cell through the URL', () => {
    const select = vi.fn()
    render(<EffectiveRoutesPanel matrix={matrix()} select={select} />)

    fireEvent.click(screen.getByTestId(`effective-cell-${MANAGED_KEY}`))

    expect(select).toHaveBeenCalledWith('routingSelection', MANAGED_KEY)
  })

  it('renders the explanation that came with the matrix', () => {
    render(<EffectiveRoutesPanel matrix={matrix()} selection={MANAGED_KEY} />)
    expect(screen.getByTestId('effective-considered-pin-zai')).toHaveTextContent('matched')
  })

  it('names every account the route refused and why', () => {
    render(<EffectiveRoutesPanel matrix={matrix()} selection={MANAGED_KEY} />)
    expect(screen.getByTestId('effective-rejected-legacy-anthropic')).toHaveTextContent(
      'provider-lock-mismatch',
    )
  })

  it('says a corrupt snapshot is a hold, not an absence of policy', () => {
    render(<EffectiveRoutesPanel matrix={matrix({ snapshot_state: 'corrupt' })} />)
    expect(screen.getByTestId('effective-snapshot-note')).toHaveTextContent('held')
  })

  it('says legacy decides when no policy has been written', () => {
    render(<EffectiveRoutesPanel matrix={matrix({ snapshot_state: 'absent' })} />)
    expect(screen.getByTestId('effective-snapshot-note')).toHaveTextContent('legacy routing')
  })

  it('renders a calm empty state before the matrix loads', () => {
    render(<EffectiveRoutesPanel />)
    expect(screen.getByTestId('effective-empty')).toBeInTheDocument()
  })
})

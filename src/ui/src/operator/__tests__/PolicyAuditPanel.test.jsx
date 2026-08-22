/**
 * PolicyAuditPanel — the mutation history, kept apart from traffic (#11538).
 *
 * Two things it must never soften: a chain that does not verify is a headline,
 * and a record written by crash recovery — or an intent that never reached the
 * snapshot — is shown as what it is rather than tidied away.
 */

import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import PolicyAuditPanel from '../PolicyAuditPanel'
import { toPolicyAudit } from '../model/policyWorkspace'

function record(overrides = {}) {
  return {
    seq: 0,
    recorded_at: '2026-08-22T12:00:00+00:00',
    payload: {
      kind: 'create',
      outcome: 'committed',
      actor: 'travis',
      recovered: false,
      prior_revision: 0,
      new_revision: 1,
      diff: { added: ['pin-zai'], removed: [], changed: [] },
      ...overrides,
    },
  }
}

describe('PolicyAuditPanel', () => {
  it('renders a calm empty state for a repository that never wrote a policy', () => {
    render(<PolicyAuditPanel audit={toPolicyAudit({ records: [], verified: true })} />)
    expect(screen.getByTestId('policy-audit-empty')).toBeInTheDocument()
  })

  it('names both sides of the revision move', () => {
    render(<PolicyAuditPanel audit={toPolicyAudit({ records: [record()], verified: true })} />)
    expect(screen.getByTestId('policy-audit-0')).toHaveTextContent('r0 → r1')
  })

  it('names the authenticated actor', () => {
    render(<PolicyAuditPanel audit={toPolicyAudit({ records: [record()], verified: true })} />)
    expect(screen.getByTestId('policy-audit-0')).toHaveTextContent('travis')
  })

  it('headlines a chain that does not verify', () => {
    render(
      <PolicyAuditPanel
        audit={toPolicyAudit({ records: [record()], verified: false, broken_at_seq: 2 })}
      />,
    )
    expect(screen.getByTestId('policy-audit-broken')).toHaveTextContent('seq 2')
  })

  it('shows an aborted intent rather than leaving a gap in the sequence', () => {
    render(
      <PolicyAuditPanel
        audit={toPolicyAudit({ records: [record({ outcome: 'aborted' })], verified: true })}
      />,
    )
    expect(screen.getByTestId('policy-audit-outcome-0')).toHaveTextContent('aborted')
  })

  it('marks a record written by crash recovery as recovered', () => {
    render(
      <PolicyAuditPanel
        audit={toPolicyAudit({ records: [record({ recovered: true })], verified: true })}
      />,
    )
    expect(screen.getByTestId('policy-audit-recovered-0')).toBeInTheDocument()
  })

  it('names the rollback target on a rollback record', () => {
    render(
      <PolicyAuditPanel
        audit={toPolicyAudit({
          records: [record({ kind: 'rollback', target_revision: 1, new_revision: 3 })],
          verified: true,
        })}
      />,
    )
    expect(screen.getByTestId('policy-audit-0')).toHaveTextContent('target r1')
  })

  it('says the page is not the complete history when it is truncated', () => {
    render(
      <PolicyAuditPanel
        audit={toPolicyAudit({ records: [record()], verified: true, truncated: true })}
      />,
    )
    expect(screen.getByTestId('policy-audit-truncated')).toBeInTheDocument()
  })
})

describe('PolicyAuditPanel — what it may not claim', () => {
  it('says the chain is unread rather than verified before anything is fetched', () => {
    // The frozen empty VM is what a session renders on its first cycle, and a
    // "chain verified" badge there is a positive tamper-evidence claim about
    // bytes nobody read.
    render(<PolicyAuditPanel />)
    expect(screen.getByTestId('policy-audit-verified')).toHaveTextContent('chain unread')
  })

  it('does not render a "no mutation" empty state it has not earned', () => {
    render(<PolicyAuditPanel />)
    expect(screen.queryByTestId('policy-audit-empty')).toBeNull()
  })

  it('names an unreachable policy plane instead of an empty history', () => {
    render(<PolicyAuditPanel sourceState="unavailable" />)
    expect(screen.getByTestId('policy-audit-feed-notice')).toHaveTextContent(
      'NOT "no policy"',
    )
  })
})

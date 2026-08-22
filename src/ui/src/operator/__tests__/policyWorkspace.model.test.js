/**
 * Routing-policy view models (#11538, ADR-0140). Pure reducers, no React.
 *
 * The rules under test are honesty rules: `corrupt` never reads as "no
 * policies", an inherited rule never reads as editable, an unclaimed route never
 * reads as a fault, and no credential ever reaches a VM.
 */

import { describe, it, expect } from 'vitest'
import {
  AGGREGATE_MESSAGE,
  EMPTY_EFFECTIVE_MATRIX_VM,
  EMPTY_POLICY_AUDIT_VM,
  EMPTY_POLICY_WORKSPACE_VM,
  LOADING_MESSAGE,
  STALE_MESSAGE,
  UNAVAILABLE_MESSAGE,
  cellTone,
  feedIsCurrent,
  feedNotice,
  draftToPolicy,
  policyToDraft,
  rejectionMessage,
  requirementLabel,
  snapshotTone,
  toEffectiveMatrix,
  toPolicyAudit,
  toPolicyPreview,
  toPolicyWorkspace,
  writeGateMessage,
} from '../model/policyWorkspace'

const POLICY = {
  id: 'pin-zai',
  enabled: true,
  priority: 3,
  match: { repo_ids: ['acme/hydraflow'], roles: ['implementer'] },
  action: {
    provider_lock: 'zai-harness',
    requirement_map: [
      {
        requirement: { kind: 'capability', value: 'balanced' },
        effective_model: 'glm-5.3',
      },
    ],
    on_unavailable: 'hold',
  },
}

const INHERITED = {
  id: 'global-rule',
  enabled: true,
  match: { repo_ids: [] },
  action: { provider_lock: 'anthropic' },
}

const WORKSPACE_PAYLOAD = {
  scope: 'repo',
  repo: 'acme/hydraflow',
  state: 'ok',
  revision: 4,
  content_hash: 'sha256:abc',
  policies: [POLICY, INHERITED],
  editable_policy_ids: ['pin-zai'],
  issues: [],
  write_gate: 'enabled',
  editable: true,
}

describe('toPolicyWorkspace', () => {
  it('returns the frozen empty VM for a malformed payload', () => {
    expect(toPolicyWorkspace(null)).toBe(EMPTY_POLICY_WORKSPACE_VM)
  })

  it('marks only the repo-scoped policy editable', () => {
    const vm = toPolicyWorkspace(WORKSPACE_PAYLOAD)
    expect(vm.policies.map(p => [p.id, p.editable])).toEqual([
      ['pin-zai', true],
      ['global-rule', false],
    ])
  })

  it('keeps a corrupt snapshot state on the VM', () => {
    // Collapsing corrupt into "no policies" is the false-coherent state the
    // whole design forbids.
    expect(toPolicyWorkspace({ ...WORKSPACE_PAYLOAD, state: 'corrupt' }).state).toBe('corrupt')
  })

  it('keeps the write gate so an editor can render read-only with a reason', () => {
    const vm = toPolicyWorkspace({
      ...WORKSPACE_PAYLOAD,
      editable: false,
      write_gate: 'dashboard-not-loopback',
    })
    expect([vm.editable, vm.writeGate]).toEqual([false, 'dashboard-not-loopback'])
  })

  it('summarises a policy as its lock plus its model mapping', () => {
    expect(toPolicyWorkspace(WORKSPACE_PAYLOAD).policies[0].summary).toBe(
      'zai-harness · capability:balanced→glm-5.3',
    )
  })

  it('distinguishes not-fetched-yet from fetched-and-empty', () => {
    expect([EMPTY_POLICY_WORKSPACE_VM.loaded, toPolicyWorkspace({}).loaded]).toEqual([
      false,
      true,
    ])
  })
})

describe('toEffectiveMatrix', () => {
  const MATRIX_PAYLOAD = {
    repo: 'acme/hydraflow',
    policy_revision: 4,
    snapshot_hash: 'sha256:abc',
    snapshot_state: 'ok',
    cells: [
      {
        key: 'implementer|agentic|capability:balanced',
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
        explanation: { considered: [], context: {} },
      },
    ],
  }

  it('returns the frozen empty VM for a malformed payload', () => {
    expect(toEffectiveMatrix(undefined)).toBe(EMPTY_EFFECTIVE_MATRIX_VM)
  })

  it('carries the pinned explanation onto the cell', () => {
    expect(toEffectiveMatrix(MATRIX_PAYLOAD).cells[0].explanation).toEqual({
      considered: [],
      context: {},
    })
  })

  it('renders the requirement as the kind:value selector the API accepts', () => {
    expect(toEffectiveMatrix(MATRIX_PAYLOAD).cells[0].requirement).toBe('capability:balanced')
  })
})

describe('tones', () => {
  it('never draws an unclaimed route as a fault', () => {
    // Shadow mode is authoritative: "no policy" means legacy decides, and a red
    // badge would train an operator to write policy to silence it.
    expect(cellTone('unmanaged')).toBe('neutral')
  })

  it('separates a held route from a rejected one', () => {
    expect([cellTone('held'), cellTone('rejected')]).toEqual(['warning', 'danger'])
  })

  it('treats an absent snapshot as normal and a corrupt one as not', () => {
    expect([snapshotTone('absent'), snapshotTone('corrupt')]).toEqual(['neutral', 'danger'])
  })
})

describe('toPolicyAudit', () => {
  const AUDIT_PAYLOAD = {
    verified: true,
    truncated: false,
    records: [
      {
        seq: 0,
        recorded_at: '2026-08-22T12:00:00+00:00',
        payload: {
          kind: 'create',
          outcome: 'committed',
          actor: 'travis',
          prior_revision: 0,
          new_revision: 1,
          diff: { added: ['pin-zai'], removed: [], changed: [] },
        },
      },
    ],
  }

  it('returns the frozen empty VM for a malformed payload', () => {
    expect(toPolicyAudit(null)).toBe(EMPTY_POLICY_AUDIT_VM)
  })

  it('offers revision 0 alongside every committed revision as a rollback target', () => {
    // Revision 0 is a real target: the state before any policy was written.
    expect(toPolicyAudit(AUDIT_PAYLOAD).rollbackTargets).toEqual([0, 1])
  })

  it('surfaces a broken chain rather than an empty history', () => {
    const vm = toPolicyAudit({ ...AUDIT_PAYLOAD, verified: false, broken_at_seq: 3 })
    expect([vm.verified, vm.brokenAtSeq]).toEqual([false, 3])
  })
})

describe('toPolicyPreview', () => {
  it('keeps only the cells that actually move', () => {
    const vm = toPolicyPreview({
      writable: true,
      diff: { added: ['pin-zai'], removed: [], changed: [] },
      cells: [
        { key: 'a', changed: true, changed_fields: ['state'], before: null, after: null },
        { key: 'b', changed: false, changed_fields: [] },
      ],
    })
    expect(vm.movedCells.map(cell => cell.key)).toEqual(['a'])
  })

  it('reports a stale edit without refusing to render it', () => {
    const vm = toPolicyPreview({ writable: false, stale: true, cells: [] })
    expect([vm.stale, vm.writable]).toEqual([true, false])
  })
})

describe('draftToPolicy', () => {
  it('scopes the rule to the workspace repository, never a typed one', () => {
    const body = draftToPolicy({ id: 'pin-zai', roles: [] }, 'acme/hydraflow')
    expect(body.match.repo_ids).toEqual(['acme/hydraflow'])
  })

  it('never claims system safety from a repo-scoped editor', () => {
    expect(draftToPolicy({ id: 'x' }, 'acme/hydraflow').system_safety).toBe(false)
  })

  it('omits the requirement map when no model was named', () => {
    // A bare provider lock is a legitimate (if held) policy; inventing a mapping
    // would be the resolver guessing, which ADR-0139 D4 forbids.
    expect(draftToPolicy({ id: 'x', effectiveModel: '  ' }, 'r/r').action.requirement_map).toEqual(
      [],
    )
  })

  it('splits the kind:value selector back into the API pair', () => {
    const body = draftToPolicy(
      { id: 'x', requirement: 'literal_family:claude-opus', effectiveModel: 'claude-opus-4-8' },
      'r/r',
    )
    expect(body.action.requirement_map[0].requirement).toEqual({
      kind: 'literal_family',
      value: 'claude-opus',
    })
  })

  it('round-trips an existing policy back through the editor', () => {
    const row = toPolicyWorkspace(WORKSPACE_PAYLOAD).policies[0]
    expect(draftToPolicy(policyToDraft(row), 'acme/hydraflow')).toEqual({
      id: 'pin-zai',
      enabled: true,
      priority: 3,
      system_safety: false,
      match: { repo_ids: ['acme/hydraflow'], roles: ['implementer'] },
      action: {
        provider_lock: 'zai-harness',
        requirement_map: [
          {
            requirement: { kind: 'capability', value: 'balanced' },
            effective_model: 'glm-5.3',
          },
        ],
        on_unavailable: 'hold',
      },
    })
  })
})

describe('operator-facing prose', () => {
  it('explains the loopback gate in terms of the fix', () => {
    expect(writeGateMessage('dashboard-not-loopback')).toContain('loopback')
  })

  it('falls back to the raw code for an unknown refusal', () => {
    expect(rejectionMessage('something-new')).toBe('something-new')
  })

  it('renders an empty requirement as an empty label rather than "undefined"', () => {
    expect(requirementLabel(null)).toBe('')
  })
})

describe('feedNotice — what a panel is entitled to claim', () => {
  it('says nothing once a current payload has landed', () => {
    expect(feedNotice('available', true)).toBe('')
  })

  it('says the feed is still loading before anything lands', () => {
    expect(feedNotice('loading', false)).toBe(LOADING_MESSAGE)
  })

  it('says a dead feed is NOT an empty repository', () => {
    expect(feedNotice('unavailable', false)).toBe(UNAVAILABLE_MESSAGE)
  })

  it('keeps speaking once a feed that loaded then died', () => {
    // The hook keeps the last-known VM on failure, so silence here would leave
    // the panel rendering a frozen revision as though it were current.
    expect(feedNotice('unavailable', true)).toBe(STALE_MESSAGE)
  })

  it('tells an aggregate reader to pick a repository', () => {
    expect(feedNotice('aggregate', false)).toBe(AGGREGATE_MESSAGE)
  })

  it('marks only an unavailable source as not current', () => {
    expect(
      ['loading', 'available', 'aggregate', 'unavailable'].map(feedIsCurrent),
    ).toEqual([true, true, true, false])
  })
})

describe('toPolicyAudit — verification is three-state', () => {
  it('invents no verification when the payload does not carry one', () => {
    expect(toPolicyAudit({ records: [] }).verified).toBeNull()
  })

  it('reports a verified chain when the payload says so', () => {
    expect(toPolicyAudit({ records: [], verified: true }).verified).toBe(true)
  })

  it('reports a broken chain when the payload says so', () => {
    expect(toPolicyAudit({ records: [], verified: false }).verified).toBe(false)
  })

  it('offers each committed revision exactly once as a rollback target', () => {
    const record = revision => ({
      seq: revision - 1,
      payload: { outcome: 'committed', new_revision: revision, diff: {} },
    })
    const vm = toPolicyAudit({ verified: true, records: [record(1), record(1), record(2)] })

    expect(vm.rollbackTargets).toEqual([0, 1, 2])
  })
})

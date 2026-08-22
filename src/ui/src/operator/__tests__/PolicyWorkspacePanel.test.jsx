/**
 * PolicyWorkspacePanel — the console's first write surface (#11538, ADR-0140).
 *
 * The behaviours pinned here are the ones a prettier editor would quietly lose:
 * a closed write gate renders its REASON rather than a save button that always
 * 403s, an inherited rule has no actions, a save is impossible until a preview
 * says the edit is writable, and a conflict names the revision that won.
 */

import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import PolicyWorkspacePanel, { MAX_ROLLBACK_BUTTONS } from '../PolicyWorkspacePanel'
import { toPolicyAudit, toPolicyPreview, toPolicyWorkspace } from '../model/policyWorkspace'

const REPO = 'acme/hydraflow'

function workspace(overrides = {}) {
  return toPolicyWorkspace({
    scope: 'repo',
    repo: REPO,
    state: 'ok',
    revision: 4,
    content_hash: 'sha256:abc',
    policies: [
      {
        id: 'pin-zai',
        enabled: true,
        match: { repo_ids: [REPO] },
        action: {
          provider_lock: 'zai-harness',
          requirement_map: [
            {
              requirement: { kind: 'capability', value: 'balanced' },
              effective_model: 'glm-5.3',
            },
          ],
        },
      },
      {
        id: 'global-rule',
        enabled: true,
        match: { repo_ids: [] },
        action: { provider_lock: 'anthropic' },
      },
    ],
    editable_policy_ids: ['pin-zai'],
    issues: [],
    write_gate: 'enabled',
    editable: true,
    ...overrides,
  })
}

const WRITABLE_PREVIEW = toPolicyPreview({
  writable: true,
  stale: false,
  expected_revision: 4,
  next_revision: 5,
  issues: [],
  diff: { added: ['second'], removed: [], changed: [] },
  cells: [
    {
      key: 'implementer|agentic|capability:balanced',
      changed: true,
      changed_fields: ['state'],
      before: { key: 'k', state: 'unmanaged' },
      after: { key: 'k', state: 'managed' },
    },
  ],
})

const AUDIT = toPolicyAudit({
  verified: true,
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
})

/** Fill the editor enough to save: an operator token plus a policy id. */
function fillEditor(id = 'second') {
  fireEvent.change(screen.getByTestId('policy-field-id'), { target: { value: id } })
  fireEvent.change(screen.getByTestId('policy-field-token'), {
    target: { value: 'operator-token' },
  })
}

describe('PolicyWorkspacePanel — the write gate', () => {
  it('explains a closed gate instead of offering an editor', () => {
    render(
      <PolicyWorkspacePanel
        workspace={workspace({ editable: false, write_gate: 'dashboard-not-loopback' })}
      />,
    )
    expect(screen.getByTestId('policy-write-gate')).toHaveTextContent('loopback')
  })

  it('renders no editor at all when writes are closed', () => {
    render(
      <PolicyWorkspacePanel
        workspace={workspace({ editable: false, write_gate: 'no-operator-identity' })}
      />,
    )
    expect(screen.queryByTestId('policy-editor')).toBeNull()
  })

  it('renders the editor when the gate is open', () => {
    render(<PolicyWorkspacePanel workspace={workspace()} />)
    expect(screen.getByTestId('policy-editor')).toBeInTheDocument()
  })

  it('renders aggregate mode read-only', () => {
    render(
      <PolicyWorkspacePanel
        workspace={toPolicyWorkspace({
          scope: 'aggregate',
          editable: false,
          write_gate: 'enabled',
          repos: [
            {
              repo: REPO,
              slug: 'acme-hydraflow',
              state: 'ok',
              revision: 4,
              policy_count: 2,
              editable_count: 1,
            },
          ],
        })}
      />,
    )
    expect(screen.getByTestId('policy-aggregate-readonly')).toBeInTheDocument()
  })
})

describe('PolicyWorkspacePanel — scope', () => {
  it('marks an inherited rule as inherited', () => {
    render(<PolicyWorkspacePanel workspace={workspace()} />)
    expect(screen.getByTestId('policy-scope-global-rule')).toHaveTextContent('inherited')
  })

  it('offers no edit action on an inherited rule', () => {
    render(<PolicyWorkspacePanel workspace={workspace()} />)
    expect(screen.queryByTestId('policy-edit-global-rule')).toBeNull()
  })

  it('offers an edit action on this repository’s own rule', () => {
    render(<PolicyWorkspacePanel workspace={workspace()} />)
    expect(screen.getByTestId('policy-edit-pin-zai')).toBeInTheDocument()
  })

  it('has no repository field, because the scope is not typed', () => {
    render(<PolicyWorkspacePanel workspace={workspace()} />)
    expect(screen.queryByTestId('policy-field-repo')).toBeNull()
  })
})

describe('PolicyWorkspacePanel — preview before write', () => {
  it('disables save until a preview says the edit is writable', () => {
    render(<PolicyWorkspacePanel workspace={workspace()} />)
    fillEditor()
    expect(screen.getByTestId('policy-save-button')).toBeDisabled()
  })

  it('disables save without an operator token even after a clean preview', () => {
    render(<PolicyWorkspacePanel workspace={workspace()} preview={WRITABLE_PREVIEW} />)
    expect(screen.getByTestId('policy-save-button')).toBeDisabled()
  })

  it('enables save once the preview is writable and a token is present', () => {
    render(<PolicyWorkspacePanel workspace={workspace()} preview={WRITABLE_PREVIEW} />)
    fillEditor()
    expect(screen.getByTestId('policy-save-button')).toBeEnabled()
  })

  it('previews against the revision it loaded', () => {
    const onPreview = vi.fn()
    render(<PolicyWorkspacePanel workspace={workspace()} onPreview={onPreview} />)
    fillEditor()

    fireEvent.click(screen.getByTestId('policy-preview-button'))

    expect(onPreview.mock.calls[0][0].expected_revision).toBe(4)
  })

  it('scopes the previewed policy to the workspace repository', () => {
    const onPreview = vi.fn()
    render(<PolicyWorkspacePanel workspace={workspace()} onPreview={onPreview} />)
    fillEditor()

    fireEvent.click(screen.getByTestId('policy-preview-button'))

    expect(onPreview.mock.calls[0][0].policy.match.repo_ids).toEqual([REPO])
  })

  it('lists the live routes an edit would move', () => {
    render(<PolicyWorkspacePanel workspace={workspace()} preview={WRITABLE_PREVIEW} />)
    expect(
      screen.getByTestId('policy-moved-implementer|agentic|capability:balanced'),
    ).toHaveTextContent('unmanaged → managed')
  })

  it('renders a conflict reported by the preview rather than by the save', () => {
    const conflicted = toPolicyPreview({
      writable: false,
      issues: [{ code: 'equal-precedence-conflict', policy_id: 'pin-claude', detail: 'pin-zai' }],
      cells: [],
      diff: {},
    })
    render(<PolicyWorkspacePanel workspace={workspace()} preview={conflicted} />)
    expect(screen.getByTestId('policy-issue-equal-precedence-conflict')).toBeInTheDocument()
  })

  it('drops a stale preview when the draft changes', () => {
    const onClearPreview = vi.fn()
    render(
      <PolicyWorkspacePanel workspace={workspace()} onClearPreview={onClearPreview} />,
    )

    fireEvent.change(screen.getByTestId('policy-field-model'), {
      target: { value: 'glm-5.4' },
    })

    expect(onClearPreview).toHaveBeenCalled()
  })
})

describe('PolicyWorkspacePanel — saving', () => {
  it('sends the operator token with the save', async () => {
    const onSave = vi.fn(() => Promise.resolve({ ok: true, revision: 5 }))
    render(
      <PolicyWorkspacePanel workspace={workspace()} preview={WRITABLE_PREVIEW} onSave={onSave} />,
    )
    fillEditor()

    fireEvent.click(screen.getByTestId('policy-save-button'))

    await waitFor(() => expect(onSave.mock.calls[0][1]).toBe('operator-token'))
  })

  it('names the revision that won when a save conflicts', async () => {
    const onSave = vi.fn(() =>
      Promise.resolve({ ok: false, status: 409, code: 'stale-revision', actualRevision: 9 }),
    )
    render(
      <PolicyWorkspacePanel workspace={workspace()} preview={WRITABLE_PREVIEW} onSave={onSave} />,
    )
    fillEditor()

    fireEvent.click(screen.getByTestId('policy-save-button'))

    await waitFor(() =>
      expect(screen.getByTestId('policy-conflict')).toHaveTextContent('Current revision is 9'),
    )
  })

  it('disables a policy through a mutation rather than a delete', async () => {
    const onSave = vi.fn(() => Promise.resolve({ ok: true, revision: 5 }))
    render(<PolicyWorkspacePanel workspace={workspace()} onSave={onSave} />)
    fillEditor()

    fireEvent.click(screen.getByTestId('policy-disable-pin-zai'))

    await waitFor(() =>
      expect(onSave.mock.calls[0][0]).toEqual({
        kind: 'disable',
        expected_revision: 4,
        policy_id: 'pin-zai',
      }),
    )
  })

  it('rolls back to a prior revision as a new revision', async () => {
    const onSave = vi.fn(() => Promise.resolve({ ok: true, revision: 5 }))
    render(<PolicyWorkspacePanel workspace={workspace()} audit={AUDIT} onSave={onSave} />)
    fillEditor()

    fireEvent.click(screen.getByTestId('policy-rollback-1'))

    await waitFor(() =>
      expect(onSave.mock.calls[0][0]).toEqual({
        kind: 'rollback',
        expected_revision: 4,
        target_revision: 1,
      }),
    )
  })
})

describe('PolicyWorkspacePanel — honest states', () => {
  it('says a corrupt snapshot is not an empty one', () => {
    render(<PolicyWorkspacePanel workspace={workspace({ state: 'corrupt' })} />)
    expect(screen.getByTestId('policy-snapshot-corrupt')).toHaveTextContent(
      'NOT "no policies"',
    )
  })

  it('says legacy routing decides when no policy exists', () => {
    render(
      <PolicyWorkspacePanel
        workspace={workspace({ policies: [], editable_policy_ids: [] })}
      />,
    )
    expect(screen.getByTestId('policy-empty')).toHaveTextContent('Legacy routing decides')
  })

  it('round-trips the selected policy through the URL', () => {
    const select = vi.fn()
    render(<PolicyWorkspacePanel workspace={workspace()} select={select} />)

    fireEvent.click(screen.getByTestId('policy-select-pin-zai'))

    expect(select).toHaveBeenCalledWith('routingSelection', 'pin-zai')
  })
})

describe('PolicyWorkspacePanel — the revision it edits against', () => {
  it('saves against the revision the form was opened on, not the newest poll', () => {
    // Reading `workspace.revision` at click time would make expected_revision
    // the WINNER's revision, so the 409 that stops a lost update could never
    // fire from this console (ADR-0140 D3).
    const onPreview = vi.fn()
    const { rerender } = render(
      <PolicyWorkspacePanel workspace={workspace()} onPreview={onPreview} />,
    )
    fillEditor()
    rerender(
      <PolicyWorkspacePanel workspace={workspace({ revision: 9 })} onPreview={onPreview} />,
    )

    fireEvent.click(screen.getByTestId('policy-preview-button'))

    expect(onPreview.mock.calls[0][0].expected_revision).toBe(4)
  })

  it('refuses to save once somebody else’s revision landed under the form', () => {
    const { rerender } = render(
      <PolicyWorkspacePanel workspace={workspace()} preview={WRITABLE_PREVIEW} />,
    )
    fillEditor()
    rerender(
      <PolicyWorkspacePanel
        workspace={workspace({ revision: 9 })}
        preview={WRITABLE_PREVIEW}
      />,
    )

    expect(screen.getByTestId('policy-save-button')).toBeDisabled()
  })

  it('says which revision the form was opened against when it is re-based', () => {
    const { rerender } = render(<PolicyWorkspacePanel workspace={workspace()} />)
    rerender(<PolicyWorkspacePanel workspace={workspace({ revision: 9 })} />)

    expect(screen.getByTestId('policy-rebased')).toHaveTextContent(
      'opened against revision 4; revision 9 is current',
    )
  })

  it('offers a re-base rather than leaving the operator stuck', () => {
    const { rerender } = render(<PolicyWorkspacePanel workspace={workspace()} />)
    rerender(<PolicyWorkspacePanel workspace={workspace({ revision: 9 })} />)

    fireEvent.click(screen.getByTestId('policy-rebase-button'))

    expect(screen.queryByTestId('policy-rebased')).toBeNull()
  })

  it('does not offer a rollback to the revision already in force', () => {
    render(<PolicyWorkspacePanel workspace={workspace({ revision: 1 })} audit={AUDIT} />)
    expect(screen.queryByTestId('policy-rollback-1')).toBeNull()
  })

  it('bounds the rollback controls no matter how long the history is', () => {
    const long = toPolicyAudit({
      verified: true,
      records: Array.from({ length: 40 }, (_, index) => ({
        seq: index,
        recorded_at: '2026-08-22T12:00:00+00:00',
        payload: {
          kind: 'create',
          outcome: 'committed',
          actor: 'travis',
          prior_revision: index,
          new_revision: index + 1,
          diff: {},
        },
      })),
    })
    render(<PolicyWorkspacePanel workspace={workspace()} audit={long} />)

    const targets = screen
      .getAllByTestId(/^policy-rollback-\d+$/)
      .map(node => node.getAttribute('data-testid'))

    expect(targets).toHaveLength(MAX_ROLLBACK_BUTTONS)
  })
})

describe('PolicyWorkspacePanel — what it may not claim', () => {
  it('does not say a repository has no policy before anything is fetched', () => {
    render(<PolicyWorkspacePanel />)
    expect(screen.queryByTestId('policy-empty')).toBeNull()
  })

  it('does not instruct the operator to fix a write gate it has not read', () => {
    render(<PolicyWorkspacePanel />)
    expect(screen.queryByTestId('policy-write-gate')).toBeNull()
  })

  it('names an unreachable policy plane instead of an empty repository', () => {
    render(<PolicyWorkspacePanel sourceState="unavailable" />)
    expect(screen.getByTestId('policy-feed-notice')).toHaveTextContent('NOT "no policy"')
  })

  it('does not claim a revision it has not read', () => {
    render(<PolicyWorkspacePanel />)
    expect(screen.getByTestId('policy-revision')).toHaveTextContent('not read yet')
  })

  it('will not send a disable with no credential attached', () => {
    // A write with no Authorization header comes back 401 "the operator token
    // was not accepted" — about a token that was never sent.
    render(<PolicyWorkspacePanel workspace={workspace()} />)
    expect(screen.getByTestId('policy-disable-pin-zai')).toBeDisabled()
  })

  it('clears a conflict banner once the operator edits the form', () => {
    render(<PolicyWorkspacePanel workspace={workspace()} preview={WRITABLE_PREVIEW} />)
    fillEditor()
    fireEvent.click(screen.getByTestId('policy-save-button'))

    fireEvent.change(screen.getByTestId('policy-field-model'), {
      target: { value: 'glm-5.4' },
    })

    expect(screen.queryByTestId('policy-conflict')).toBeNull()
  })
})

describe('PolicyWorkspacePanel — a feed that stopped answering', () => {
  it('closes the editor rather than writing against a frozen revision', () => {
    render(
      <PolicyWorkspacePanel workspace={workspace()} sourceState="unavailable" />,
    )
    expect(screen.queryByTestId('policy-editor')).toBeNull()
  })

  it('says the state on screen is the last one that loaded', () => {
    render(
      <PolicyWorkspacePanel workspace={workspace()} sourceState="unavailable" />,
    )
    expect(screen.getByTestId('policy-feed-notice')).toHaveTextContent(
      'stopped answering',
    )
  })
})

describe('PolicyWorkspacePanel — rollback is only offered from a chain that verifies', () => {
  it('offers no rollback while the chain is broken', () => {
    // The write plane already refuses with `audit-chain-broken`, and the Audit
    // view already says the targets cannot be trusted.
    const broken = toPolicyAudit({
      verified: false,
      broken_at_seq: 1,
      records: [
        {
          seq: 0,
          payload: { outcome: 'committed', new_revision: 1, actor: 'travis', diff: {} },
        },
      ],
    })
    render(<PolicyWorkspacePanel workspace={workspace()} audit={broken} />)

    expect(screen.queryByTestId('policy-rollback-1')).toBeNull()
  })

  it('offers rollback when the chain verifies', () => {
    render(<PolicyWorkspacePanel workspace={workspace()} audit={AUDIT} />)
    expect(screen.getByTestId('policy-rollback-1')).toBeInTheDocument()
  })
})

describe('PolicyWorkspacePanel — the pin follows the repository', () => {
  it('re-pins when the workspace switches to another repository', () => {
    const { rerender } = render(<PolicyWorkspacePanel workspace={workspace()} />)
    rerender(
      <PolicyWorkspacePanel
        workspace={workspace({ repo: 'acme/other', revision: 2 })}
      />,
    )

    expect(screen.queryByTestId('policy-rebased')).toBeNull()
  })

  it('keeps the pin when a save reports no revision', () => {
    // Dropping it would silently restore the unpinned behaviour, where
    // expected_revision follows the live poll and the 409 can never fire.
    const onSave = vi.fn(() => Promise.resolve({ ok: true }))
    const onPreview = vi.fn()
    const { rerender } = render(
      <PolicyWorkspacePanel
        workspace={workspace()}
        preview={WRITABLE_PREVIEW}
        onSave={onSave}
        onPreview={onPreview}
      />,
    )
    fillEditor()
    fireEvent.click(screen.getByTestId('policy-save-button'))
    rerender(
      <PolicyWorkspacePanel
        workspace={workspace({ revision: 9 })}
        preview={WRITABLE_PREVIEW}
        onSave={onSave}
        onPreview={onPreview}
      />,
    )

    expect(screen.getByTestId('policy-rebased')).toBeInTheDocument()
  })
})

describe('PolicyWorkspacePanel — aggregate', () => {
  it('declares itself read-only', () => {
    render(
      <PolicyWorkspacePanel
        workspace={toPolicyWorkspace({ scope: 'aggregate', repos: [] })}
        sourceState="aggregate"
      />,
    )
    expect(screen.getByTestId('policy-aggregate-readonly')).toHaveTextContent(
      'read-only',
    )
  })

  it('renders an empty roster as an explicit statement', () => {
    render(
      <PolicyWorkspacePanel
        workspace={toPolicyWorkspace({ scope: 'aggregate', repos: [] })}
        sourceState="aggregate"
      />,
    )
    expect(screen.getByTestId('policy-aggregate-empty')).toBeInTheDocument()
  })
})

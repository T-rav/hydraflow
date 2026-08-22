/**
 * usePolicyWorkspace — the policy feed and the write path (#11538, ADR-0140).
 *
 * The load-bearing test here is the STALE-RESPONSE one. An AbortController
 * cancels a cycle on unmount but does nothing about two live cycles finishing
 * out of order, and a slow poll landing after a save's refresh would put the
 * pre-save revision back on screen — inviting the operator to save against it,
 * which is the lost update optimistic concurrency exists to prevent.
 */

import { describe, it, expect, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import {
  POLICY_AUDIT_ENDPOINT,
  POLICY_EFFECTIVE_ENDPOINT,
  POLICY_ENDPOINT,
  POLICY_MUTATIONS_ENDPOINT,
  POLICY_PREVIEW_ENDPOINT,
  POLICY_SOURCE_AGGREGATE,
  POLICY_SOURCE_AVAILABLE,
  POLICY_SOURCE_UNAVAILABLE,
  REPO_ALL,
  usePolicyWorkspace,
} from '../usePolicyWorkspace'

// Every test that wants the per-repository DETAIL feed must name a repository:
// no selection is the aggregate view, which is read-only by construction and
// deliberately does not call the per-repo routes at all.
const REPO = 'acme/hydraflow'
const SCOPED_POLICY_ENDPOINT = `${POLICY_ENDPOINT}?repo=${encodeURIComponent(REPO)}`

function workspacePayload(revision) {
  return {
    scope: 'repo',
    repo: 'acme/hydraflow',
    state: 'ok',
    revision,
    content_hash: `sha256:r${revision}`,
    policies: [],
    editable_policy_ids: [],
    issues: [],
    write_gate: 'enabled',
    editable: true,
  }
}

const MATRIX_PAYLOAD = {
  repo: 'acme/hydraflow',
  policy_revision: 1,
  snapshot_hash: 'sha256:r1',
  snapshot_state: 'ok',
  cells: [],
}

const AUDIT_PAYLOAD = { records: [], verified: true, truncated: false }

/** A fetcher that answers every read from the revision it is told to serve. */
function readFetcher(revision = 1) {
  return vi.fn(url => {
    if (url.startsWith(POLICY_EFFECTIVE_ENDPOINT)) {
      return Promise.resolve({ ok: true, status: 200, data: MATRIX_PAYLOAD })
    }
    if (url.startsWith(POLICY_AUDIT_ENDPOINT)) {
      return Promise.resolve({ ok: true, status: 200, data: AUDIT_PAYLOAD })
    }
    return Promise.resolve({ ok: true, status: 200, data: workspacePayload(revision) })
  })
}

describe('usePolicyWorkspace', () => {
  it('loads the workspace, the matrix, and the history in one cycle', async () => {
    const fetcher = readFetcher(3)
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() => expect(result.current.workspace.loaded).toBe(true))
    expect([
      result.current.workspace.revision,
      result.current.matrix.loaded,
      result.current.audit.loaded,
    ]).toEqual([3, true, true])
  })

  it('does not fetch when no fetcher is supplied', () => {
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher: null }))
    expect(result.current.workspace.loaded).toBe(false)
  })

  it('does not poll at all while the routing mode is closed', async () => {
    // The audit read walks and hash-verifies a chain that is never pruned, so a
    // console session that never opens Routing must not pay for it every 30 s.
    const fetcher = readFetcher(1)
    renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO, enabled: false }))
    await act(async () => {})
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('reads only the aggregate summary when no repository is selected', async () => {
    // Aggregate is read-only by construction: the per-repository detail routes
    // refuse `__all__` with a 400, so they are not called.
    const fetcher = readFetcher(1)
    renderHook(() => usePolicyWorkspace({ fetcher }))
    await waitFor(() => expect(fetcher).toHaveBeenCalled())
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      `${POLICY_ENDPOINT}?repo=${encodeURIComponent(REPO_ALL)}`,
    ])
  })

  it('reports an unavailable source rather than an empty repository', async () => {
    const fetcher = vi.fn(() => Promise.resolve({ ok: false, status: 500, data: null }))
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() =>
      expect(result.current.sourceState).toBe(POLICY_SOURCE_UNAVAILABLE),
    )
    expect(result.current.workspace.loaded).toBe(false)
  })

  it('reports an unavailable source when the cycle throws', async () => {
    const fetcher = vi.fn(() => Promise.reject(new Error('gone')))
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() =>
      expect(result.current.sourceState).toBe(POLICY_SOURCE_UNAVAILABLE),
    )
  })

  it('reports an available source once every slice answered', async () => {
    const fetcher = readFetcher(1)
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() => expect(result.current.sourceState).toBe(POLICY_SOURCE_AVAILABLE))
  })

  it('clears the previous repository’s state the moment the selection changes', async () => {
    // Otherwise the panel renders repo A's policies under repo B's header for a
    // whole round trip — and a save would carry A's revision.
    const fetcher = readFetcher(3)
    const { result, rerender } = renderHook(props => usePolicyWorkspace(props), {
      initialProps: { fetcher, repo: REPO },
    })
    await waitFor(() => expect(result.current.workspace.revision).toBe(3))
    rerender({ fetcher: vi.fn(() => new Promise(() => {})), repo: 'acme/other' })
    expect(result.current.workspace.loaded).toBe(false)
  })

  it('does not let a routine poll discard an in-flight preview', async () => {
    // One shared counter would drop the preview here, leaving the Preview
    // button looking inert with no error anywhere.
    const gates = []
    const fetcher = vi.fn(url => {
      if (url.startsWith(POLICY_PREVIEW_ENDPOINT)) {
        return new Promise(resolve => {
          gates.push(resolve)
        })
      }
      return Promise.resolve({ ok: true, status: 200, data: workspacePayload(1) })
    })
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() => expect(result.current.workspace.loaded).toBe(true))

    let pending
    await act(async () => {
      pending = result.current.requestPreview({ kind: 'create', expected_revision: 1 })
      await waitFor(() => expect(gates.length).toBe(1))
      await result.current.refresh()
      gates[0]({ ok: true, status: 200, data: { writable: true, cells: [], diff: {} } })
      await pending
    })

    expect(result.current.preview).not.toBeNull()
  })

  it('keeps the last-known workspace when a cycle throws', async () => {
    const fetcher = readFetcher(2)
    const { result, rerender } = renderHook(props => usePolicyWorkspace(props), {
      initialProps: { fetcher, repo: REPO },
    })
    await waitFor(() => expect(result.current.workspace.revision).toBe(2))
    rerender({ fetcher: vi.fn(() => Promise.reject(new Error('gone'))), repo: REPO })
    await act(async () => {})
    expect(result.current.workspace.revision).toBe(2)
  })

  it('rejects a stale response that lands after a newer one', async () => {
    // Two live cycles, resolved out of order on purpose: the FIRST cycle's
    // (older, revision 1) payload settles last and must not overwrite the
    // second cycle's revision 2.
    const gates = []
    const fetcher = vi.fn(url => {
      // Exact match: the effective and audit endpoints are PREFIXED by the
      // workspace one, so `startsWith` would gate three calls per cycle.
      if (url === SCOPED_POLICY_ENDPOINT) {
        return new Promise(resolve => {
          gates.push(resolve)
        })
      }
      return Promise.resolve({ ok: true, status: 200, data: MATRIX_PAYLOAD })
    })
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() => expect(gates.length).toBe(1))
    await act(async () => {
      result.current.refresh()
    })
    await waitFor(() => expect(gates.length).toBe(2))

    await act(async () => {
      gates[1]({ ok: true, status: 200, data: workspacePayload(2) })
      gates[0]({ ok: true, status: 200, data: workspacePayload(1) })
    })

    expect(result.current.workspace.revision).toBe(2)
  })

  it('returns the winning revision when a save conflicts', async () => {
    const fetcher = vi.fn(url => {
      if (url.startsWith(POLICY_MUTATIONS_ENDPOINT)) {
        return Promise.resolve({
          ok: false,
          status: 409,
          data: { code: 'stale-revision', actual_revision: 7 },
        })
      }
      if (url.startsWith(POLICY_EFFECTIVE_ENDPOINT)) {
        return Promise.resolve({ ok: true, status: 200, data: MATRIX_PAYLOAD })
      }
      if (url.startsWith(POLICY_AUDIT_ENDPOINT)) {
        return Promise.resolve({ ok: true, status: 200, data: AUDIT_PAYLOAD })
      }
      return Promise.resolve({ ok: true, status: 200, data: workspacePayload(7) })
    })
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() => expect(result.current.workspace.loaded).toBe(true))

    let outcome
    await act(async () => {
      outcome = await result.current.save({ kind: 'create', expected_revision: 1 }, 'tok')
    })

    expect([outcome.ok, outcome.status, outcome.actualRevision]).toEqual([false, 409, 7])
  })

  it('sends the operator token only on the write', async () => {
    const fetcher = readFetcher(1)
    fetcher.mockImplementation(url =>
      url.startsWith(POLICY_MUTATIONS_ENDPOINT)
        ? Promise.resolve({ ok: true, status: 200, data: { revision: 2 } })
        : Promise.resolve({ ok: true, status: 200, data: workspacePayload(2) }),
    )
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() => expect(result.current.workspace.loaded).toBe(true))

    await act(async () => {
      await result.current.save({ kind: 'create', expected_revision: 1 }, 'operator-token')
    })

    const tokenCalls = fetcher.mock.calls.filter(([, options]) => options?.token)
    expect(tokenCalls.map(([url]) => url.startsWith(POLICY_MUTATIONS_ENDPOINT))).toEqual([true])
  })

  it('clears the preview once a save commits', async () => {
    const fetcher = vi.fn(url => {
      if (url.startsWith(POLICY_PREVIEW_ENDPOINT)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          data: { writable: true, cells: [], diff: {} },
        })
      }
      if (url.startsWith(POLICY_MUTATIONS_ENDPOINT)) {
        return Promise.resolve({ ok: true, status: 200, data: { revision: 2 } })
      }
      if (url.startsWith(POLICY_EFFECTIVE_ENDPOINT)) {
        return Promise.resolve({ ok: true, status: 200, data: MATRIX_PAYLOAD })
      }
      if (url.startsWith(POLICY_AUDIT_ENDPOINT)) {
        return Promise.resolve({ ok: true, status: 200, data: AUDIT_PAYLOAD })
      }
      return Promise.resolve({ ok: true, status: 200, data: workspacePayload(2) })
    })
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() => expect(result.current.workspace.loaded).toBe(true))
    await act(async () => {
      await result.current.requestPreview({ kind: 'create', expected_revision: 1 })
    })

    await act(async () => {
      await result.current.save({ kind: 'create', expected_revision: 1 }, 'tok')
    })

    expect(result.current.preview).toBeNull()
  })

  it('scopes every request to the selected repository', async () => {
    const fetcher = readFetcher(1)
    renderHook(() => usePolicyWorkspace({ fetcher, repo: 'acme/other' }))
    await waitFor(() => expect(fetcher).toHaveBeenCalled())
    expect(fetcher.mock.calls.every(([url]) => url.includes('repo=acme%2Fother'))).toBe(true)
  })
})

describe('usePolicyWorkspace — honesty of the source state', () => {
  it('does not load a workspace from an error body', async () => {
    // A FastAPI refusal is `{"detail": ...}`, which reduces to a VM that would
    // otherwise render "No policy has been written for this repository".
    const fetcher = vi.fn(() =>
      Promise.resolve({ ok: false, status: 500, data: { detail: 'boom' } }),
    )
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() =>
      expect(result.current.sourceState).toBe(POLICY_SOURCE_UNAVAILABLE),
    )
    expect(result.current.workspace.loaded).toBe(false)
  })

  it('reports aggregate as its own state, not as available', async () => {
    // `available` beside an unfetched matrix and history is a self-contradictory
    // pair those two panels resolve as "still loading", forever.
    const fetcher = readFetcher(1)
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher }))
    await waitFor(() => expect(result.current.workspace.loaded).toBe(true))
    expect(result.current.sourceState).toBe(POLICY_SOURCE_AGGREGATE)
  })

  it('retires an in-flight preview when the draft changes', async () => {
    // Nulling `preview` alone lets the older preview land afterwards and
    // re-enable Save for a draft that was never previewed.
    const gates = []
    const fetcher = vi.fn(url => {
      if (url.startsWith(POLICY_PREVIEW_ENDPOINT)) {
        return new Promise(resolve => {
          gates.push(resolve)
        })
      }
      return Promise.resolve({ ok: true, status: 200, data: workspacePayload(1) })
    })
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() => expect(result.current.workspace.loaded).toBe(true))

    await act(async () => {
      const pending = result.current.requestPreview({ kind: 'create', expected_revision: 1 })
      await waitFor(() => expect(gates.length).toBe(1))
      result.current.clearPreview()
      gates[0]({ ok: true, status: 200, data: { writable: true, cells: [], diff: {} } })
      await pending
    })

    expect(result.current.preview).toBeNull()
  })
})

describe('usePolicyWorkspace — a committed save retires its preview too', () => {
  it('does not let an in-flight preview re-enable Save after a commit', async () => {
    // The same defect `clearPreview` fixes, on the sibling path: the preview
    // describes the PRE-save revision, and Save keys off `preview.writable`.
    const gates = []
    const fetcher = vi.fn(url => {
      if (url.startsWith(POLICY_PREVIEW_ENDPOINT)) {
        return new Promise(resolve => {
          gates.push(resolve)
        })
      }
      if (url.startsWith(POLICY_MUTATIONS_ENDPOINT)) {
        return Promise.resolve({ ok: true, status: 200, data: { revision: 2 } })
      }
      return Promise.resolve({ ok: true, status: 200, data: workspacePayload(2) })
    })
    const { result } = renderHook(() => usePolicyWorkspace({ fetcher, repo: REPO }))
    await waitFor(() => expect(result.current.workspace.loaded).toBe(true))

    await act(async () => {
      const pending = result.current.requestPreview({ kind: 'create', expected_revision: 1 })
      await waitFor(() => expect(gates.length).toBe(1))
      await result.current.save({ kind: 'create', expected_revision: 1 }, 'tok')
      gates[0]({ ok: true, status: 200, data: { writable: true, cells: [], diff: {} } })
      await pending
    })

    expect(result.current.preview).toBeNull()
  })
})

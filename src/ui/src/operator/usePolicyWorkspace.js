/**
 * usePolicyWorkspace — the operator console's routing-policy feed and write path
 * (issue #11538, ADR-0140).
 *
 * It follows `useGatewayRouting`'s shape (one pinned `setInterval`, one
 * `AbortController` per cycle, a last-known VM kept on failure) and adds the
 * things a WRITE surface needs that a read-only poll does not:
 *
 * **Two monotonic sequence guards, not one.** An `AbortController` cancels a
 * cycle on unmount, but it does nothing about two *live* cycles finishing out of
 * order — a slow poll landing after a save's refresh would put the pre-save
 * revision back on screen and invite the operator to save against it, which is
 * exactly the lost update optimistic concurrency exists to prevent. The poll and
 * the preview take tickets from SEPARATE counters, because they write disjoint
 * state: one counter would let a routine 30-second poll silently discard an
 * in-flight preview and leave the Preview button looking inert.
 *
 * **An honest source state.** A cycle that threw, or any response that was not
 * 2xx, sets `sourceState = 'unavailable'`. Without it a dead endpoint is
 * indistinguishable from "this repository has no policy", which is precisely the
 * false-coherent state ADR-0140 exists to prevent — and it would be asserted by
 * a panel whose whole job is trustworthiness.
 *
 * **A credential that is never stored.** The operator token is passed in per
 * save and forwarded straight to the request. It is never written to state, to
 * `localStorage`, or into any view model — a token in browser storage is a token
 * in every later page view's blast radius.
 *
 * The fetcher deliberately does NOT throw on a non-2xx response: a 409 carries
 * the revision that won, and a 422 carries every validation issue. Those bodies
 * are the answer, not an error to swallow.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { GATEWAY_ROUTING_POLL_MS } from '../constants'
import {
  EMPTY_EFFECTIVE_MATRIX_VM,
  EMPTY_POLICY_AUDIT_VM,
  EMPTY_POLICY_WORKSPACE_VM,
  toEffectiveMatrix,
  toPolicyAudit,
  toPolicyPreview,
  toPolicyWorkspace,
} from './model/policyWorkspace'

export const POLICY_ENDPOINT = '/api/gateway/policies'
export const POLICY_EFFECTIVE_ENDPOINT = '/api/gateway/policies/effective'
export const POLICY_PREVIEW_ENDPOINT = '/api/gateway/policies/preview'
export const POLICY_MUTATIONS_ENDPOINT = '/api/gateway/policies/mutations'
export const POLICY_AUDIT_ENDPOINT = '/api/gateway/policies/audit'

/** The cross-repo sentinel the dashboard uses; policy reads it as read-only. */
export const REPO_ALL = '__all__'

export const POLICY_SOURCE_LOADING = 'loading'
export const POLICY_SOURCE_AVAILABLE = 'available'
export const POLICY_SOURCE_UNAVAILABLE = 'unavailable'
/** Aggregate: the summary IS current, and the per-repo detail was never asked for. */
export const POLICY_SOURCE_AGGREGATE = 'aggregate'

/**
 * Default fetcher. Returns `{ok, status, data}` and throws only on a transport
 * failure, because a refusal's BODY is the answer this surface needs.
 */
export async function defaultPolicyFetcher(
  url,
  { signal, method = 'GET', body = null, token = null } = {},
) {
  const headers = {}
  if (body != null) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(url, {
    method,
    signal,
    headers,
    body: body == null ? undefined : JSON.stringify(body),
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  return { ok: res.ok, status: res.status, data }
}

function withRepo(endpoint, repo) {
  return repo ? `${endpoint}?repo=${encodeURIComponent(repo)}` : endpoint
}

/**
 * @param {{
 *   repo?: string|null, enabled?: boolean, fetcher?: Function, intervalMs?: number,
 * }} [options]
 */
export function usePolicyWorkspace({
  repo = null,
  enabled = true,
  fetcher = defaultPolicyFetcher,
  intervalMs = GATEWAY_ROUTING_POLL_MS,
} = {}) {
  const [workspace, setWorkspace] = useState(EMPTY_POLICY_WORKSPACE_VM)
  const [matrix, setMatrix] = useState(EMPTY_EFFECTIVE_MATRIX_VM)
  const [audit, setAudit] = useState(EMPTY_POLICY_AUDIT_VM)
  const [sourceState, setSourceState] = useState(POLICY_SOURCE_LOADING)
  const [preview, setPreview] = useState(null)
  const [rejection, setRejection] = useState(null)

  // Two counters per channel, not one shared pair: `issued` hands out tickets,
  // `applied` remembers the newest ticket that has been SETTLED OR RETIRED, and
  // a response lands only if it is strictly newer. Strictly, because
  // `clearPreview` retires the in-flight ticket by setting applied = issued —
  // a `>=` test would let that same request land anyway and re-enable Save for
  // a draft the operator has already changed. The poll and the preview keep
  // their own pair so neither can invalidate the other's answer.
  const pollIssued = useRef(0)
  const pollApplied = useRef(0)
  const previewIssued = useRef(0)
  const previewApplied = useRef(0)

  // A repository selection is the one input that invalidates every slice at
  // once. Without the reset the panel renders the previous repo's policies
  // under the new repo's header for a whole round trip — and `mutation()`
  // would build a body from a revision that belongs to a different repository.
  useEffect(() => {
    setWorkspace(EMPTY_POLICY_WORKSPACE_VM)
    setMatrix(EMPTY_EFFECTIVE_MATRIX_VM)
    setAudit(EMPTY_POLICY_AUDIT_VM)
    setPreview(null)
    setRejection(null)
    setSourceState(POLICY_SOURCE_LOADING)
  }, [repo])

  const load = useCallback(
    async signal => {
      const ticket = ++pollIssued.current
      // No repository selected is the AGGREGATE view, and aggregate is
      // read-only by construction: the summary read answers it and the
      // per-repository detail routes refuse it, so they are not called at all.
      const aggregate = !repo
      const scope = repo || REPO_ALL
      let responses
      try {
        responses = await Promise.all([
          fetcher(withRepo(POLICY_ENDPOINT, scope), { signal }),
          aggregate
            ? null
            : fetcher(withRepo(POLICY_EFFECTIVE_ENDPOINT, scope), { signal }),
          aggregate
            ? null
            : fetcher(withRepo(POLICY_AUDIT_ENDPOINT, scope), { signal }),
        ])
      } catch {
        if (!signal?.aborted && ticket > pollApplied.current) {
          pollApplied.current = ticket
          setSourceState(POLICY_SOURCE_UNAVAILABLE)
        }
        return
      }
      if (signal?.aborted || ticket <= pollApplied.current) return
      pollApplied.current = ticket
      const [policies, effective, history] = responses
      if (policies?.ok) setWorkspace(toPolicyWorkspace(policies.data))
      if (effective?.ok) setMatrix(toEffectiveMatrix(effective.data))
      if (history?.ok) setAudit(toPolicyAudit(history.data))
      const answered = responses.filter(response => response !== null)
      if (!answered.every(response => response?.ok)) {
        setSourceState(POLICY_SOURCE_UNAVAILABLE)
        return
      }
      // Aggregate gets its OWN state. Reporting `available` while the matrix and
      // the history were never fetched leaves those two panels claiming a read
      // that is not happening — a self-contradictory pair.
      setSourceState(aggregate ? POLICY_SOURCE_AGGREGATE : POLICY_SOURCE_AVAILABLE)
    },
    [fetcher, repo],
  )

  useEffect(() => {
    if (!enabled || typeof fetcher !== 'function') return undefined
    const controller = new AbortController()
    load(controller.signal)
    const timer = setInterval(() => load(controller.signal), intervalMs)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [enabled, fetcher, intervalMs, load])

  const requestPreview = useCallback(
    async mutation => {
      const ticket = ++previewIssued.current
      let response
      try {
        response = await fetcher(
          withRepo(POLICY_PREVIEW_ENDPOINT, repo || REPO_ALL),
          { method: 'POST', body: mutation },
        )
      } catch {
        if (ticket > previewApplied.current) {
          previewApplied.current = ticket
          setRejection('storage-unavailable')
        }
        return null
      }
      // A preview that landed after a NEWER preview — or after the draft it
      // described was edited — would show the operator the consequences of an
      // edit they have already moved on from.
      if (ticket <= previewApplied.current) return null
      previewApplied.current = ticket
      const vm = response?.ok ? toPolicyPreview(response.data) : null
      setPreview(vm)
      setRejection(response?.ok ? null : response?.data?.code || 'validation-failed')
      return vm
    },
    [fetcher, repo],
  )

  const save = useCallback(
    async (mutation, token) => {
      let response
      try {
        response = await fetcher(
          withRepo(POLICY_MUTATIONS_ENDPOINT, repo || REPO_ALL),
          { method: 'POST', body: mutation, token },
        )
      } catch {
        setRejection('storage-unavailable')
        return { ok: false, status: 0, code: 'storage-unavailable' }
      }
      if (!response?.ok) {
        setRejection(response?.data?.code || 'validation-failed')
        // Reload even on a refusal: a 409 means somebody else's revision won,
        // and the form has to be able to show what it is now.
        await load()
        return {
          ok: false,
          status: response?.status || 0,
          code: response?.data?.code || 'validation-failed',
          actualRevision: response?.data?.actual_revision ?? null,
          issues: response?.data?.issues || [],
        }
      }
      setRejection(null)
      // Retire the ticket as well as the state, for the same reason
      // `clearPreview` does: an in-flight preview landing after the save would
      // repopulate `preview` with a view of the PRE-save revision and re-enable
      // the Save button for an edit that has already been written.
      previewApplied.current = previewIssued.current
      setPreview(null)
      await load()
      return { ok: true, status: response.status, revision: response.data?.revision }
    },
    [fetcher, load, repo],
  )

  const clearPreview = useCallback(() => {
    // Retire the ticket as well as the state. Nulling `preview` alone leaves an
    // in-flight preview free to land afterwards and re-enable Save — for a
    // draft the operator has already changed, which is exactly the
    // "previewed before it is written" contract the button claims.
    previewApplied.current = previewIssued.current
    setPreview(null)
    setRejection(null)
  }, [])

  return {
    workspace,
    matrix,
    audit,
    sourceState,
    preview,
    rejection,
    requestPreview,
    save,
    clearPreview,
    refresh: load,
  }
}

export default usePolicyWorkspace

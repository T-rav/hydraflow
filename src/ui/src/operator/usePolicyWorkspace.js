/**
 * usePolicyWorkspace — the operator console's routing-policy feed and write path
 * (issue #11538, ADR-0140).
 *
 * It follows `useGatewayRouting`'s shape (one pinned `setInterval`, one
 * `AbortController` per cycle, a last-known VM kept on failure) and adds the two
 * things a WRITE surface needs that a read-only poll does not:
 *
 * **A monotonic sequence guard.** An `AbortController` cancels a cycle on
 * unmount, but it does nothing about two *live* cycles finishing out of order —
 * a slow poll landing after a fast save's refresh would put the pre-save
 * revision back on screen and invite the operator to save against it, which is
 * exactly the lost update optimistic concurrency exists to prevent. Every load
 * takes a ticket; a response whose ticket is older than the newest one already
 * applied is dropped rather than rendered.
 *
 * **A credential that is never stored.** The operator token is passed in per
 * save and forwarded straight to the request. It is never written to state, to
 * `localStorage`, or into any view model — a token in browser storage is a
 * token in every later page view's blast radius.
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
 * @param {{ repo?: string|null, fetcher?: Function, intervalMs?: number }} [options]
 */
export function usePolicyWorkspace({
  repo = null,
  fetcher = defaultPolicyFetcher,
  intervalMs = GATEWAY_ROUTING_POLL_MS,
} = {}) {
  const [workspace, setWorkspace] = useState(EMPTY_POLICY_WORKSPACE_VM)
  const [matrix, setMatrix] = useState(EMPTY_EFFECTIVE_MATRIX_VM)
  const [audit, setAudit] = useState(EMPTY_POLICY_AUDIT_VM)
  const [preview, setPreview] = useState(null)
  const [rejection, setRejection] = useState(null)

  // Two counters, not one: `issued` hands out tickets, `applied` remembers the
  // newest one that reached state. A response only lands if it is newer.
  const issuedRef = useRef(0)
  const appliedRef = useRef(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const load = useCallback(
    async signal => {
      const ticket = ++issuedRef.current
      let responses
      try {
        responses = await Promise.all([
          fetcherRef.current(withRepo(POLICY_ENDPOINT, repo), { signal }),
          fetcherRef.current(withRepo(POLICY_EFFECTIVE_ENDPOINT, repo), { signal }),
          fetcherRef.current(withRepo(POLICY_AUDIT_ENDPOINT, repo), { signal }),
        ])
      } catch {
        return
      }
      if (signal?.aborted || ticket < appliedRef.current) return
      appliedRef.current = ticket
      const [policies, effective, history] = responses
      if (policies?.ok) setWorkspace(toPolicyWorkspace(policies.data))
      if (effective?.ok) setMatrix(toEffectiveMatrix(effective.data))
      if (history?.ok) setAudit(toPolicyAudit(history.data))
    },
    [repo],
  )

  useEffect(() => {
    if (typeof fetcher !== 'function') return undefined
    const controller = new AbortController()
    load(controller.signal)
    const timer = setInterval(() => load(controller.signal), intervalMs)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [fetcher, intervalMs, load])

  const requestPreview = useCallback(
    async mutation => {
      const ticket = ++issuedRef.current
      let response
      try {
        response = await fetcherRef.current(withRepo(POLICY_PREVIEW_ENDPOINT, repo), {
          method: 'POST',
          body: mutation,
        })
      } catch {
        return null
      }
      // A preview that landed after a newer one would show the operator the
      // consequences of an edit they have already moved on from.
      if (ticket < appliedRef.current) return null
      appliedRef.current = ticket
      const vm = response?.ok ? toPolicyPreview(response.data) : null
      setPreview(vm)
      setRejection(response?.ok ? null : response?.data?.code || 'preview-failed')
      return vm
    },
    [repo],
  )

  const save = useCallback(
    async (mutation, token) => {
      let response
      try {
        response = await fetcherRef.current(withRepo(POLICY_MUTATIONS_ENDPOINT, repo), {
          method: 'POST',
          body: mutation,
          token,
        })
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
      setPreview(null)
      await load()
      return { ok: true, status: response.status, revision: response.data?.revision }
    },
    [load, repo],
  )

  const clearPreview = useCallback(() => {
    setPreview(null)
    setRejection(null)
  }, [])

  return {
    workspace,
    matrix,
    audit,
    preview,
    rejection,
    requestPreview,
    save,
    clearPreview,
    refresh: load,
  }
}

export default usePolicyWorkspace

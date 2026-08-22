/**
 * Gateway routing view models (issue #11534, ADR-0138). Pure — no fetch, no React.
 *
 * Two reducers over the `/api/gateway/...` envelopes:
 *
 *   toGatewayAccounts({available, source_state, data})  -> the Accounts view
 *   toGatewayLiveRoutes(activeEnvelope, recentEnvelope) -> the Live view
 *
 * Both are deliberately HONEST rather than tidy:
 *
 *   - the envelope's `available` / `source_state` survive into the VM, so a
 *     gateway that is unreachable or has no control token renders as an
 *     explicit degraded state and NEVER as "no accounts" / "no traffic";
 *   - account facts stay independent — `configured`, administrative state,
 *     `leased`, `inFlight`, `observed`, and `health` are separate fields with
 *     separate tones. "Key configured" never becomes "healthy", and "healthy"
 *     never becomes "currently routing";
 *   - `unverified` is a neutral tone, never a success tone: an account with no
 *     evidence has not been proven good.
 *
 * Every numeric field is coerced through `num()` (NaN/Infinity/non-numeric -> 0),
 * mirroring model/cost.js and model/trustFleet.js — a malformed row never
 * produces NaN or throws. A missing / malformed payload yields the frozen EMPTY
 * view model.
 */

const UNAVAILABLE_STATE = 'not-configured'

function num(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function str(value) {
  return value == null ? '' : String(value)
}

function orNull(value) {
  return value == null || value === '' ? null : String(value)
}

/** Compact age label: seconds under a minute, then minutes, then hours. */
export function formatAge(seconds) {
  const total = Math.max(0, Math.floor(num(seconds)))
  if (total < 60) return `${total}s`
  if (total < 3600) return `${Math.floor(total / 60)}m`
  const hours = Math.floor(total / 3600)
  return `${hours}h ${Math.floor((total % 3600) / 60)}m`
}

/** Latency label in ms under a second, else seconds with one decimal. */
export function formatLatency(latencyMs) {
  const ms = Math.max(0, num(latencyMs))
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

/** Cost label. An unknown price is "—", never a misleading $0.00. */
export function formatCost(costUsd, costUnknown) {
  if (costUnknown || costUsd == null) return '—'
  return `$${num(costUsd).toFixed(4)}`
}

/** Health tone. `unverified` is neutral: no evidence is not a pass. */
export function healthTone(health) {
  if (health === 'healthy') return 'success'
  if (health === 'degraded') return 'danger'
  return 'neutral'
}

/** Terminal-status tone. A client abort is not an upstream failure. */
export function statusTone(status) {
  if (status === 'completed') return 'success'
  if (status === 'client-aborted') return 'warning'
  return 'danger'
}

export const EMPTY_GATEWAY_ACCOUNTS_VM = Object.freeze({
  available: false,
  sourceState: UNAVAILABLE_STATE,
  asOf: null,
  evidenceSince: null,
  windowSeconds: 0,
  evidenceTruncated: false,
  summary: Object.freeze({ configured: 0, enabled: 0, leased: 0, inFlight: 0 }),
  accounts: Object.freeze([]),
})

export const EMPTY_GATEWAY_LIVE_VM = Object.freeze({
  available: false,
  sourceState: UNAVAILABLE_STATE,
  evidenceSince: null,
  truncated: false,
  leases: Object.freeze([]),
  inFlight: Object.freeze([]),
  recent: Object.freeze([]),
})

function envelopeState(raw) {
  const data = raw?.data && typeof raw.data === 'object' ? raw.data : null
  const declared = raw?.available === true
  // An envelope that claims availability but carries no payload is malformed,
  // not available — reporting it as `available` would let an empty view pass
  // for a real one, which is the exact failure this whole model guards against.
  const malformed = declared && data === null
  return {
    available: declared && data !== null,
    sourceState: malformed ? 'invalid' : str(raw?.source_state) || UNAVAILABLE_STATE,
    data,
  }
}

function toAccountRow(raw) {
  const health = str(raw?.health) || 'unverified'
  return {
    accountId: str(raw?.account_id),
    displayName: str(raw?.display_name),
    providerBinding: str(raw?.provider_binding),
    baseOrigin: orNull(raw?.base_origin),
    authStyle: orNull(raw?.auth_style),
    credentialEnv: orNull(raw?.credential_env),
    configured: raw?.configured === true,
    administrativeState: str(raw?.administrative_state) || 'enabled',
    leased: raw?.leased === true,
    leaseCount: num(raw?.lease_count),
    inFlight: raw?.in_flight === true,
    inFlightCount: num(raw?.in_flight_count),
    observed: raw?.observed === true,
    observedRequestCount: num(raw?.observed_request_count),
    observedAbortedCount: num(raw?.observed_aborted_count),
    observedErrorCount: num(raw?.observed_error_count),
    lastObservedAt: orNull(raw?.last_observed_at),
    health,
    healthReason: orNull(raw?.health_reason),
    healthTone: healthTone(health),
  }
}

/**
 * @param {unknown} raw The `/api/gateway/accounts` envelope.
 * @returns {typeof EMPTY_GATEWAY_ACCOUNTS_VM}
 */
export function toGatewayAccounts(raw) {
  const { available, sourceState, data } = envelopeState(raw)
  if (!available) {
    return { ...EMPTY_GATEWAY_ACCOUNTS_VM, sourceState }
  }
  const rows = Array.isArray(data.accounts) ? data.accounts : []
  const summary = data.summary && typeof data.summary === 'object' ? data.summary : {}
  return {
    available: true,
    sourceState,
    asOf: orNull(data.as_of),
    evidenceSince: orNull(data.evidence_since),
    windowSeconds: num(data.window_seconds),
    evidenceTruncated: data.evidence_truncated === true,
    summary: {
      configured: num(summary.configured),
      enabled: num(summary.enabled),
      leased: num(summary.leased),
      inFlight: num(summary.in_flight),
    },
    accounts: rows.map(toAccountRow),
  }
}

function routeIdentity(raw) {
  return {
    accountId: str(raw?.account_id),
    providerBinding: str(raw?.provider_binding),
    repoSlug: str(raw?.repo_slug),
    role: orNull(raw?.worker_role) || str(raw?.principal_id),
    canonicalRole: orNull(raw?.worker_role),
    issueNumber: raw?.issue_number == null ? null : num(raw.issue_number),
  }
}

function toLeaseRow(raw) {
  return {
    ...routeIdentity(raw),
    keyId: str(raw?.key_id),
    ageLabel: formatAge(raw?.age_seconds),
    expiresAt: orNull(raw?.expires_at),
  }
}

function toInFlightRow(raw) {
  return {
    ...routeIdentity(raw),
    requestId: str(raw?.request_id),
    path: orNull(raw?.path),
    ageLabel: formatAge(raw?.age_seconds),
  }
}

function toRecentRow(raw) {
  const status = str(raw?.status) || 'completed'
  return {
    ...routeIdentity(raw),
    requestId: str(raw?.request_id),
    modelRequested: orNull(raw?.model_requested),
    modelServed: orNull(raw?.model_served),
    status,
    statusTone: statusTone(status),
    statusCode: num(raw?.status_code),
    latencyLabel: formatLatency(raw?.latency_ms),
    costLabel: formatCost(raw?.cost_usd, raw?.cost_unknown === true),
    startedAt: orNull(raw?.started_at),
  }
}

/**
 * @param {unknown} activeRaw The `/api/gateway/routes/active` envelope.
 * @param {unknown} recentRaw The `/api/gateway/routes/recent` envelope.
 * @returns {typeof EMPTY_GATEWAY_LIVE_VM}
 */
export function toGatewayLiveRoutes(activeRaw, recentRaw) {
  const active = envelopeState(activeRaw)
  const recent = envelopeState(recentRaw)
  // Both reads come from one gateway: if either is unavailable the view is
  // incomplete, so it reports the degraded state rather than a partial truth —
  // attributed to the read that actually failed, never to the healthy one.
  if (!active.available || !recent.available) {
    const sourceState = !active.available ? active.sourceState : recent.sourceState
    return { ...EMPTY_GATEWAY_LIVE_VM, sourceState }
  }
  const leases = Array.isArray(active.data.leases) ? active.data.leases : []
  const inFlight = Array.isArray(active.data.in_flight) ? active.data.in_flight : []
  const routes = Array.isArray(recent.data.routes) ? recent.data.routes : []
  return {
    available: true,
    sourceState: active.sourceState,
    evidenceSince: orNull(active.data.evidence_since),
    truncated: recent.data.truncated === true,
    leases: leases.map(toLeaseRow),
    inFlight: inFlight.map(toInFlightRow),
    recent: routes.map(toRecentRow),
  }
}

export default toGatewayAccounts

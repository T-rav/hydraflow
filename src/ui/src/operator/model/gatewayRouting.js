/**
 * Gateway routing view models (issue #11534 ADR-0138; #11540 ADR-0142).
 * Pure — no fetch, no React.
 *
 * Three reducers over the `/api/gateway/...` envelopes:
 *
 *   toGatewayAccounts({available, source_state, data})  -> the Accounts view
 *   toGatewayLiveRoutes(activeEnvelope, recentEnvelope) -> the Live view
 *   toAccountAdmin({..., write_gate, editable})         -> the host-admin overlay
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
 *
 * The ONE exception to `num()` is capacity, and it is deliberate: a null
 * `lease_capacity` / `request_capacity` means "this account declares no
 * ceiling", which is the state every legacy account has always been in.
 * Coercing it to 0 would render "2 / 0" — an account over a limit nobody set.
 * Null survives as null through `nullableNum()`, and the panel says "no limit".
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

/** A declared ceiling, or `null` for "none declared". Never 0 standing in for null. */
function nullableNum(value) {
  return value == null ? null : num(value)
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

/**
 * Circuit tone. `closed` is NEUTRAL, never success — for the same reason
 * `unverified` is: a breaker that has not tripped is the absence of a verdict,
 * not evidence the lane is good.
 */
export function circuitTone(state) {
  return state === 'open' ? 'danger' : 'neutral'
}

/**
 * "used / limit", or "used / no limit" where the account declares no ceiling.
 * An undeclared capacity is stated rather than drawn as a number, because a
 * rendered 0 would read as an account that may take no work at all.
 */
export function formatCapacity(used, limit) {
  return `${Math.max(0, num(used))} / ${limit == null ? 'no limit' : num(limit)}`
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
  const circuitState = str(raw?.circuit_state) || 'closed'
  const leaseCapacity = nullableNum(raw?.lease_capacity)
  const requestCapacity = nullableNum(raw?.request_capacity)
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
    // ADR-0142 pool facts. Capacity stays nullable all the way to the label.
    leaseCapacity,
    requestCapacity,
    leaseCapacityLabel: formatCapacity(raw?.lease_count, leaseCapacity),
    requestCapacityLabel: formatCapacity(raw?.in_flight_count, requestCapacity),
    circuitState,
    circuitTone: circuitTone(circuitState),
    circuitConsecutiveFailures: num(raw?.circuit_consecutive_failures),
    circuitResetAt: orNull(raw?.circuit_reset_at),
    circuitLastCondition: orNull(raw?.circuit_last_condition),
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

export const EMPTY_ACCOUNT_ADMIN_VM = Object.freeze({
  available: false,
  sourceState: UNAVAILABLE_STATE,
  // `null`, not 0: revision 0 is a REAL revision (an overlay nobody has touched),
  // and a control that sent 0 while the chain was actually at 4 would be sending
  // a stale revision the gateway would rightly refuse — with a 409 that looked
  // like somebody else's edit rather than an unread view.
  revision: null,
  chainVerified: false,
  editable: false,
  writeGate: 'no-operator-identity',
  entries: Object.freeze([]),
})

const WRITE_GATE_MESSAGES = Object.freeze({
  'workspace-disabled':
    'The operator write plane is switched off (gateway_policy_workspace_enabled). Accounts are read-only.',
  'dashboard-not-loopback':
    'Account administration is disabled because the dashboard is bound beyond loopback. There is no operator authorization boundary on a shared socket (ADR-0138 D5).',
  'no-operator-identity':
    'Account administration needs an authenticated operator identity. Set HYDRAFLOW_OPERATOR_TOKEN on the dashboard host, then enter it below.',
})

/** Why host-admin is closed, in the words an operator can act on. */
export function accountWriteGateMessage(gate) {
  return WRITE_GATE_MESSAGES[gate] || ''
}

const ADMIN_REJECTION_MESSAGES = Object.freeze({
  'stale-revision':
    'Reload — someone else changed this. The administrative overlay moved after this view was loaded, so this action was refused rather than applied over theirs.',
  'unknown-account': 'The gateway has no account with that id.',
  'audit-chain-broken':
    'The gateway’s administrative audit chain does not verify. It refuses every mutation until the chain is repaired.',
  'unauthenticated-operator':
    'The operator token was not accepted. Check HYDRAFLOW_OPERATOR_TOKEN on the dashboard host.',
  'gateway-unreachable':
    'The gateway did not answer. It may still have applied this — reload the accounts view before trying again.',
  'gateway-not-configured':
    'No gateway control token is configured on this dashboard, so there is no control plane to administer.',
  'gateway-invalid-response':
    'The gateway answered with an unrecognised payload. This dashboard will not report a mutation it could not verify.',
  'gateway-refused':
    'The gateway refused this action with a code this dashboard does not recognise.',
})

/** One refusal, in the operator's words. A 409 says RELOAD, not "error". */
export function adminRejectionMessage(code) {
  if (!code) return ''
  return ADMIN_REJECTION_MESSAGES[code] || String(code)
}

function toAdminEntry(raw) {
  return {
    seq: num(raw?.seq),
    recordedAt: orNull(raw?.recorded_at),
    mutation: str(raw?.mutation),
    accountId: str(raw?.account_id),
    actor: str(raw?.actor),
    actorAuthenticatedBy: str(raw?.actor_authenticated_by),
    priorRevision: num(raw?.prior_revision),
    nextRevision: num(raw?.next_revision),
    administrativeState: orNull(raw?.administrative_state),
    revokedKeyCount: nullableNum(raw?.revoked_key_count),
  }
}

/**
 * The host-admin overlay: which revision the controls must be composed against,
 * whether the chain verifies, and whether this dashboard may write at all.
 *
 * `editable` is the BACKEND's verdict, never inferred here — the gate depends on
 * the dashboard's bind and its env-only credential, neither of which the browser
 * can see. An unread or unavailable feed is never editable.
 *
 * @param {unknown} raw The `/api/gateway/accounts/audit` envelope.
 * @returns {typeof EMPTY_ACCOUNT_ADMIN_VM}
 */
export function toAccountAdmin(raw) {
  const { available, sourceState, data } = envelopeState(raw)
  const writeGate = str(raw?.write_gate) || EMPTY_ACCOUNT_ADMIN_VM.writeGate
  if (!available) {
    return { ...EMPTY_ACCOUNT_ADMIN_VM, sourceState, writeGate }
  }
  const entries = Array.isArray(data.entries) ? data.entries : []
  const chainVerified = data.chain_verified === true
  return {
    available: true,
    sourceState,
    revision: nullableNum(data.revision),
    chainVerified,
    // A chain that does not verify has no trustworthy revision to compose
    // against, and the gateway refuses every mutation against it anyway — so
    // the console does not offer controls it already knows will 503.
    editable: raw?.editable === true && chainVerified,
    writeGate,
    // The gateway returns NO entries for an unverified chain; rendering
    // whatever arrived would present tampered history as history.
    entries: chainVerified ? entries.map(toAdminEntry) : [],
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
